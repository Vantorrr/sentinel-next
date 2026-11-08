"""Bounded at-least-once queue. A crash after HTTP 200 can resend once.

This is not exactly-once. Oldest events are dropped when the cap is hit,
and that count is kept. The file is replaced atomically.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


class DurableQueue:
    def __init__(self, path: Path, maxlen: int = 1000) -> None:
        self.path = path
        self.maxlen = maxlen
        self.events: list[dict[str, Any]] = []
        self.dropped = 0
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            events = data.get("events")
            if not isinstance(events, list):
                raise ValueError("events")
            self.events = [item for item in events if isinstance(item, dict)]
            self.dropped = int(data.get("dropped") or 0)
        except (OSError, ValueError, json.JSONDecodeError):
            corrupt = self.path.with_suffix(".corrupt.json")
            os.replace(self.path, corrupt)
            self.events = []

    def push(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        overflow = len(self.events) - self.maxlen
        if overflow > 0:
            del self.events[:overflow]
            self.dropped += overflow
        self.save()

    def ack(self, count: int) -> None:
        if count <= 0:
            return
        del self.events[:count]
        self.save()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"v": 1, "dropped": self.dropped, "events": self.events},
            ensure_ascii=False,
        )
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, self.path)
