"""
Hik-Connect cloud integration.

Uses the same login flow as the official Hik-Connect iPhone/Android app.
Just email + password — no developer accounts, no port forwarding.

Based on reverse-engineered API from github.com/tomasbedrich/hikconnect.

Flow:
  1. Login with email + MD5(password) → session JWT
  2. Handle region redirect (code 1100) — Russian accounts → api.hik-connectru.com
  3. List devices → list cameras per device
  4. Get HLS live stream URL for cloud viewing
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


@dataclass
class HikCamera:
    camera_id: str
    name: str
    device_serial: str
    channel_no: int
    signal_status: int  # 1=online 0=offline
    is_shown: int


@dataclass
class HikStream:
    serial: str
    url: str
    expire_time: int


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
            timeout=15.0,
            headers={
                "clientType": "55",
                "lang": "en-US",
                "featureCode": FEATURE_CODE,
            },
        )

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

    # ── Device / Camera listing ────────────────────────────────────────────

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

            for device in data.get("deviceInfos", []):
                serial = device.get("deviceSerial", "")
                if not serial:
                    continue

                locks: dict[int, int] = {}
                try:
                    lock_json = json.loads(
                        data.get("statusInfos", {})
                        .get(serial, {})
                        .get("optionals", {})
                        .get("lockNum", "{}")
                    )
                    locks = {int(k): v for k, v in lock_json.items()}
                except (json.JSONDecodeError, KeyError, ValueError):
                    pass

                devices.append(HikDevice(
                    serial=serial,
                    name=device.get("name", serial),
                    device_type=device.get("deviceType", ""),
                    version=device.get("version", ""),
                    locks=locks,
                ))

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
            cameras.append(HikCamera(
                camera_id=cam.get("cameraId", ""),
                name=cam.get("cameraName", ""),
                device_serial=device_serial,
                channel_no=cam.get("channelNo", 1),
                signal_status=cam.get("deviceChannelInfo", {}).get("signalStatus", 0),
                is_shown=cam.get("isShow", 0),
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

    async def get_live_stream_url(
        self,
        serial: str,
        channel: int = 1,
        quality: int = 2,  # 1=HD 2=SD
    ) -> HikStream:
        """Get HLS live stream URL from the cloud. Works anywhere, no port forwarding."""
        await self._ensure_session()
        resp = await self._http.post(
            f"{self._base_url}/v3/streaming/previewParam",
            data={
                "deviceSerial": serial,
                "channelNo": channel,
                "streamType": quality,
                "protocol": 2,  # HLS
                "quality": quality,
            },
        )
        data = resp.json()

        stream_url = data.get("url", "") or data.get("data", {}).get("url", "")
        expire_time = data.get("data", {}).get("expireTime", 0)

        return HikStream(serial=serial, url=stream_url, expire_time=expire_time)

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
