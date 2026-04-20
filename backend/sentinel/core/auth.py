"""
Multi-tenant authentication & authorization.

Auth methods (checked in order):
  1. API Key via `X-API-Key` header — for edge agents + scripts
     -> resolves tenant from `tenants.api_key`
  2. JWT Bearer token — for dashboard users
     -> contains tenant_id, role, user_id

Roles:
  - superadmin: sees all tenants, manages platform
  - admin: manages their own salon (cameras, persons, settings)
  - viewer: read-only access to their salon data

Public endpoints (no auth):
  - GET  /health, /health/detail
  - GET  /docs, /redoc, /openapi.json
  - POST /auth/login
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from loguru import logger
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.config import get_settings
from sentinel.db.base import AsyncSessionLocal

cfg = get_settings()

_ALGORITHM = "HS256"
_TOKEN_EXPIRE_HOURS = 72

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_bearer = HTTPBearer(auto_error=False)

_DOC_PATHS = {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"} if cfg.DEBUG else set()
PUBLIC_PATHS = {"/health", "/health/detail"} | _DOC_PATHS


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class TenantContext:
    """Resolved auth context available to every route."""
    tenant_id: str
    role: str          # "superadmin" | "admin" | "viewer"
    user_id: str = ""
    tenant_name: str = ""


class TokenPayload(BaseModel):
    sub: str               # user_id
    tenant_id: str
    role: str
    tenant_name: str = ""
    exp: datetime | None = None


# ── Password helpers ─────────────────────────────────────────────────────────

def hash_password(raw: str) -> str:
    return _pwd_ctx.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    return _pwd_ctx.verify(raw, hashed)


# ── JWT helpers ──────────────────────────────────────────────────────────────

def create_access_token(
    user_id: str,
    tenant_id: str,
    role: str,
    tenant_name: str = "",
    expires_hours: int = _TOKEN_EXPIRE_HOURS,
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=expires_hours)
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role,
        "tenant_name": tenant_name,
        "exp": expire,
    }
    return jwt.encode(payload, cfg.SECRET_KEY, algorithm=_ALGORITHM)


def verify_token(token: str) -> TokenPayload:
    try:
        data = jwt.decode(token, cfg.SECRET_KEY, algorithms=[_ALGORITHM])
        return TokenPayload(**data)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid token: {exc}",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ── Resolve tenant from API key (DB lookup) ──────────────────────────────────

async def _resolve_tenant_by_api_key(api_key: str) -> TenantContext | None:
    from sentinel.db.models.tenant import Tenant
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Tenant).where(Tenant.api_key == api_key, Tenant.is_active == True)  # noqa: E712
        )
        tenant = result.scalar_one_or_none()
        if tenant:
            return TenantContext(
                tenant_id=tenant.id,
                role="admin",
                user_id=f"agent@{tenant.slug}",
                tenant_name=tenant.name,
            )
    return None


# ── Dependencies ─────────────────────────────────────────────────────────────

async def get_current_tenant(
    request: Request,
    api_key: str | None = Depends(_api_key_header),
    bearer: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> TenantContext:
    """
    Resolve auth context. Used by all protected routes.
    Returns TenantContext with tenant_id and role.
    """
    # Method 1: SECRET_KEY = superadmin passthrough
    if api_key and api_key == cfg.SECRET_KEY:
        return TenantContext(
            tenant_id="__all__",
            role="superadmin",
            user_id="superadmin",
            tenant_name="Platform",
        )

    # Method 2: Tenant API key (edge agents, scripts)
    if api_key:
        ctx = await _resolve_tenant_by_api_key(api_key)
        if ctx:
            return ctx

    # Method 3: Bearer JWT (dashboard users)
    if bearer and bearer.credentials:
        payload = verify_token(bearer.credentials)
        return TenantContext(
            tenant_id=payload.tenant_id,
            role=payload.role,
            user_id=payload.sub,
            tenant_name=payload.tenant_name,
        )

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация. Передайте X-API-Key или Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_superadmin(
    tenant: TenantContext = Depends(get_current_tenant),
) -> TenantContext:
    if tenant.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin access required")
    return tenant


async def require_ws_auth(
    websocket: WebSocket,
    token: str | None = Query(default=None),
) -> TenantContext:
    if not token:
        if cfg.DEMO_MODE:
            return TenantContext(tenant_id="legacy", role="admin", user_id="demo")
        await websocket.close(code=4001, reason="Token required: ?token=<JWT>")
        raise HTTPException(status_code=401, detail="WS auth required")

    # SECRET_KEY = superadmin
    if token == cfg.SECRET_KEY:
        return TenantContext(
            tenant_id="__all__", role="superadmin",
            user_id="superadmin", tenant_name="Platform",
        )

    # Try as tenant API key
    ctx = await _resolve_tenant_by_api_key(token)
    if ctx:
        return ctx

    # Try as JWT
    try:
        payload = verify_token(token)
        return TenantContext(
            tenant_id=payload.tenant_id,
            role=payload.role,
            user_id=payload.sub,
            tenant_name=payload.tenant_name,
        )
    except HTTPException:
        await websocket.close(code=4001, reason="Invalid token")
        raise


# ── Auth router ──────────────────────────────────────────────────────────────

auth_router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = _TOKEN_EXPIRE_HOURS * 3600
    user: dict


@auth_router.post("/login", response_model=LoginResponse)
async def login(req: LoginRequest) -> LoginResponse:
    """Authenticate with email + password, receive JWT."""
    from sentinel.db.models.tenant import User, Tenant

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User).where(User.email == req.email, User.is_active == True)  # noqa: E712
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Неверный email или пароль")

        tenant_name = ""
        tenant_id = user.tenant_id or ""

        if user.role == "superadmin":
            tenant_id = "__all__"
            tenant_name = "Platform"

        if user.tenant_id:
            t = await session.get(Tenant, user.tenant_id)
            if t:
                tenant_name = t.name

        # Update last_login
        await session.execute(
            update(User)
            .where(User.id == user.id)
            .values(last_login=datetime.now(timezone.utc))
        )
        await session.commit()

    token = create_access_token(
        user_id=user.id,
        tenant_id=tenant_id,
        role=user.role,
        tenant_name=tenant_name,
    )

    logger.info("🔐 Login: {} ({})", user.email, user.role)

    return LoginResponse(
        access_token=token,
        user={
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "role": user.role,
            "tenant_id": tenant_id,
            "tenant_name": tenant_name,
        },
    )


class LegacyApiKeyLogin(BaseModel):
    api_key: str


@auth_router.post("/token", response_model=LoginResponse)
async def legacy_token(req: LegacyApiKeyLogin) -> LoginResponse:
    """Legacy: exchange API key for JWT. Used by old frontends / scripts."""
    ctx = await _resolve_tenant_by_api_key(req.api_key)
    if not ctx:
        # Fallback: check if it matches SECRET_KEY (superadmin)
        if req.api_key == cfg.SECRET_KEY:
            token = create_access_token(
                user_id="superadmin",
                tenant_id="__all__",
                role="superadmin",
                tenant_name="Platform",
            )
            return LoginResponse(
                access_token=token,
                user={
                    "id": "superadmin",
                    "email": "admin@sentinel.ai",
                    "name": "Superadmin",
                    "role": "superadmin",
                    "tenant_id": "__all__",
                    "tenant_name": "Platform",
                },
            )
        raise HTTPException(status_code=401, detail="Неверный ключ")

    token = create_access_token(
        user_id=ctx.user_id,
        tenant_id=ctx.tenant_id,
        role=ctx.role,
        tenant_name=ctx.tenant_name,
    )
    return LoginResponse(
        access_token=token,
        user={
            "id": ctx.user_id,
            "email": "",
            "name": ctx.tenant_name,
            "role": ctx.role,
            "tenant_id": ctx.tenant_id,
            "tenant_name": ctx.tenant_name,
        },
    )


@auth_router.get("/me")
async def me(tenant: TenantContext = Depends(get_current_tenant)) -> dict:
    """Return current user info from token."""
    return {
        "user_id": tenant.user_id,
        "tenant_id": tenant.tenant_id,
        "tenant_name": tenant.tenant_name,
        "role": tenant.role,
    }
