"""Camera management REST endpoints — tenant-scoped, DB-persisted."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, get_current_tenant
from sentinel.db.base import get_db
from sentinel.db.models.camera import CameraRecord
from sentinel.pipeline.camera import CameraConfig
from sentinel.pipeline.manager import get_manager
from sentinel.pipeline.stream_target import (
    caller_may_see_camera,
    classify_stream_url,
    diagnostic_message,
    redact_stream_url,
    redact_text,
)

router = APIRouter(prefix="/cameras", tags=["cameras"])


class AddCameraRequest(BaseModel):
    id: str = Field(..., description="Unique camera ID")
    url: str = Field(..., description="RTSP URL, webcam index, or file path")
    name: str = ""
    location_id: str = "default"
    fps_inference: int = 10
    enabled: bool = True


class TestConnectionRequest(BaseModel):
    url: str = Field(..., description="RTSP URL to test")


class CameraResponse(BaseModel):
    id: str
    name: str
    url: str
    location_id: str
    tenant_id: str = ""
    enabled: bool
    running: bool
    stream_status: str = "offline"
    frames_received: int = 0
    last_error: str = ""
    host_class: str = ""
    requirement: str = ""


@router.get("/", response_model=list[CameraResponse])
async def list_cameras(
    tenant: TenantContext = Depends(get_current_tenant),
) -> list[CameraResponse]:
    all_cams = get_manager().list_cameras()
    if tenant.role == "superadmin":
        return [CameraResponse(**c) for c in all_cams]
    return [
        CameraResponse(**c) for c in all_cams
        if c.get("location_id", "").startswith(tenant.tenant_id)
        or c.get("tenant_id") == tenant.tenant_id
    ]


@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def add_camera(
    req: AddCameraRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CameraResponse:
    if tenant.tenant_id == "__all__":
        raise HTTPException(
            400,
            "Superadmin cannot add cameras. "
            "Войдите пользователем салона: переключения салона нет.",
        )

    target = classify_stream_url(req.url)
    if target.blocked:
        raise HTTPException(422, detail={
            "code": "stream_not_usable",
            "message": target.reason,
            "host_class": target.host_class,
            "requirement": target.requirement,
        })

    location = f"{tenant.tenant_id}/{req.location_id}"
    cam_cfg = CameraConfig(
        id=req.id,
        url=req.url,
        name=req.name or req.id,
        location_id=location,
        tenant_id=tenant.tenant_id,
        fps_inference=req.fps_inference,
        enabled=req.enabled,
    )

    # Persist to DB
    existing = await db.get(CameraRecord, req.id)
    if existing:
        raise HTTPException(400, f"Camera '{req.id}' already exists")

    record = CameraRecord(
        id=req.id,
        tenant_id=tenant.tenant_id,
        url=req.url,
        name=req.name or req.id,
        location_id=req.location_id,
        fps_inference=req.fps_inference,
        enabled=req.enabled,
    )
    db.add(record)
    await db.commit()

    try:
        get_manager().add_camera(cam_cfg)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    cams = {c["id"]: c for c in get_manager().list_cameras()}
    cam_data = cams.get(req.id)
    if cam_data:
        return CameraResponse(**cam_data)
    return CameraResponse(
        id=req.id, name=cam_cfg.name, url=redact_stream_url(req.url),
        location_id=location, enabled=True, running=False,
        stream_status="connecting", host_class=target.host_class,
        requirement=target.requirement,
    )


@router.delete("/{camera_id}", status_code=status.HTTP_200_OK)
async def remove_camera(
    camera_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from sentinel.db.models.zone import Zone

    record = await db.get(CameraRecord, camera_id)
    if record and tenant.tenant_id != "__all__" and record.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Zones have no FK to cameras — delete explicitly so salon config stays clean
    zone_q = select(Zone).where(Zone.camera_id == camera_id)
    if tenant.tenant_id != "__all__":
        zone_q = zone_q.where(Zone.tenant_id == tenant.tenant_id)
    for z in (await db.execute(zone_q)).scalars().all():
        await db.delete(z)

    removed_runtime = get_manager().remove_camera(camera_id)
    if record:
        await db.delete(record)
        await db.commit()
    elif not removed_runtime:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")
    else:
        await db.commit()

    return {"removed": camera_id}


@router.post("/test")
async def test_connection(
    req: TestConnectionRequest,
    tenant: TenantContext = Depends(get_current_tenant),
) -> dict:
    """Try opening an RTSP/video stream and grab one frame."""
    url = req.url.strip()
    if not url:
        raise HTTPException(400, "URL is empty")

    loop = asyncio.get_event_loop()

    def _probe() -> dict:
        import cv2
        cap = cv2.VideoCapture(url)
        if not cap.isOpened():
            return {
                "ok": False,
                "frames": 0,
                "error": "Не удалось подключиться. Проверьте адрес, порт, логин и пароль.",
            }
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            return {
                "ok": False,
                "frames": 0,
                "error": "Подключение есть, но кадр получить не удалось.",
            }
        h, w = frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        return {"ok": True, "frames": 1, "width": w, "height": h, "fps": round(fps, 1)}

    target = classify_stream_url(url)
    if target.blocked:
        return {
            "ok": False,
            "frames": 0,
            "host_class": target.host_class,
            "requirement": target.requirement,
            "error": target.reason,
        }

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _probe),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        result = {
            "ok": False,
            "frames": 0,
            "error": "Таймаут 15 сек — кадр не получен. Проверьте маршрут и адрес.",
        }
    except Exception as exc:
        result = {"ok": False, "frames": 0, "error": redact_text(str(exc))[:300]}

    if isinstance(result.get("error"), str):
        result["error"] = redact_text(result["error"])[:300]
    result.setdefault("host_class", target.host_class)
    result.setdefault("requirement", target.requirement)
    return result


@router.get("/{camera_id}/heatmap")
async def get_heatmap(
    camera_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if tenant.tenant_id != "__all__":
        record = await db.get(CameraRecord, camera_id)
        if not record or record.tenant_id != tenant.tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
    return get_manager().get_heatmap(camera_id)


@router.get("/{camera_id}/diagnostics")
async def camera_diagnostics(
    camera_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Safe stream status. Does not open the camera and does not rewrite the stored URL."""
    record = await db.get(CameraRecord, camera_id)
    runtime = get_manager().diagnostics(camera_id)
    if runtime is None and record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    owner = record.tenant_id if record else (runtime or {}).get("tenant_id")
    allowed = caller_may_see_camera(
        tenant.tenant_id,
        owner if isinstance(owner, str) else None,
        is_superadmin=tenant.role == "superadmin" or tenant.tenant_id == "__all__",
    )
    if not allowed:
        # A DB row confirms the id; a runtime-only id must not be confirmed.
        if record:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    if runtime is None and record is not None:
        target = classify_stream_url(record.url)
        status_name = "unreachable" if target.blocked else "offline"
        return {
            "id": record.id,
            "name": record.name,
            "loaded": False,
            "url": redact_stream_url(record.url),
            "running": False,
            "stream_status": status_name,
            "frames_received": 0,
            "last_error": target.reason if target.blocked else "",
            "host_class": target.host_class,
            "requirement": target.requirement,
            "task_alive": False,
            "lan_substituted": False,
            "ezviz_serial_set": bool(record.ezviz_serial),
            "ezviz_channel": record.ezviz_channel,
            "message": diagnostic_message(
                record.url,
                status=status_name,
                frames_received=0,
                last_error=target.reason if target.blocked else "",
            ),
        }

    assert runtime is not None
    if record:
        runtime["ezviz_serial_set"] = bool(record.ezviz_serial)
        runtime["ezviz_channel"] = record.ezviz_channel
    runtime["loaded"] = True
    runtime["lan_substituted"] = False
    return runtime


async def load_cameras_from_db() -> list[CameraConfig]:
    """Load all enabled cameras from DB — called on startup."""
    from sentinel.db.base import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(CameraRecord).where(CameraRecord.enabled == True)  # noqa: E712
        )).scalars().all()

    configs: list[CameraConfig] = []
    for r in rows:
        configs.append(CameraConfig(
            id=r.id,
            url=r.url,
            name=r.name,
            location_id=f"{r.tenant_id}/{r.location_id}",
            tenant_id=r.tenant_id,
            fps_inference=r.fps_inference,
            enabled=r.enabled,
        ))
    return configs
