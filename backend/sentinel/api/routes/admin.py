"""Admin API — superadmin-only tenant & user management."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, hash_password, require_superadmin
from sentinel.db.base import get_db
from sentinel.db.models.person import Alert, Visit
from sentinel.db.models.tenant import AgentRegistration, Tenant, User

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateTenantRequest(BaseModel):
    name: str
    slug: str
    plan: str = "pro"
    max_cameras: int = 8
    contact_email: str | None = None
    contact_phone: str | None = None
    address: str | None = None


class CreateTenantResponse(BaseModel):
    id: str
    name: str
    slug: str
    api_key: str
    plan: str
    max_cameras: int


class TenantSummary(BaseModel):
    id: str
    name: str
    slug: str
    plan: str
    max_cameras: int
    is_active: bool
    created_at: str
    users_count: int = 0
    agents_count: int = 0
    visits_today: int = 0


class CreateUserRequest(BaseModel):
    email: str
    password: str
    name: str = ""
    role: str = "admin"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    role: str
    is_active: bool
    tenant_id: str | None


class GlobalStats(BaseModel):
    total_tenants: int
    active_tenants: int
    total_users: int
    total_agents: int
    agents_online: int
    total_visits_today: int
    total_alerts_today: int


# ── Tenant CRUD ──────────────────────────────────────────────────────────────

@router.post("/tenants", response_model=CreateTenantResponse, status_code=201)
async def create_tenant(
    req: CreateTenantRequest,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> CreateTenantResponse:
    existing = await db.execute(select(Tenant).where(Tenant.slug == req.slug))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Slug '{req.slug}' already taken")

    tenant = Tenant(
        id=str(uuid.uuid4()),
        name=req.name,
        slug=req.slug,
        api_key=f"sk-{secrets.token_hex(24)}",
        plan=req.plan,
        max_cameras=req.max_cameras,
        contact_email=req.contact_email,
        contact_phone=req.contact_phone,
        address=req.address,
    )
    db.add(tenant)
    await db.commit()
    await db.refresh(tenant)
    logger.info("🏢 Tenant created: {} ({})", tenant.name, tenant.slug)
    return CreateTenantResponse(
        id=tenant.id, name=tenant.name, slug=tenant.slug,
        api_key=tenant.api_key, plan=tenant.plan, max_cameras=tenant.max_cameras,
    )


@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> list[TenantSummary]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(select(Tenant).order_by(Tenant.created_at.desc()))
    tenants = result.scalars().all()
    out: list[TenantSummary] = []
    for t in tenants:
        users_q = await db.execute(
            select(func.count()).select_from(User).where(User.tenant_id == t.id)
        )
        agents_q = await db.execute(
            select(func.count()).select_from(AgentRegistration).where(AgentRegistration.tenant_id == t.id)
        )
        visits_q = await db.execute(
            select(func.count()).select_from(Visit)
            .where(Visit.tenant_id == t.id, Visit.entered_at >= today_start)
        )
        out.append(TenantSummary(
            id=t.id, name=t.name, slug=t.slug, plan=t.plan,
            max_cameras=t.max_cameras, is_active=t.is_active,
            created_at=t.created_at.isoformat() if t.created_at else "",
            users_count=users_q.scalar() or 0,
            agents_count=agents_q.scalar() or 0,
            visits_today=visits_q.scalar() or 0,
        ))
    return out


@router.get("/tenants/{tenant_id}")
async def get_tenant(
    tenant_id: str,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    users = await db.execute(select(User).where(User.tenant_id == tenant_id))
    agents = await db.execute(select(AgentRegistration).where(AgentRegistration.tenant_id == tenant_id))

    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "api_key": tenant.api_key,
        "plan": tenant.plan,
        "max_cameras": tenant.max_cameras,
        "is_active": tenant.is_active,
        "contact_email": tenant.contact_email,
        "contact_phone": tenant.contact_phone,
        "address": tenant.address,
        "created_at": tenant.created_at.isoformat() if tenant.created_at else "",
        "users": [
            {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active}
            for u in users.scalars()
        ],
        "agents": [
            {
                "id": a.id, "agent_name": a.agent_name, "hostname": a.hostname,
                "status": a.status, "cameras_count": a.cameras_count,
                "last_heartbeat": a.last_heartbeat.isoformat() if a.last_heartbeat else None,
            }
            for a in agents.scalars()
        ],
    }


@router.put("/tenants/{tenant_id}")
async def update_tenant(
    tenant_id: str,
    body: dict,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    allowed = {"name", "plan", "max_cameras", "is_active", "contact_email", "contact_phone", "address", "notes"}
    for k, v in body.items():
        if k in allowed:
            setattr(tenant, k, v)

    await db.commit()
    return {"updated": tenant_id}


@router.post("/tenants/{tenant_id}/regenerate-key")
async def regenerate_api_key(
    tenant_id: str,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    new_key = f"sk-{secrets.token_hex(24)}"
    tenant.api_key = new_key
    await db.commit()
    logger.warning("🔑 API key regenerated for tenant {}", tenant.slug)
    return {"api_key": new_key}


# ── Telegram ─────────────────────────────────────────────────────────────────

class TelegramUpdate(BaseModel):
    tenant_id: str
    telegram_chat_id: str | None = None


@router.put("/telegram")
async def set_telegram(
    body: TelegramUpdate,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set telegram_chat_id for a specific tenant."""
    tenant = await db.get(Tenant, body.tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    await db.execute(
        update(Tenant).where(Tenant.id == body.tenant_id).values(
            telegram_chat_id=body.telegram_chat_id,
        )
    )
    await db.commit()
    return {"updated": body.tenant_id}


@router.delete("/tenants/{tenant_id}")
async def delete_tenant(
    tenant_id: str,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete tenant and all associated data (CASCADE)."""
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")
    slug = tenant.slug
    await db.delete(tenant)
    await db.commit()
    logger.warning("🗑️ Tenant deleted: {} ({})", tenant.name, slug)
    return {"deleted": tenant_id}


# ── User management ──────────────────────────────────────────────────────────

@router.post("/tenants/{tenant_id}/users", response_model=UserResponse, status_code=201)
async def create_user(
    tenant_id: str,
    req: CreateUserRequest,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> UserResponse:
    tenant = await db.get(Tenant, tenant_id)
    if not tenant:
        raise HTTPException(404, "Tenant not found")

    existing = await db.execute(select(User).where(User.email == req.email))
    if existing.scalar_one_or_none():
        raise HTTPException(400, f"Email '{req.email}' already registered")

    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
        role=req.role,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    logger.info("👤 User created: {} for tenant {}", req.email, tenant.slug)
    return UserResponse(
        id=user.id, email=user.email, name=user.name,
        role=user.role, is_active=True, tenant_id=tenant_id,
    )


@router.delete("/tenants/{tenant_id}/users/{user_id}")
async def delete_user(
    tenant_id: str,
    user_id: str,
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Delete a user from a tenant."""
    user = await db.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        raise HTTPException(404, "User not found")
    email = user.email
    await db.delete(user)
    await db.commit()
    logger.info("👤 User deleted: {} from tenant {}", email, tenant_id)
    return {"deleted": user_id}


# ── Global stats ─────────────────────────────────────────────────────────────

@router.get("/stats", response_model=GlobalStats)
async def global_stats(
    _: TenantContext = Depends(require_superadmin),
    db: AsyncSession = Depends(get_db),
) -> GlobalStats:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    total_tenants = (await db.execute(select(func.count()).select_from(Tenant))).scalar() or 0
    active_tenants = (await db.execute(
        select(func.count()).select_from(Tenant).where(Tenant.is_active == True)  # noqa: E712
    )).scalar() or 0
    total_users = (await db.execute(select(func.count()).select_from(User))).scalar() or 0
    total_agents = (await db.execute(select(func.count()).select_from(AgentRegistration))).scalar() or 0
    agents_online = (await db.execute(
        select(func.count()).select_from(AgentRegistration).where(AgentRegistration.status == "online")
    )).scalar() or 0
    visits_today = (await db.execute(
        select(func.count()).select_from(Visit).where(Visit.entered_at >= today_start)
    )).scalar() or 0
    alerts_today = (await db.execute(
        select(func.count()).select_from(Alert).where(Alert.created_at >= today_start)
    )).scalar() or 0

    return GlobalStats(
        total_tenants=total_tenants,
        active_tenants=active_tenants,
        total_users=total_users,
        total_agents=total_agents,
        agents_online=agents_online,
        total_visits_today=visits_today,
        total_alerts_today=alerts_today,
    )
