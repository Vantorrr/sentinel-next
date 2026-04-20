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
    enabled: bool
    running: bool


@router.get("/", response_model=list[CameraResponse])
async def list_cameras(
    tenant: TenantContext = Depends(get_current_tenant),
) -> list[CameraResponse]:
    all_cams = get_manager().list_cameras()
    if tenant.role == "superadmin":
        return [CameraResponse(**c) for c in all_cams]
    return [
        CameraResponse(**c) for c in all_cams
        if c.get("location_id", "").startswith(tenant.tenant_id) or c.get("id", "").startswith("demo")
    ]


@router.post("/", response_model=CameraResponse, status_code=status.HTTP_201_CREATED)
async def add_camera(
    req: AddCameraRequest,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> CameraResponse:
    if tenant.tenant_id == "__all__":
        raise HTTPException(400, "Superadmin cannot add cameras — switch to tenant context")

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
        id=req.id, name=cam_cfg.name, url=req.url,
        location_id=location, enabled=True, running=False,
    )


@router.delete("/{camera_id}", status_code=status.HTTP_200_OK)
async def remove_camera(
    camera_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    record = await db.get(CameraRecord, camera_id)
    if record and tenant.tenant_id != "__all__" and record.tenant_id != tenant.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    if not get_manager().remove_camera(camera_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Camera not found")

    if record:
        await db.delete(record)
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
            return {"ok": False, "error": "Не удалось подключиться. Проверьте IP, порт, логин и пароль."}
        ret, frame = cap.read()
        if not ret or frame is None:
            cap.release()
            return {"ok": False, "error": "Подключение есть, но кадр получить не удалось."}
        h, w = frame.shape[:2]
        fps = cap.get(cv2.CAP_PROP_FPS)
        cap.release()
        return {"ok": True, "width": w, "height": h, "fps": round(fps, 1)}

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, _probe),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        result = {"ok": False, "error": "Таймаут 15 сек — камера не отвечает. Проверьте сеть и IP."}
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}

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
