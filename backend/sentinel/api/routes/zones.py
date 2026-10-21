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
from sentinel.pipeline.manager import get_manager
from sentinel.services.llm.redbook import REDBOOK_ZONE_PRESETS, scale_preset_polygon

router = APIRouter(prefix="/zones", tags=["zones"])

SUPERADMIN_TENANT = "__all__"


class ZoneCreate(BaseModel):
    name: str
    zone_type: ZoneType = ZoneType.CUSTOM
    polygon: list[list[int]]  # [[x1,y1], [x2,y2], ...]
    staff_required: bool = False
    max_absence_seconds: int = 180  # Красная книга: ресепшен не бросать
    max_wait_seconds: int = 60     # Красная книга гл.3: встречать сразу


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


class RedBookPresetBody(BaseModel):
    frame_width: int = 1920
    frame_height: int = 1080
    replace_existing: bool = False


@router.get("/presets/redbook")
async def list_redbook_presets(
    _: TenantContext = Depends(get_current_tenant),
) -> dict:
    """Красная книга Вай Тай — готовые шаблоны зон."""
    return {
        "name": "Вай Тай · Красная книга",
        "description": "Вход + Ресепшен + Ожидание/чай с таймерами по стандарту",
        "presets": REDBOOK_ZONE_PRESETS,
    }


@router.post("/camera/{camera_id}")
async def create_zone(
    camera_id: str,
    body: ZoneCreate,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if len(body.polygon) < 3:
        raise HTTPException(422, "Polygon must have at least 3 points")

    if tenant.tenant_id == SUPERADMIN_TENANT:
        raise HTTPException(400, "Войдите как админ салона, чтобы создавать зоны")
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
    try:
        await get_manager().reload_zones(camera_id)
    except Exception:
        pass
    return _zone_to_dict(zone)


@router.post("/camera/{camera_id}/presets/redbook")
async def apply_redbook_presets(
    camera_id: str,
    body: RedBookPresetBody,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """One-click: создать зоны Вход/Ресепшен/Ожидание по Красной книге."""
    if tenant.tenant_id == SUPERADMIN_TENANT:
        raise HTTPException(400, "Войдите как админ салона, чтобы применить пресет зон")

    if body.replace_existing:
        existing = (await db.execute(
            select(Zone).where(Zone.camera_id == camera_id, Zone.tenant_id == tenant.tenant_id)
        )).scalars().all()
        for z in existing:
            await db.delete(z)

    created: list[dict] = []
    for preset in REDBOOK_ZONE_PRESETS:
        poly = scale_preset_polygon(
            preset["polygon"], body.frame_width, body.frame_height
        )
        zone = Zone(
            id=str(uuid.uuid4()),
            camera_id=camera_id,
            tenant_id=tenant.tenant_id,
            name=preset["name"],
            zone_type=ZoneType(preset["zone_type"]),
            polygon=json.dumps(poly),
            staff_required=bool(preset["staff_required"]),
            max_absence_seconds=int(preset["max_absence_seconds"]),
            max_wait_seconds=int(preset["max_wait_seconds"]),
        )
        db.add(zone)
        created.append({
            "name": zone.name,
            "zone_type": zone.zone_type,
            "max_wait_seconds": zone.max_wait_seconds,
            "max_absence_seconds": zone.max_absence_seconds,
            "hint": preset.get("hint", ""),
        })

    await db.commit()
    try:
        await get_manager().reload_zones(camera_id)
    except Exception:
        pass
    return {
        "camera_id": camera_id,
        "applied": len(created),
        "zones": created,
        "note": "Подправьте полигоны под реальный кадр камеры после применения.",
    }


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
    try:
        await get_manager().reload_zones(zone.camera_id)
    except Exception:
        pass
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

    cam_id = zone.camera_id
    await db.delete(zone)
    await db.commit()
    try:
        await get_manager().reload_zones(cam_id)
    except Exception:
        pass
    return {"deleted": zone_id}
