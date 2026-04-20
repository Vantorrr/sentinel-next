"""
Hik-Connect cloud integration — login with email + password (same as the app).

No developer accounts needed. Just your Hik-Connect login.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, get_current_tenant, require_superadmin
from sentinel.db.base import get_db
from sentinel.db.models.camera import CameraRecord
from sentinel.pipeline.camera import CameraConfig
from sentinel.pipeline.manager import get_manager
from sentinel.services.hikconnect.client import (
    HikConnectError,
    get_hikconnect_client,
    init_hikconnect,
)

router = APIRouter(prefix="/hikconnect", tags=["hikconnect"])


class HikConnectLogin(BaseModel):
    email: str
    password: str
    region: str = "ru"


class ImportCameraBody(BaseModel):
    device_serial: str
    channel_no: int = 1
    name: str = ""
    location_id: str = "default"
    quality: int = 2  # 1=HD 2=SD


@router.post("/connect")
async def connect_hikconnect(
    body: HikConnectLogin,
    _: TenantContext = Depends(require_superadmin),
) -> dict:
    """Login to Hik-Connect and list all cameras across all devices."""
    try:
        client = await init_hikconnect(body.email, body.password, body.region)
        devices = await client.get_devices()
        all_cameras = await client.list_all_cameras()
        logger.info(
            "Hik-Connect: logged in, {} devices, {} cameras",
            len(devices), len(all_cameras),
        )
        return {
            "connected": True,
            "devices_found": len(devices),
            "cameras_found": len(all_cameras),
            "devices": [
                {
                    "serial": d.serial,
                    "name": d.name,
                    "type": d.device_type,
                    "version": d.version,
                }
                for d in devices
            ],
            "cameras": [
                {
                    "device_serial": c.device_serial,
                    "camera_id": c.camera_id,
                    "name": c.name,
                    "channel_no": c.channel_no,
                    "status": "online" if c.signal_status == 1 else "offline",
                }
                for c in all_cameras
            ],
        }
    except HikConnectError as exc:
        raise HTTPException(400, f"Hik-Connect: {exc.message}")
    except Exception as exc:
        logger.error("Hik-Connect login error: {}", exc)
        raise HTTPException(500, "Ошибка подключения к Hik-Connect")


@router.get("/cameras")
async def list_hikconnect_cameras(
    _: TenantContext = Depends(get_current_tenant),
) -> dict:
    """List cameras from the connected Hik-Connect account."""
    client = get_hikconnect_client()
    if not client:
        raise HTTPException(
            400,
            "Hik-Connect не подключён. Войдите через админ-панель (email + пароль от приложения).",
        )
    try:
        cameras = await client.list_all_cameras()
        return {
            "cameras": [
                {
                    "device_serial": c.device_serial,
                    "camera_id": c.camera_id,
                    "name": c.name,
                    "channel_no": c.channel_no,
                    "status": "online" if c.signal_status == 1 else "offline",
                }
                for c in cameras
            ],
        }
    except HikConnectError as exc:
        raise HTTPException(400, f"Hik-Connect: {exc.message}")


@router.post("/import")
async def import_hikconnect_camera(
    body: ImportCameraBody,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Import a camera from Hik-Connect cloud into Sentinel."""
    if tenant.tenant_id == "__all__":
        raise HTTPException(400, "Выберите салон (не суперадмин) для импорта камеры")

    client = get_hikconnect_client()
    if not client:
        raise HTTPException(400, "Hik-Connect не подключён")

    stream_url = ""
    try:
        stream = await client.get_live_stream_url(
            serial=body.device_serial,
            channel=body.channel_no,
            quality=body.quality,
        )
        stream_url = stream.url
    except HikConnectError as exc:
        logger.warning("Cloud stream failed: {}, will try RTSP fallback", exc.message)

    if not stream_url:
        logger.info("No cloud stream for {}, using placeholder for RTSP setup", body.device_serial)
        stream_url = f"rtsp://admin@<LOCAL_IP>:554/Streaming/Channels/{body.channel_no}01"

    cam_id = f"hik-{body.device_serial}-ch{body.channel_no}"
    cam_name = body.name or f"Hik {body.device_serial} CH{body.channel_no}"

    config = CameraConfig(
        id=cam_id,
        url=stream_url,
        location_id=body.location_id,
        name=cam_name,
        tenant_id=tenant.tenant_id,
        fps_inference=10 if body.quality == 2 else 5,
    )

    manager = get_manager()
    manager.add_camera(config)

    record = CameraRecord(
        id=cam_id,
        tenant_id=tenant.tenant_id,
        url=stream_url,
        name=cam_name,
        location_id=body.location_id,
        fps_inference=config.fps_inference,
        enabled=True,
        ezviz_serial=body.device_serial,
        ezviz_channel=body.channel_no,
    )
    db.add(record)
    await db.commit()

    logger.info("Imported Hik-Connect camera: {} ({})", cam_id, cam_name)
    return {
        "id": cam_id,
        "name": cam_name,
        "url": stream_url[:60] + "..." if len(stream_url) > 60 else stream_url,
        "location_id": body.location_id,
        "running": True,
        "enabled": True,
    }


@router.post("/refresh/{camera_id}")
async def refresh_hikconnect_stream(
    camera_id: str,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Refresh HLS stream URL for a Hik-Connect camera (tokens expire ~24h)."""
    record = await db.get(CameraRecord, camera_id)
    if not record or not record.ezviz_serial:
        raise HTTPException(404, "Это не Hik-Connect камера")
    if tenant.tenant_id != "__all__" and record.tenant_id != tenant.tenant_id:
        raise HTTPException(403, "Нет доступа")

    client = get_hikconnect_client()
    if not client:
        raise HTTPException(400, "Hik-Connect не подключён")

    try:
        stream = await client.get_live_stream_url(
            serial=record.ezviz_serial,
            channel=record.ezviz_channel or 1,
        )
    except HikConnectError as exc:
        raise HTTPException(400, f"Ошибка обновления: {exc.message}")

    if stream.url:
        record.url = stream.url
        await db.commit()

        manager = get_manager()
        manager.remove_camera(camera_id)
        manager.add_camera(CameraConfig(
            id=camera_id,
            url=stream.url,
            location_id=record.location_id or "default",
            name=record.name or camera_id,
            tenant_id=record.tenant_id,
            fps_inference=record.fps_inference or 10,
        ))

    return {"refreshed": camera_id, "url": (stream.url or record.url)[:60] + "..."}
