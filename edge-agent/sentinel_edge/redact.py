"""Redact secrets from logs and diagnostic exports. Never store frames."""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

_USERINFO = re.compile(
    r"((?:rtsp|rtsps|rtmp|https?|ftp)://)(?:[^/\s@]+)@",
    re.IGNORECASE,
)
_QUERY = re.compile(
    r"((?:rtsp|rtsps|rtmp|https?|ftp)://[^\s?#]*)\?[^\s#]*",
    re.IGNORECASE,
)
_ASSIGN = re.compile(
    r"((?:SENTINEL_API_KEY|API_KEY|PASSWORD|PWD)\s*[=:]\s*)(\S+)",
    re.IGNORECASE,
)


def redact_text(text: str) -> str:
    cleaned = _USERINFO.sub(r"\1", text or "")
    cleaned = _QUERY.sub(r"\1", cleaned)
    return _ASSIGN.sub(r"\1***", cleaned)


def camera_label(url: str) -> str:
    """Host and path only. Userinfo and query are dropped."""
    raw = (url or "").strip()
    if not raw:
        return ""
    parts = urlsplit(raw)
    if not parts.scheme:
        return "[local]"
    host = parts.hostname or ""
    netloc = host
    if parts.port:
        netloc = f"{host}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
