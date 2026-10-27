"""
Hik-Connect cloud integration.

Uses the same login flow as the official Hik-Connect iPhone/Android app.
Just email + password — no developer accounts, no port forwarding.

Based on reverse-engineered API from github.com/tomasbedrich/hikconnect.

Flow:
  1. Login with email + MD5(password) → session JWT
  2. Handle region redirect (code 1100) — Russian accounts → api.hik-connectru.com
  3. List devices → list cameras per device
  4. Get live stream URL (HLS/RTMP/FLV/EZOPEN) + device LAN IP fallback
  5. Auto-refresh session (JWT valid ~30 min, refreshable)
"""

from __future__ import annotations

import datetime
import hashlib
import json
from base64 import urlsafe_b64decode
from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

HIKCONNECT_API_HOSTS: dict[str, str] = {
    "default": "api.hik-connect.com",
    "eu": "api.hik-connect.com",
    "us": "api.hik-connect.com",
    "cn": "api.hik-connect.com",
    "ru": "api.hik-connectru.com",
    "sg": "api.hik-connect.com",
    "in": "api.hik-connect.com",
}

FEATURE_CODE = "deadbeef"


@dataclass
class HikDevice:
    serial: str
    name: str
    device_type: str
    version: str
    locks: dict[int, int] = field(default_factory=dict)
    local_ip: str = ""
    wan_ip: str = ""
    offline: bool = False


@dataclass
class HikCamera:
    camera_id: str
    name: str
    device_serial: str
    channel_no: int
    signal_status: int  # 1=online 0=offline
    is_shown: int
    is_encrypt: int = 0
    vtm_domain: str = ""
    vtm_external_ip: str = ""
    vtm_port: int = 0


