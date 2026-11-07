"""Classify camera URLs and decide whether this process may open them.

A saved placeholder or a private LAN address is not a successful cloud stream.
Nothing here rewrites a host to a salon address: that address is reachable only
from a process on the same network.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

_USERINFO = re.compile(r"((?:rtsp|rtsps|rtmp|https?|ftp)://)(?:[^/\s@]+)@", re.IGNORECASE)
# Drop the whole query. Ticket names vary (token, t, accessToken, sign, …).
_URL_QUERY = re.compile(
    r"((?:rtsp|rtsps|rtmp|https?|ftp)://[^\s?#]*)\?[^\s#]*",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StreamTarget:
    host_class: str
    scheme: str
    has_credentials: bool
    blocked: bool
    reason: str
    requirement: str


@dataclass(frozen=True)
class HikImportVerdict:
    ok: bool
    code: str
    message: str
    host_class: str
    requirement: str

    def as_detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "host_class": self.host_class,
            "requirement": self.requirement,
        }


@dataclass
class StreamState:
    status: str = "connecting"
    frames_received: int = 0
    last_frame_at: str | None = None
    last_error: str = ""
    host_class: str = ""
    requirement: str = ""
    scheme: str = ""


_PLACEHOLDER_REASON = (
    "В URL шаблон <LOCAL_IP>, без настоящего адреса и без пароля. "
    "Поток не открывается и не подменяется адресом регистратора. "
    "Онлайн ставится только после кадра. Для салона нужен edge в одной сети "
    "с регистратором либо RTSP, до которого с этого сервера есть маршрут."
)
_PASSWORD_REASON = (
    "RTSP Hikvision без пароля устройства не открывается. "
    "Официальный URL содержит логин, пароль и путь /Streaming/Channels/101 или 102."
)
_EMPTY_REASON = "Пустой URL потока. Кадр получить нельзя."
_LAN_IMPORT_REASON = (
    "Облако не вернуло поток, который этот сервер может открыть. "
    "Частный адрес регистратора отсюда недоступен и в URL не подставляется. "
    "Запустите edge на компьютере в сети салона или укажите RTSP с маршрутом "
    "до этого сервера. Логин Hik-Connect сам по себе кадр не даёт."
)


def redact_text(text: str) -> str:
    """Drop userinfo and every query string. Host and path stay."""
    cleaned = _USERINFO.sub(r"\1", text or "")
    return _URL_QUERY.sub(r"\1", cleaned)


def caller_may_see_camera(
    caller_tenant_id: str,
    owner_tenant_id: str | None,
    *,
    is_superadmin: bool,
) -> bool:
    """Superadmin sees any loaded camera. A salon sees only its own owner id."""
    if is_superadmin or caller_tenant_id == "__all__":
        return True
    if not owner_tenant_id:
        return False
    return caller_tenant_id == owner_tenant_id


def hik_upsert_action(existing_owner: str | None, caller_tenant_id: str) -> str:
    """insert, update, or forbidden. Runtime must start only after this write commits."""
    if existing_owner is None:
        return "insert"
    if existing_owner != caller_tenant_id:
        return "forbidden"
    return "update"


def redact_stream_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return "[invalid-url]"
    if not parts.scheme:
        return raw
    host = parts.hostname or ""
    if (not host and ("<" in raw or "local_ip" in raw.lower())) or "local_ip" in host.lower():
        host = "<LOCAL_IP>"
    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _host_class(host: str) -> str:
    import ipaddress

    if not host:
        return "empty"
    if "<" in host or ">" in host or "local_ip" in host.lower():
        return "placeholder"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return "hostname"
    if ip.is_loopback:
        return "loopback"
    if ip.is_link_local:
        return "link_local"
    if ip.is_private:
        return "private"
    if ip.is_unspecified:
        return "unspecified"
    if ip.is_reserved or ip.is_multicast or not ip.is_global:
        return "reserved"
    return "public"


def classify_stream_url(url: str) -> StreamTarget:
    raw = (url or "").strip()
    if not raw:
        return StreamTarget("empty", "", False, True, _EMPTY_REASON, "reachable_stream")
    if raw.lower() == "demo":
        return StreamTarget("demo", "", False, False, "", "")
    if raw.isdigit() or raw.startswith("/dev/video"):
        return StreamTarget("device", "", False, False, "", "")
    lowered = raw.lower()
    if "<" in raw or "local_ip" in lowered:
        return StreamTarget(
            "placeholder", "rtsp", False, True, _PLACEHOLDER_REASON, "edge_same_lan",
        )

    parts = urlsplit(raw)
    scheme = (parts.scheme or "").lower()
    if scheme not in {"rtsp", "rtsps", "rtmp", "http", "https", "file"}:
        if raw.startswith("/"):
            return StreamTarget("file", "", False, False, "", "")
        return StreamTarget(
            "unknown", scheme, False, True, "Неизвестный источник потока.", "reachable_stream",
        )

    if scheme == "file":
        return StreamTarget("file", "file", False, False, "", "")

    host = parts.hostname or ""
    host_class = _host_class(host)
    # Device RTSP uses user:password. Cloud RTMP/RTSP often uses a query ticket
    # on a public host. A query on a private host is not that ticket.
    query_ticket = bool(parts.query) and host_class in {"public", "hostname"}
    has_credentials = bool(parts.password) or query_ticket
    if scheme in {"rtsp", "rtsps", "rtmp"} and not has_credentials:
        return StreamTarget(host_class, scheme, False, True, _PASSWORD_REASON, "rtsp_credentials")
    if host_class in {"private", "loopback", "link_local", "unspecified", "reserved"}:
        return StreamTarget(
            host_class,
            scheme,
            has_credentials,
            False,
            "Адрес в сети, недоступной с другого хоста без маршрута.",
            "same_lan",
        )
    return StreamTarget(host_class, scheme, has_credentials, False, "", "")


def assess_hik_stream(url: str, protocol: str = "") -> HikImportVerdict:
    """Cloud import may store only a URL this server can open. LAN is not implied."""
    if (protocol or "") == "rtsp-lan":
        return HikImportVerdict(
            False, "lan_unroutable", _LAN_IMPORT_REASON, "private", "edge_same_lan",
        )
    target = classify_stream_url(url)
    if target.host_class == "placeholder":
        return HikImportVerdict(
            False, "legacy_placeholder", target.reason, target.host_class, target.requirement,
        )
    if target.host_class in {"private", "loopback", "link_local", "unspecified", "reserved"}:
        return HikImportVerdict(
            False, "lan_unroutable", _LAN_IMPORT_REASON, target.host_class, "edge_same_lan",
        )
    if target.blocked or not url.strip():
        code = (
            "rtsp_credentials_required"
            if target.requirement == "rtsp_credentials"
            else "cloud_stream_unavailable"
        )
        return HikImportVerdict(
            False,
            code,
            target.reason or _LAN_IMPORT_REASON,
            target.host_class,
            target.requirement or "edge_same_lan",
        )
    usable_scheme = target.scheme in {"http", "https", "rtsp", "rtsps", "rtmp"}
    usable_host = target.host_class in {"public", "hostname"}
    if usable_scheme and usable_host:
        return HikImportVerdict(True, "ok", "", target.host_class, "")
    return HikImportVerdict(
        False, "cloud_stream_unavailable", _LAN_IMPORT_REASON, target.host_class, "edge_same_lan",
    )


def diagnostic_message(url: str, *, status: str, frames_received: int, last_error: str) -> str:
    target = classify_stream_url(url)
    if target.host_class == "placeholder":
        return _PLACEHOLDER_REASON + " Запись в базе не переписывается."
    if frames_received > 0 and status in {"online", "demo"}:
        return "Кадр получен. Это единственный признак, что поток живой."
    if target.requirement == "same_lan" and status != "online":
        return (
            "Адрес в частной сети. Кадр будет только если этот процесс в той же сети, "
            "что регистратор. Иначе нужен edge на месте. Онлайн без кадра не ставится."
        )
    if status == "connecting":
        return "Поток запускается. Онлайн появится после первого кадра."
    if last_error:
        return redact_text(last_error)
    if target.blocked:
        return target.reason
    return "Кадра нет."
