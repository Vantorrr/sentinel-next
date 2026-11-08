"""Runtime health. A decoded frame is not the same thing as an opened socket."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class CameraHealth:
    camera_id: str
    label: str
    opened: bool = False
    frames: int = 0
    last_open_wall: float | None = None
    last_frame_wall: float | None = None
    last_error: str = ""

    def snapshot(self, now: float) -> dict[str, Any]:
        age = None if self.last_frame_wall is None else round(now - self.last_frame_wall, 3)
        return {
            "camera_id": self.camera_id,
            "label": self.label,
            "opened": self.opened,
            "frames": self.frames,
            "has_decoded_frame": self.frames > 0,
            "last_frame_age_s": age,
            "last_error": self.last_error,
        }


@dataclass
class RuntimeHealth:
    cameras: dict[str, CameraHealth] = field(default_factory=dict)
    last_event_ack_wall: float | None = None
    last_heartbeat_ack_wall: float | None = None
    last_event_status: int | None = None
    last_heartbeat_status: int | None = None
    queue_depth: int = 0
    dropped_oldest: int = 0
    fps: float = 0.0
    state: str = "starting"

    def snapshot(self) -> dict[str, Any]:
        now = time.time()
        return {
            "state": self.state,
            "fps": round(self.fps, 2),
            "queue_depth": self.queue_depth,
            "dropped_oldest": self.dropped_oldest,
            "last_event_ack_age_s": _age(self.last_event_ack_wall, now),
            "last_heartbeat_ack_age_s": _age(self.last_heartbeat_ack_wall, now),
            "last_event_status": self.last_event_status,
            "last_heartbeat_status": self.last_heartbeat_status,
            "cameras": [cam.snapshot(now) for cam in self.cameras.values()],
            "delivery": "at-least-once",
        }


def _age(stamp: float | None, now: float) -> float | None:
    if stamp is None:
        return None
    return round(now - stamp, 3)


def format_foreground_line(snapshot: dict[str, Any]) -> str:
    """Operator line. Decoded frames and HTTP status only; opened is omitted."""
    parts = [
        f"state={snapshot.get('state')}",
        f"event_http={snapshot.get('last_event_status')}",
        f"heartbeat_http={snapshot.get('last_heartbeat_status')}",
    ]
    for cam in snapshot.get("cameras") or []:
        parts.append(
            "camera={id} decoded_frames={frames} last_frame_age_s={age} has_decoded_frame={flag}".format(
                id=cam.get("camera_id"),
                frames=cam.get("frames"),
                age=cam.get("last_frame_age_s"),
                flag=cam.get("has_decoded_frame"),
            )
        )
    return " ".join(parts)


def write_status(path: Path, health: RuntimeHealth) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(health.snapshot(), ensure_ascii=False, indent=2)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, path)
