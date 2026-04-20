"""
Detailed health check endpoint.

GET /health/detail  →  {
  "status": "ok" | "degraded" | "down",
  "services": {
    "database":   { "ok": true,  "latency_ms": 3 },
    "redis":      { "ok": true,  "latency_ms": 1 },
    "qdrant":     { "ok": true,  "version": "1.12.0" },
    "ai_yolo":    { "ok": true,  "device": "cpu" },
    "ai_reid":    { "ok": true },
    "cameras":    { "ok": true,  "total": 2, "running": 2 }
  }
}
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import redis.asyncio as aioredis
from fastapi import APIRouter
from loguru import logger
from sqlalchemy import text

from sentinel.core.config import get_settings
from sentinel.db.base import AsyncSessionLocal
from sentinel.pipeline.manager import get_manager

router = APIRouter(prefix="/health", tags=["health"])
cfg = get_settings()


async def _check_database() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        async with AsyncSessionLocal() as s:
            await s.execute(text("SELECT 1"))
        return {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _check_redis() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        r = aioredis.from_url(cfg.REDIS_URL, socket_connect_timeout=2)
        await r.ping()
        await r.aclose()
        return {"ok": True, "latency_ms": round((time.monotonic() - t0) * 1000, 1)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _check_qdrant() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{cfg.QDRANT_URL}/", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                data = await resp.json()
                return {
                    "ok": resp.status == 200,
                    "version": data.get("version", "?"),
                    "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _check_ai() -> dict[str, Any]:
    manager = get_manager()
    yolo_ok = manager._detection is not None and manager._detection.ready
    reid_ok = manager._reid is not None and manager._reid.ready
    return {
        "yolo": {"ok": yolo_ok, "device": cfg.YOLO_DEVICE},
        "reid": {"ok": reid_ok},
    }


async def _check_cameras() -> dict[str, Any]:
    cams = get_manager().list_cameras()
    running = sum(1 for c in cams if c["running"])
    return {
        "ok": True,
        "total": len(cams),
        "running": running,
    }


@router.get("/detail")
async def health_detail() -> dict[str, Any]:
    db, redis, qdrant, ai, cameras = await asyncio.gather(
        _check_database(),
        _check_redis(),
        _check_qdrant(),
        _check_ai(),
        _check_cameras(),
        return_exceptions=False,
    )

    critical_ok = db["ok"] and redis["ok"]  # type: ignore[index]
    any_degraded = not qdrant["ok"]  # type: ignore[index]

    overall = "ok" if (critical_ok and not any_degraded) else ("degraded" if critical_ok else "down")

    return {
        "status": overall,
        "version": cfg.APP_VERSION,
        "services": {
            "database": db,
            "redis": redis,
            "qdrant": qdrant,
            "ai": ai,
            "cameras": cameras,
        },
    }
