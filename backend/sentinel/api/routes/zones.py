"""Zone CRUD API — tenant-scoped."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, get_current_tenant
from sentinel.db.base import get_db
from sentinel.db.models.zone import Zone, ZoneType

router = APIRouter(prefix="/zones", tags=["zones"])

SUPERADMIN_TENANT = "__all__"


class ZoneCreate(BaseModel):
    name: str
    zone_type: ZoneType = ZoneType.CUSTOM
    polygon: list[list[int]]  # [[x1,y1], [x2,y2], ...]
    staff_required: bool = False
    max_absence_seconds: int = 300
    max_wait_seconds: int = 120


class ZoneUpdate(BaseModel):
    name: str | None = None
    zone_type: ZoneType | None = None
    polygon: list[list[int]] | None = None
    is_active: bool | None = None
    staff_required: bool | None = None
    max_absence_seconds: int | None = None
    max_wait_seconds: int | None = None


def _zone_to_dict(z: Zone) -> dict:
    return {
        "id": z.id,
        "camera_id": z.camera_id,
        "tenant_id": z.tenant_id,
        "name": z.name,
        "zone_type": z.zone_type,
        "polygon": json.loads(z.polygon),
        "is_active": z.is_active,
        "staff_required": z.staff_required,
        "max_absence_seconds": z.max_absence_seconds,
        "max_wait_seconds": z.max_wait_seconds,
        "created_at": z.created_at.isoformat() if z.created_at else None,
        "updated_at": z.updated_at.isoformat() if z.updated_at else None,
    }


@router.get("")
async def list_zones(
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(Zone)
    if tenant.tenant_id != SUPERADMIN_TENANT:
        stmt = stmt.where(Zone.tenant_id == tenant.tenant_id)
    stmt = stmt.order_by(Zone.camera_id, Zone.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [_zone_to_dict(z) for z in rows]


@router.get("/camera/{camera_id}")
async def list_zones_for_camera(
    camera_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(Zone).where(Zone.camera_id == camera_id)
    if tenant.tenant_id != SUPERADMIN_TENANT:
        stmt = stmt.where(Zone.tenant_id == tenant.tenant_id)
    stmt = stmt.order_by(Zone.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [_zone_to_dict(z) for z in rows]


@router.post("/camera/{camera_id}")
async def create_zone(
    camera_id: str,
    body: ZoneCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if tenant.tenant_id == SUPERADMIN_TENANT:
        raise HTTPException(400, "Superadmin cannot create zones — switch to tenant context")
    if len(body.polygon) < 3:
        raise HTTPException(422, "Polygon must have at least 3 points")

    zone = Zone(
        id=str(uuid.uuid4()),
        camera_id=camera_id,
        tenant_id=tenant.tenant_id,
        name=body.name,
        zone_type=body.zone_type,
        polygon=json.dumps(body.polygon),
        staff_required=body.staff_required,
        max_absence_seconds=body.max_absence_seconds,
        max_wait_seconds=body.max_wait_seconds,
    )
    db.add(zone)
    await db.commit()
    await db.refresh(zone)
    return _zone_to_dict(zone)


@router.put("/{zone_id}")
async def update_zone(
    zone_id: str,
    body: ZoneUpdate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    zone = (await db.execute(
        select(Zone).where(Zone.id == zone_id)
    )).scalar_one_or_none()
    if not zone:
        raise HTTPException(404, "Zone not found")
    if tenant.tenant_id != SUPERADMIN_TENANT and zone.tenant_id != tenant.tenant_id:
        raise HTTPException(403, "Access denied")

    for field, value in body.model_dump(exclude_none=True).items():
        if field == "polygon":
            if len(value) < 3:
                raise HTTPException(422, "Polygon must have at least 3 points")
            setattr(zone, field, json.dumps(value))
        else:
            setattr(zone, field, value)

    await db.commit()
    await db.refresh(zone)
    return _zone_to_dict(zone)


@router.delete("/{zone_id}")
async def delete_zone(
    zone_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    zone = (await db.execute(
        select(Zone).where(Zone.id == zone_id)
    )).scalar_one_or_none()
    if not zone:
        raise HTTPException(404, "Zone not found")
    if tenant.tenant_id != SUPERADMIN_TENANT and zone.tenant_id != tenant.tenant_id:
        raise HTTPException(403, "Access denied")

    await db.delete(zone)
    await db.commit()
    return {"deleted": zone_id}