@dataclass
class HikStream:
    serial: str
    url: str
    expire_time: int
    protocol: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class HikConnectClient:
    """Async client for the Hik-Connect consumer API (mirrors the official app)."""

    def __init__(self, email: str, password: str, region: str = "ru") -> None:
        self._email = email
        self._password_hash = hashlib.md5(password.encode("utf-8")).hexdigest()
        api_host = HIKCONNECT_API_HOSTS.get(region, HIKCONNECT_API_HOSTS["default"])
        self._base_url = f"https://{api_host}"
        self._session_id: str = ""
        self._refresh_session_id: str = ""
        self._login_valid_until: datetime.datetime | None = None
        self._http = httpx.AsyncClient(
            timeout=20.0,
            headers={
                "clientType": "55",
                "lang": "en-US",
                "featureCode": FEATURE_CODE,
            },
        )
        self._device_cache: dict[str, HikDevice] = {}

    async def close(self) -> None:
        await self._http.aclose()

    # ── Auth ──────────────────────────────────────────────────────────────────

    async def login(self) -> None:
        """Login with email + password (same as Hik-Connect app)."""
        resp = await self._http.post(
            f"{self._base_url}/v3/users/login/v2",
            data={
                "account": self._email,
                "password": self._password_hash,
            },
        )
        data = resp.json()
        code = data.get("meta", {}).get("code", 0)

        if code == 1100:
            new_domain = data.get("loginArea", {}).get("apiDomain", "")
            if new_domain:
                logger.info("Hik-Connect: region redirect → {}", new_domain)
                self._base_url = f"https://{new_domain}"
                return await self.login()
            raise HikConnectError("1100", "Region redirect without domain")

        if code in (1013, 1014, 1226):
            raise HikConnectError(
                str(code), "Неверный email или пароль"
            )

        if code == 1015:
            raise HikConnectError(
                "1015",
                "Аккаунт временно заблокирован (слишком много попыток). Подождите 15-30 минут.",
            )

        if code != 200:
            msg = data.get("meta", {}).get("message", "Login failed")
            raise HikConnectError(str(code), msg)

        session = data.get("loginSession", {})
        sid = session.get("sessionId", "")
        rf_sid = session.get("rfSessionId", "")
        if not sid:
            raise HikConnectError("0", "No sessionId in response")

        self._apply_session(sid, rf_sid)

        area_domain = data.get("loginArea", {}).get("apiDomain", "")
        if area_domain:
            self._base_url = f"https://{area_domain}"

        logger.info("Hik-Connect: logged in as {}", self._email)

    async def refresh_login(self) -> None:
        """Refresh session using rfSessionId (JWT valid ~30 min)."""
        if not self._refresh_session_id:
            return await self.login()

        old_sid = self._http.headers.get("sessionId")
        if "sessionId" in self._http.headers:
            del self._http.headers["sessionId"]

        try:
            resp = await self._http.put(
                f"{self._base_url}/v3/apigateway/login",
                data={
                    "refreshSessionId": self._refresh_session_id,
                    "featureCode": FEATURE_CODE,
                },
            )
            data = resp.json()
            session = data.get("sessionInfo", {})
            sid = session.get("sessionId", "")
            rf_sid = session.get("refreshSessionId", "")
            if sid:
                self._apply_session(sid, rf_sid)
                logger.info("Hik-Connect: session refreshed")
            else:
                await self.login()
        except Exception:
            if old_sid:
                self._http.headers["sessionId"] = old_sid
            await self.login()

    def _apply_session(self, session_id: str, refresh_session_id: str) -> None:
        self._session_id = session_id
        self._refresh_session_id = refresh_session_id
        self._http.headers["sessionId"] = session_id
        self._login_valid_until = self._decode_jwt_expiration(session_id)
        logger.debug(
            "Session valid until {}", self._login_valid_until
        )

    def is_refresh_needed(self) -> bool:
        if not self._login_valid_until:
            return True
        return (self._login_valid_until - datetime.datetime.now()) < datetime.timedelta(
            hours=1
        )

    async def _ensure_session(self) -> None:
        if not self._session_id:
            await self.login()
        elif self.is_refresh_needed():
            await self.refresh_login()

    async def _api_get(self, path: str) -> dict[str, Any]:
        await self._ensure_session()
        resp = await self._http.get(f"{self._base_url}{path}")
        data = resp.json()
        if data.get("meta", {}).get("code") == 401:
            await self.login()
            resp = await self._http.get(f"{self._base_url}{path}")
            data = resp.json()
        return data

    async def _api_post_form(self, path: str, form: dict[str, Any]) -> dict[str, Any]:
        await self._ensure_session()
        resp = await self._http.post(f"{self._base_url}{path}", data=form)
        data = resp.json()
        if data.get("meta", {}).get("code") == 401:
            await self.login()
            resp = await self._http.post(f"{self._base_url}{path}", data=form)
            data = resp.json()
        return data

    # ── Device / Camera listing ────────────────────────────────────────────

    @staticmethod
    def _extract_ips(status: dict[str, Any]) -> tuple[str, str]:
        """Pull LAN / WAN IP from CONNECTION / STATUS blobs."""
        local_ip = ""
        wan_ip = ""
        optionals = status.get("optionals") or {}
        candidates = [status, optionals]
        conn = optionals.get("connection") or optionals.get("CONNECTION") or status.get("connection")
        if isinstance(conn, str):
            try:
                conn = json.loads(conn)
            except json.JSONDecodeError:
                conn = {}
        if isinstance(conn, dict):
            candidates.append(conn)

        for blob in candidates:
            if not isinstance(blob, dict):
                continue
            for key in ("localIp", "localIP", "ip", "netIp", "local_ip"):
                val = blob.get(key) or ""
                if isinstance(val, str) and val and not val.startswith("0."):
                    local_ip = local_ip or val
            for key in ("wanIp", "wanIP", "externalIp", "netIp", "wan_ip"):
                val = blob.get(key) or ""
                if isinstance(val, str) and val and not val.startswith("0."):
                    wan_ip = wan_ip or val
        return local_ip, wan_ip

    async def get_devices(self) -> list[HikDevice]:
        """List all devices (DVRs/NVRs) from the account."""
        devices: list[HikDevice] = []
        limit, offset, has_next = 50, 0, True

        while has_next:
            data = await self._api_get(
                f"/v3/userdevices/v1/devices/pagelist"
                f"?groupId=-1&limit={limit}&offset={offset}"
                f"&filter=TIME_PLAN,CONNECTION,SWITCH,STATUS,STATUS_EXT,WIFI,NODISTURB,P2P,KMS,HIDDNS"
            )

            status_infos = data.get("statusInfos") or {}

            for device in data.get("deviceInfos", []):
                serial = device.get("deviceSerial", "")
                if not serial:
                    continue

                locks: dict[int, int] = {}
                status = status_infos.get(serial) or {}
                try:
                    lock_json = json.loads(
                        status.get("optionals", {}).get("lockNum", "{}")
                    )
                    locks = {int(k): v for k, v in lock_json.items()}
                except (json.JSONDecodeError, KeyError, ValueError, TypeError):
                    pass

                local_ip, wan_ip = self._extract_ips(status if isinstance(status, dict) else {})
                offline = bool(status.get("offline") if isinstance(status, dict) else False)

                hik_dev = HikDevice(
                    serial=serial,
                    name=device.get("name", serial),
                    device_type=device.get("deviceType", ""),
                    version=device.get("version", ""),
                    locks=locks,
                    local_ip=local_ip,
                    wan_ip=wan_ip,
                    offline=offline,
                )
                devices.append(hik_dev)
                self._device_cache[serial] = hik_dev

            offset += limit
            has_next = data.get("page", {}).get("hasNext", False)

        logger.info("Hik-Connect: found {} devices", len(devices))
        return devices

    async def get_cameras(self, device_serial: str) -> list[HikCamera]:
        """List cameras connected to a specific device/DVR/NVR."""
        data = await self._api_get(
            f"/v3/userdevices/v1/cameras/info?deviceSerial={device_serial}"
        )

        cameras: list[HikCamera] = []
        for cam in data.get("cameraInfos", []):
            dci = cam.get("deviceChannelInfo") or {}
            vtm = cam.get("vtmInfo") or dci.get("vtmInfo") or {}
            cameras.append(HikCamera(
                camera_id=cam.get("cameraId", ""),
                name=cam.get("cameraName", ""),
                device_serial=device_serial,
                channel_no=cam.get("channelNo", 1),
                signal_status=dci.get("signalStatus", cam.get("status", 0)) or 0,
                is_shown=cam.get("isShow", 0),
                is_encrypt=int(cam.get("isEncrypt") or dci.get("isEncrypt") or 0),
                vtm_domain=str(vtm.get("domain") or ""),
                vtm_external_ip=str(vtm.get("externalIp") or ""),
                vtm_port=int(vtm.get("port") or 0),
            ))

        return cameras

    async def list_all_cameras(self) -> list[HikCamera]:
        """List ALL cameras across all devices in the account."""
        devices = await self.get_devices()
        all_cameras: list[HikCamera] = []
        for dev in devices:
            cams = await self.get_cameras(dev.serial)
            for cam in cams:
                if not cam.name or cam.name.startswith("Camera 01") or cam.name.startswith("camera "):
                    cam.name = f"{dev.name} CH{cam.channel_no}"
            all_cameras.extend(cams)
        logger.info("Hik-Connect: total {} cameras across {} devices", len(all_cameras), len(devices))
        return all_cameras

    # ── Live stream URL ──────────────────────────────────────────────────────

    @staticmethod
    def _pick_url(payload: dict[str, Any]) -> tuple[str, int]:
        """Best-effort URL extraction from varied Hik/EZVIZ response shapes."""
        if not isinstance(payload, dict):
            return "", 0

        direct = payload.get("url") or payload.get("streamUrl") or payload.get("liveAddress") or ""
        if isinstance(direct, str) and direct.startswith(("http://", "https://", "rtsp://", "rtmp://", "ezopen://")):
            expire = payload.get("expireTime") or payload.get("expire") or 0
            try:
                return direct, int(expire) if expire else 0
            except (TypeError, ValueError):
                return direct, 0

        data = payload.get("data")
        if isinstance(data, dict):
            return HikConnectClient._pick_url(data)
        if isinstance(data, list):
            for item in data:
                url, exp = HikConnectClient._pick_url(item if isinstance(item, dict) else {})
                if url:
                    return url, exp

        for key in ("result", "stream", "live", "preview"):
            nested = payload.get(key)
            if isinstance(nested, dict):
                url, exp = HikConnectClient._pick_url(nested)
                if url:
                    return url, exp

        return "", 0

    async def get_live_stream_url(
        self,
        serial: str,
        channel: int = 1,
        quality: int = 2,  # 1=HD 2=SD
    ) -> HikStream:
        """Try cloud stream endpoints (HLS/RTMP/FLV/EZOPEN). Empty url = no cloud preview."""
        await self._ensure_session()
        attempts: list[tuple[str, dict[str, Any]]] = []
        last_raw: dict[str, Any] = {}

        # protocol: 1=EZOPEN 2=HLS 3=RTMP 4=FLV (Hik/EZVIZ conventions vary by endpoint)
        for protocol, label in ((2, "hls"), (4, "flv"), (3, "rtmp"), (1, "ezopen")):
            form = {
                "deviceSerial": serial,
                "channelNo": channel,
                "streamType": quality,
                "protocol": protocol,
                "quality": quality,
            }
            try:
                data = await self._api_post_form("/v3/streaming/previewParam", form)
            except Exception as exc:
                logger.warning("previewParam {} failed: {}", label, exc)
                continue
            last_raw = data
            attempts.append((f"previewParam/{label}", data))
            url, expire = self._pick_url(data)
            meta_code = (data.get("meta") or {}).get("code")
            logger.info(
                "Hik stream previewParam protocol={} meta={} url={}",
                protocol, meta_code, (url[:80] + "...") if url and len(url) > 80 else url,
            )
            if url:
                return HikStream(serial=serial, url=url, expire_time=expire, protocol=label, raw=data)

        # Alternate carrier endpoint (some RU accounts)
        for protocol, label in (("2", "hls"), ("4", "flv"), ("3", "rtmp")):
            path = (
                f"/v1/carrier/wing/endpoint/video/getVideoUrl"
                f"?deviceSerial={serial}&channelNo={channel}"
                f"&protocol={protocol}&quality={quality}&expireTime=86400&type=1"
            )
            try:
                data = await self._api_get(path)
            except Exception as exc:
                logger.warning("getVideoUrl {} failed: {}", label, exc)
                continue
            last_raw = data
            attempts.append((f"getVideoUrl/{label}", data))
            url, expire = self._pick_url(data)
            if url:
                return HikStream(serial=serial, url=url, expire_time=expire, protocol=label, raw=data)

        # Open-live (legacy)
        try:
            data = await self._api_get(
                f"/v3/openlive/get?deviceSerial={serial}&channelNo={channel}&code=&quality={quality}"
            )
            last_raw = data
            attempts.append(("openlive", data))
            url, expire = self._pick_url(data)
            if url:
                return HikStream(serial=serial, url=url, expire_time=expire, protocol="openlive", raw=data)
        except Exception as exc:
            logger.warning("openlive failed: {}", exc)

        # LAN RTSP fallback from device CONNECTION info
        if serial not in self._device_cache:
            await self.get_devices()
        device = self._device_cache.get(serial)
        local_ip = (device.local_ip if device else "") or ""
        if local_ip:
            rtsp = self.build_rtsp_url(local_ip, channel=channel, stream="sub")
            logger.info("Hik stream: no cloud URL for {}, using LAN RTSP {}", serial, local_ip)
            return HikStream(
                serial=serial,
                url=rtsp,
                expire_time=0,
                protocol="rtsp-lan",
                raw={"attempts": attempts, "local_ip": local_ip, "last": last_raw},
            )

        logger.warning(
            "Hik stream: no URL for {} ch{} after {} attempts; last={}",
            serial, channel, len(attempts), json.dumps(last_raw, ensure_ascii=False)[:400],
        )
        return HikStream(
            serial=serial,
            url="",
            expire_time=0,
            protocol="",
            raw={"attempts": attempts, "last": last_raw},
        )

    async def isapi(
        self,
        serial: str,
        api_data: str,
        channel: int = 1,
        api_key: str = "100044",
    ) -> httpx.Response:
        """Proxy an ISAPI request to the device through Hik-Connect cloud."""
        await self._ensure_session()
        return await self._http.post(
            f"{self._base_url}/v3/userdevices/v1/isapi",
            data={
                "apiKey": api_key,
                "channelNo": str(channel),
                "deviceSerial": serial,
                "apiData": api_data,
            },
        )

    async def get_snapshot_jpeg(self, serial: str, channel: int = 1) -> bytes | None:
        """Grab a JPEG via cloud ISAPI proxy (works without HLS subscription)."""
        # NVR IP channels often use StreamingProxy; try both
        paths = [
            f"GET /ISAPI/Streaming/channels/{channel}01/picture",
            f"GET /ISAPI/ContentMgmt/StreamingProxy/channels/{channel * 100 + 1}/picture",
            f"GET /ISAPI/Streaming/channels/{channel}/picture",
        ]
        for path in paths:
            try:
                resp = await self.isapi(serial, path, channel=channel)
            except Exception as exc:
                logger.warning("ISAPI snapshot {} failed: {}", path, exc)
                continue
            ctype = (resp.headers.get("content-type") or "").lower()
            body = resp.content
            if body[:3] == b"\xff\xd8\xff" or "image" in ctype:
                logger.info("Hik snapshot OK via {} ({} bytes)", path, len(body))
                return body
            # Sometimes JSON error wrapper
            try:
                err = resp.json()
                logger.debug("ISAPI snapshot {} → {}", path, err)
            except Exception:
                logger.debug("ISAPI snapshot {} non-jpeg {}B ctype={}", path, len(body), ctype)
        return None

    async def debug_stream(self, serial: str, channel: int = 1) -> dict[str, Any]:
        """Return raw probe results for diagnosing empty cloud URLs."""
        stream = await self.get_live_stream_url(serial, channel)
        cams = await self.get_cameras(serial)
        cam = next((c for c in cams if c.channel_no == channel), cams[0] if cams else None)
        device = self._device_cache.get(serial)
        if not device:
            await self.get_devices()
            device = self._device_cache.get(serial)

        snapshot_ok = False
        snapshot_bytes = 0
        try:
            jpeg = await self.get_snapshot_jpeg(serial, channel)
            if jpeg:
                snapshot_ok = True
                snapshot_bytes = len(jpeg)
        except Exception as exc:
            logger.warning("snapshot probe failed: {}", exc)

        return {
            "base_url": self._base_url,
            "stream_url": stream.url,
            "protocol": stream.protocol,
            "raw": stream.raw,
            "snapshot_ok": snapshot_ok,
            "snapshot_bytes": snapshot_bytes,
            "device": {
                "serial": serial,
                "name": device.name if device else "",
                "local_ip": device.local_ip if device else "",
                "wan_ip": device.wan_ip if device else "",
                "offline": device.offline if device else None,
            },
            "camera": {
                "name": cam.name if cam else "",
                "channel_no": channel,
                "signal_status": cam.signal_status if cam else None,
                "is_encrypt": cam.is_encrypt if cam else None,
                "vtm_domain": cam.vtm_domain if cam else "",
                "vtm_external_ip": cam.vtm_external_ip if cam else "",
                "vtm_port": cam.vtm_port if cam else 0,
            } if cam else None,
        }

    @staticmethod
    def build_rtsp_url(
        local_ip: str,
        rtsp_port: str = "554",
        channel: int = 1,
        stream: str = "sub",
    ) -> str:
        """Build RTSP URL for direct local network access (requires LAN)."""
        ch = f"{channel}02" if stream == "sub" else f"{channel}01"
        return f"rtsp://admin@{local_ip}:{rtsp_port}/Streaming/Channels/{ch}"

    @staticmethod
    def _decode_jwt_expiration(jwt: str) -> datetime.datetime:
        parts = jwt.split(".")
        claims_raw = parts[1]
        missing_padding = len(claims_raw) % 4
        if missing_padding:
            claims_raw += "=" * (4 - missing_padding)
        claims_json_raw = urlsafe_b64decode(claims_raw)
        claims = json.loads(claims_json_raw)
        return datetime.datetime.fromtimestamp(claims["exp"])


class HikConnectError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"Hik-Connect Error [{code}]: {message}")


_client: HikConnectClient | None = None


def get_hikconnect_client() -> HikConnectClient | None:
    return _client


async def init_hikconnect(email: str, password: str, region: str = "ru") -> HikConnectClient:
    global _client
    if _client:
        await _client.close()
    _client = HikConnectClient(email, password, region)
    await _client.login()
    return _client
