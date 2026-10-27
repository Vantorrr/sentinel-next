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

    return {
        "refreshed": camera_id,
        "url": (stream.url or record.url)[:80] + ("..." if len(stream.url or record.url or "") > 80 else ""),
        "protocol": stream.protocol,
    }


@router.get("/debug-stream/{serial}")
async def debug_hikconnect_stream(
    serial: str,
    channel: int = 1,
    _: TenantContext = Depends(require_superadmin),
) -> dict:
    """Raw Hik stream probe (superadmin) — diagnose empty cloud URLs."""
    client = get_hikconnect_client()
    if not client:
        raise HTTPException(400, "Hik-Connect не подключён")
    try:
        return await client.debug_stream(serial, channel)
    except HikConnectError as exc:
        raise HTTPException(400, f"Hik-Connect: {exc.message}")
    except Exception as exc:
        logger.error("Hik debug-stream error: {}", exc)
        raise HTTPException(500, "Ошибка диагностики потока")


@router.get("/dump-status/{serial}")
async def dump_device_status(
    serial: str,
    _: TenantContext = Depends(require_superadmin),
) -> dict:
    """Raw device statusInfos + ISAPI probe (superadmin)."""
    client = get_hikconnect_client()
    if not client:
        raise HTTPException(400, "Hik-Connect не подключён")
    devices = await client.get_devices()
    # re-fetch raw pagelist page containing serial
    data = await client._api_get(
        "/v3/userdevices/v1/devices/pagelist?groupId=-1&limit=50&offset=0"
        "&filter=TIME_PLAN,CONNECTION,SWITCH,STATUS,STATUS_EXT,WIFI,NODISTURB,P2P,KMS,HIDDNS"
    )
    status = (data.get("statusInfos") or {}).get(serial)
    info = next((d for d in (data.get("deviceInfos") or []) if d.get("deviceSerial") == serial), None)
    isapi_tries = {}
    for path in [
        "GET /ISAPI/System/deviceInfo",
        "GET /ISAPI/System/Network/interfaces",
        "GET /ISAPI/Streaming/channels/102/picture",
        "GET /ISAPI/ContentMgmt/StreamingProxy/channels/101/picture",
    ]:
        try:
            resp = await client.isapi(serial, path, channel=1)
            ctype = resp.headers.get("content-type", "")
            body = resp.content
            preview = body[:200]
            try:
                preview_s = body.decode("utf-8", errors="replace")[:500]
            except Exception:
                preview_s = str(preview)
            isapi_tries[path] = {
                "status_code": resp.status_code,
                "content_type": ctype,
                "bytes": len(body),
                "preview": preview_s,
                "jpeg": body[:3] == b"\xff\xd8\xff",
            }
        except Exception as exc:
            isapi_tries[path] = {"error": str(exc)}
    return {
        "deviceInfo": info,
        "statusInfo": status,
        "parsed": next(({"name": d.name, "local_ip": d.local_ip, "wan_ip": d.wan_ip} for d in devices if d.serial == serial), None),
        "isapi": isapi_tries,
    }



@router.get("/probe-capture/{serial}")
async def probe_capture(
    serial: str,
    channel: int = 1,
    _: TenantContext = Depends(require_superadmin),
) -> dict:
    """Try alternate cloud capture/stream endpoints (superadmin)."""
    client = get_hikconnect_client()
    if not client:
        raise HTTPException(400, "Hik-Connect не подключён")
    await client._ensure_session()
    results = []
    paths = [
        ("GET", f"/v3/devices/{serial}/{channel}/capture?channelNo={channel}"),
        ("GET", f"/v3/userdevices/v1/cameras/capture?deviceSerial={serial}&channelNo={channel}"),
        ("POST", "/v3/devices/capture/image", {"deviceSerial": serial, "channelNo": channel}),
        ("GET", f"/v3/alarms/image?deviceSerial={serial}&channelNo={channel}"),
        ("POST", "/v3/streaming/device/token", {"deviceSerial": serial, "channelNo": channel}),
        ("POST", "/v3/vtm/token", {"deviceSerial": serial, "channelNo": channel}),
        ("GET", f"/v3/devices/{serial}/status"),
        ("POST", "/v3/open/live/address/get", {"deviceSerial": serial, "channelNo": channel, "protocol": 2, "quality": 2}),
        ("POST", "/api/lapp/v2/live/address/get", {"deviceSerial": serial, "channelNo": channel, "protocol": 2}),
    ]
    for method, path, *rest in [(p[0], p[1], p[2] if len(p)>2 else None) for p in [
        ("GET", f"/v3/devices/{serial}/{channel}/capture?channelNo={channel}"),
        ("GET", f"/v3/userdevices/v1/cameras/capture?deviceSerial={serial}&channelNo={channel}"),
        ("POST", "/v3/devices/capture/image"),
        ("POST", "/v3/streaming/device/token"),
        ("POST", "/v3/vtm/token"),
        ("POST", "/v3/open/live/address/get"),
    ]]:
        form = None
        if method == "POST":
            if "capture/image" in path:
                form = {"deviceSerial": serial, "channelNo": channel}
            elif "token" in path:
                form = {"deviceSerial": serial, "channelNo": channel}
            elif "live/address" in path:
                form = {"deviceSerial": serial, "channelNo": channel, "protocol": 2, "quality": 2, "type": 1}
        try:
            if method == "GET":
                data = await client._api_get(path)
            else:
                data = await client._api_post_form(path, form or {})
            results.append({"method": method, "path": path, "data": data})
        except Exception as exc:
            results.append({"method": method, "path": path, "error": str(exc)})
    # Also try EZVIZ RU hosts with same sessionId
    ez_hosts = [
        "https://apiirus.ezvizru.com",
        "https://api.ezvizru.com",
        "https://open.ezvizru.com",
    ]
    for host in ez_hosts:
        for path in [
            f"/v3/userdevices/v1/cameras/capture?deviceSerial={serial}&channelNo={channel}",
            "/v3/streaming/previewParam",
        ]:
            try:
                if path.endswith("previewParam"):
                    resp = await client._http.post(
                        f"{host}{path}",
                        data={
                            "deviceSerial": serial,
                            "channelNo": channel,
                            "streamType": 2,
                            "protocol": 2,
                            "quality": 2,
                        },
                    )
                else:
                    resp = await client._http.get(f"{host}{path}")
                try:
                    payload = resp.json()
                except Exception:
                    payload = {"text": resp.text[:300]}
                results.append({"host": host, "path": path, "status": resp.status_code, "data": payload})
            except Exception as exc:
                results.append({"host": host, "path": path, "error": str(exc)})
    return {"serial": serial, "channel": channel, "results": results}
