"""Edge Agent API — event ingestion, heartbeat, face sync."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, get_current_tenant
from sentinel.core.config import get_settings
from sentinel.core.events import EventBus, EventType, SentinelEvent
from sentinel.db.base import get_db
from sentinel.db.models.tenant import AgentRegistration

cfg = get_settings()

router = APIRouter(prefix="/agent", tags=["agent"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class AgentEvent(BaseModel):
    type: str
    camera_id: str = ""
    location_id: str = "default"
    track_id: str | None = None
    person_id: str | None = None
    confidence: float = 0.0
    payload: dict = {}
    timestamp_ms: int = 0


class EventBatchRequest(BaseModel):
    agent_id: str
    events: list[AgentEvent]


class HeartbeatRequest(BaseModel):
    agent_id: str
    agent_name: str = ""
    hostname: str = ""
    cameras_count: int = 0
    cpu_usage: float = 0.0
    memory_mb: float = 0.0
    fps: float = 0.0
    version: str = ""


class FaceUpload(BaseModel):
    person_id: str
    name: str
    category: str = "new"
    embedding: list[float]


# ── Event ingestion ──────────────────────────────────────────────────────────

def _require_real_tenant(tenant: TenantContext) -> None:
    if tenant.tenant_id == "__all__":
        raise HTTPException(400, "Agent endpoints require a real tenant API key, not superadmin")


@router.post("/events")
async def ingest_events(
    req: EventBatchRequest,
    tenant: TenantContext = Depends(get_current_tenant),
) -> dict:
    """Receive batch of events from edge agent. Publishes to EventBus."""
    _require_real_tenant(tenant)
    bus = EventBus.get()
    count = 0
    for ev in req.events:
        event = SentinelEvent(
            type=ev.type,
            camera_id=ev.camera_id,
            location_id=ev.location_id,
            tenant_id=tenant.tenant_id,
            track_id=ev.track_id or "",
            person_id=ev.person_id,
            confidence=ev.confidence,
            payload={**ev.payload, "agent_id": req.agent_id},
            timestamp_ms=ev.timestamp_ms or int(datetime.now(timezone.utc).timestamp() * 1000),
        )
        await bus.publish(event)
        count += 1

    return {"accepted": count, "tenant_id": tenant.tenant_id}


# ── Heartbeat ────────────────────────────────────────────────────────────────

@router.post("/heartbeat")
async def agent_heartbeat(
    req: HeartbeatRequest,
    request: Request,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Register or update edge agent status."""
    _require_real_tenant(tenant)
    client_ip = request.client.host if request.client else ""
    now = datetime.now(timezone.utc)

    agent = await db.get(AgentRegistration, req.agent_id)
    if agent:
        agent.hostname = req.hostname or agent.hostname
        agent.agent_name = req.agent_name or agent.agent_name
        agent.ip_address = client_ip
        agent.cameras_count = req.cameras_count
        agent.cpu_usage = req.cpu_usage
        agent.memory_mb = req.memory_mb
        agent.fps = req.fps
        agent.version = req.version
        agent.status = "online"
        agent.last_heartbeat = now
    else:
        agent = AgentRegistration(
            id=req.agent_id,
            tenant_id=tenant.tenant_id,
            agent_name=req.agent_name,
            hostname=req.hostname,
            ip_address=client_ip,
            cameras_count=req.cameras_count,
            cpu_usage=req.cpu_usage,
            memory_mb=req.memory_mb,
            fps=req.fps,
            version=req.version,
            status="online",
            last_heartbeat=now,
        )
        db.add(agent)

    await db.commit()
    return {"status": "ok", "agent_id": req.agent_id}


# ── Face sync ────────────────────────────────────────────────────────────────

@router.post("/faces/sync")
async def upload_faces(
    faces: list[FaceUpload],
    tenant: TenantContext = Depends(get_current_tenant),
) -> dict:
    """Upload face embeddings from edge agent to central Qdrant."""
    _require_real_tenant(tenant)
    from sentinel.pipeline.manager import get_manager

    manager = get_manager()
    reid = manager._reid
    if not reid or not reid.ready:
        return {"synced": 0, "error": "ReID service not ready"}

    import numpy as np
    synced = 0
    for face in faces:
        try:
            embedding = np.array(face.embedding, dtype=np.float32)
            await reid.register(
                person_id=face.person_id,
                name=face.name,
                category=face.category,
                embedding=embedding,
            )
            synced += 1
        except Exception as exc:
            logger.warning("Face sync error for {}: {}", face.person_id, exc)

    return {"synced": synced, "total": len(faces)}


@router.get("/faces")
async def download_faces(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Download tenant's face database for local ReID."""
    _require_real_tenant(tenant)

    from sentinel.db.models.person import Person
    from sentinel.pipeline.manager import get_manager

    result = await db.execute(
        select(Person).where(Person.tenant_id == tenant.tenant_id)
    )
    persons = result.scalars().all()

    manager = get_manager()
    reid = manager._reid
    faces: list[dict] = []

    if reid and reid.ready and reid._qdrant:
        from qdrant_client.models import Filter, FieldCondition, MatchAny
        person_ids = [p.id for p in persons]
        if person_ids:
            try:
                hits, _ = await reid._qdrant.scroll(
                    collection_name=cfg.QDRANT_COLLECTION_FACES,
                    scroll_filter=Filter(must=[
                        FieldCondition(key="person_id", match=MatchAny(any=person_ids))
                    ]),
                    limit=1000,
                    with_vectors=True,
                )
                for point in hits:
                    p = point.payload or {}
                    faces.append({
                        "person_id": p.get("person_id", ""),
                        "name": p.get("name", ""),
                        "category": p.get("category", "new"),
                        "embedding": point.vector if point.vector else [],
                    })
            except Exception as exc:
                logger.warning("Face download from Qdrant failed: {}", exc)

    return {"faces": faces, "tenant_id": tenant.tenant_id, "total": len(faces)}


@router.get("/config")
async def get_agent_config(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return tenant-specific configuration for edge agent."""
    from sentinel.db.models.tenant import Tenant
    t = await db.get(Tenant, tenant.tenant_id)
    return {
        "tenant_id": tenant.tenant_id,
        "tenant_name": t.name if t else "",
        "max_cameras": t.max_cameras if t else 4,
        "plan": t.plan if t else "free",
    }
