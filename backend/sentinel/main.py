"""
Sentinel-Next — FastAPI application entry point.

Multi-tenant SaaS platform for AI business surveillance.

Startup sequence:
  1. Configure loguru
  2. Connect EventBus (Redis)
  3. Load AI models (YOLO, InsightFace)
  4. Start DBWriter + LLM Summarizer background tasks
  5. Seed superadmin user if not exists
  6. Optional: start demo camera if DEMO_MODE=true
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from sentinel.api.routes.analytics import router as analytics_router
from sentinel.api.routes.cameras import router as cameras_router
from sentinel.api.routes.chat import router as chat_router
from sentinel.api.routes.health import router as health_router
from sentinel.api.routes.persons import router as persons_router
from sentinel.api.routes.zones import router as zones_router
from sentinel.api.websocket import router as ws_router
from sentinel.core.auth import PUBLIC_PATHS, auth_router, verify_token, hash_password
from sentinel.core.config import get_settings
from sentinel.core.events import EventBus
from sentinel.core.logging_setup import setup_logging
from sentinel.pipeline.camera import CameraConfig
from sentinel.pipeline.manager import get_manager
from sentinel.services.analytics.db_writer import DBWriter
from sentinel.services.llm.summarizer import SceneSummarizer
from sentinel.services.notifications.telegram import TelegramNotifier

cfg = get_settings()
setup_logging(cfg.LOG_LEVEL)

try:
    import sentry_sdk
    if cfg.SENTRY_DSN:
        sentry_sdk.init(dsn=cfg.SENTRY_DSN, traces_sample_rate=0.05)
        logger.info("Sentry configured")
except ImportError:
    pass


# ── Auth middleware ───────────────────────────────────────────────────────────

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: ...) -> Response:  # type: ignore[override]
        path = request.url.path

        if (
            path in PUBLIC_PATHS
            or path.startswith("/auth")
            or path.startswith("/ws/")
            or request.headers.get("upgrade", "").lower() == "websocket"
        ):
            return await call_next(request)

        # SECRET_KEY = superadmin passthrough
        api_key = request.headers.get("x-api-key")
        if api_key and api_key == cfg.SECRET_KEY:
            return await call_next(request)

        # Tenant API key lookup
        if api_key:
            from sentinel.core.auth import _resolve_tenant_by_api_key
            ctx = await _resolve_tenant_by_api_key(api_key)
            if ctx:
                return await call_next(request)

        # Bearer JWT
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token_valid = False
            try:
                verify_token(auth_header[7:])
                token_valid = True
            except Exception:
                pass
            if token_valid:
                return await call_next(request)

        return JSONResponse(
            status_code=401,
            content={"detail": "Требуется авторизация."},
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Seed superadmin ──────────────────────────────────────────────────────────

async def _seed_superadmin() -> None:
    """Create default superadmin user if none exists."""
    from sqlalchemy import select
    from sentinel.db.base import AsyncSessionLocal
    from sentinel.db.models.tenant import User

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.role == "superadmin").limit(1)
        )
        if result.scalar_one_or_none():
            return

        admin = User(
            id=str(uuid.uuid4()),
            tenant_id=None,
            email="admin@sentinel.ai",
            password_hash=hash_password("admin"),
            name="Superadmin",
            role="superadmin",
            is_active=True,
        )
        session.add(admin)
        await session.commit()
        logger.info("🔐 Superadmin seeded: admin@sentinel.ai / admin (CHANGE PASSWORD!)")


# ── Lifespan ─────────────────────────────────────────────────────────────────

async def _ezviz_stream_refresh_loop() -> None:
    """Refresh EZVIZ HLS stream URLs every 20 hours (they expire ~24h)."""
    REFRESH_INTERVAL = 20 * 3600  # 20 hours
    while True:
        await asyncio.sleep(REFRESH_INTERVAL)
        try:
            from sentinel.services.hikconnect.client import get_hikconnect_client
            from sentinel.db.base import AsyncSessionLocal
            from sentinel.db.models.camera import CameraRecord
            from sqlalchemy import select

            client = get_hikconnect_client()
            if not client:
                continue

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(CameraRecord).where(CameraRecord.ezviz_serial.isnot(None))
                )
                ezviz_cameras = result.scalars().all()

                for cam in ezviz_cameras:
                    try:
                        stream = await client.get_live_stream_url(
                            device_serial=cam.ezviz_serial,  # type: ignore[arg-type]
                            channel_no=cam.ezviz_channel or 1,
                        )
                        if stream.url and stream.url != cam.url:
                            cam.url = stream.url
                            manager = get_manager()
                            manager.remove_camera(cam.id)
                            manager.add_camera(CameraConfig(
                                id=cam.id,
                                url=stream.url,
                                location_id=cam.location_id or "default",
                                name=cam.name or cam.id,
                                tenant_id=cam.tenant_id,
                                fps_inference=cam.fps_inference or 10,
                            ))
                    except Exception as exc:
                        logger.warning("EZVIZ refresh failed for {}: {}", cam.id, exc)

                await db.commit()
                logger.info("📹 EZVIZ stream URLs refreshed for {} cameras", len(ezviz_cameras))
        except Exception as exc:
            logger.error("EZVIZ refresh loop error: {}", exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    logger.opt(colors=True).info(
        "🛡  <bold><cyan>Sentinel-Next {}</cyan></bold> — starting up",
        cfg.APP_VERSION,
    )

    bus = EventBus.get()
    await bus.connect()

    manager = get_manager()
    await manager.startup()

    db_writer = DBWriter()
    db_writer_task = asyncio.create_task(db_writer.run(), name="db-writer")

    summarizer = SceneSummarizer()
    summarizer_task = asyncio.create_task(summarizer.run(), name="llm-summarizer")

    tg_task: asyncio.Task[None] | None = None
    if cfg.TELEGRAM_BOT_TOKEN:
        tg_notifier = TelegramNotifier()
        tg_task = asyncio.create_task(tg_notifier.run(), name="telegram-notifier")
        logger.opt(colors=True).info("📱 <green>Telegram notifier</green> enabled")

    await _seed_superadmin()

    # Auto-load persisted cameras from DB
    try:
        from sentinel.api.routes.cameras import load_cameras_from_db
        saved_cameras = await load_cameras_from_db()
        for cam_cfg in saved_cameras:
            manager.add_camera(cam_cfg)
        if saved_cameras:
            logger.info("📷 Loaded {} cameras from DB", len(saved_cameras))
    except Exception as exc:
        logger.warning("Failed to load cameras from DB: {}", exc)

    # Auto-init Hik-Connect if credentials configured
    ezviz_refresh_task: asyncio.Task[None] | None = None
    if cfg.HIKCONNECT_EMAIL and cfg.HIKCONNECT_PASSWORD:
        try:
            from sentinel.services.hikconnect.client import init_hikconnect
            await init_hikconnect(cfg.HIKCONNECT_EMAIL, cfg.HIKCONNECT_PASSWORD, cfg.HIKCONNECT_REGION)
            logger.opt(colors=True).info("📹 <green>Hik-Connect</green> cloud connected ({})", cfg.HIKCONNECT_EMAIL)
            ezviz_refresh_task = asyncio.create_task(
                _ezviz_stream_refresh_loop(), name="ezviz-refresh"
            )
        except Exception as exc:
            logger.warning("Hik-Connect login failed: {} — configure via admin panel", exc)

    if cfg.DEMO_MODE:
        logger.opt(colors=True).info("🎬 <yellow>DEMO MODE</yellow> — synthetic camera added")
        manager.add_camera(CameraConfig(
            id="demo-cam-1",
            url="demo",
            name="Demo Camera",
            location_id="demo",
            fps_inference=5,
        ))

    logger.opt(colors=True).success(
        "✅ <bold>Sentinel-Next READY</bold> → http://{}:{}/docs",
        cfg.HOST, cfg.PORT,
    )
    yield

    logger.info("🛑 Sentinel-Next shutting down…")
    db_writer_task.cancel()
    summarizer_task.cancel()
    tasks_to_cancel = [db_writer_task, summarizer_task]
    if tg_task:
        tg_task.cancel()
        tasks_to_cancel.append(tg_task)
    if ezviz_refresh_task:
        ezviz_refresh_task.cancel()
        tasks_to_cancel.append(ezviz_refresh_task)
    await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
    await manager.shutdown()
    await bus.disconnect()
    logger.info("👋 Stopped.")


app = FastAPI(
    title=cfg.APP_NAME,
    version=cfg.APP_VERSION,
    description="Multi-tenant AI Surveillance & Business Intelligence SaaS",
    lifespan=lifespan,
    docs_url="/docs" if cfg.DEBUG else None,
    redoc_url="/redoc" if cfg.DEBUG else None,
)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cfg.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
except ImportError:
    pass

# ── Routes ─────────────────────────────────────────────────────────────────────
app.include_router(auth_router)
app.include_router(cameras_router, prefix="/api/v1")
app.include_router(persons_router, prefix="/api/v1")
app.include_router(analytics_router, prefix="/api/v1")
app.include_router(chat_router, prefix="/api/v1")
app.include_router(zones_router, prefix="/api/v1")
app.include_router(health_router)
app.include_router(ws_router)

# Import admin + agent routes
try:
    from sentinel.api.routes.admin import router as admin_router
    app.include_router(admin_router)
except ImportError as exc:
    logger.warning("Admin routes not loaded: {}", exc)

try:
    from sentinel.api.routes.agent import router as agent_router
    app.include_router(agent_router, prefix="/api/v1")
except ImportError as exc:
    logger.warning("Agent routes not loaded: {}", exc)

try:
    from sentinel.api.routes.hikconnect import router as hikconnect_router
    app.include_router(hikconnect_router, prefix="/api/v1")
except ImportError as exc:
    logger.warning("HikConnect routes not loaded: {}", exc)


@app.get("/health", tags=["health"])
async def health_basic() -> dict:
    return {
        "status": "ok",
        "version": cfg.APP_VERSION,
        "cameras": len(get_manager().list_cameras()),
        "demo_mode": cfg.DEMO_MODE,
    }
