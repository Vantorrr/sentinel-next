"""Edge settings from a config file and the process environment.

The file is data only. Shell substitution is rejected by the parser.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from sentinel_edge.envfile import parse_env


@dataclass
class EdgeSettings:
    api_url: str = "http://localhost:8000"
    api_key: str = ""
    agent_id: str = "edge"
    agent_name: str = "edge-1"
    cameras: str = ""
    fps_inference: int = 5
    yolo_model: str = "yolo11n.pt"
    yolo_confidence: float = 0.35
    heartbeat_interval: int = 30
    event_batch_size: int = 10
    event_flush_interval: int = 5
    queue_max: int = 1000
    log_level: str = "INFO"
    data_dir: str = ""

    def camera_list(self) -> list[str]:
        return [part.strip() for part in self.cameras.split(",") if part.strip()]

    def errors(self) -> list[str]:
        problems: list[str] = []
        if not (self.api_url.startswith("http://") or self.api_url.startswith("https://")):
            problems.append("SENTINEL_API_URL must start with http:// or https://")
        if not self.api_key.strip():
            problems.append("SENTINEL_API_KEY is empty")
        if not self.camera_list():
            problems.append("SENTINEL_CAMERAS is empty")
        if self.fps_inference < 1:
            problems.append("SENTINEL_FPS_INFERENCE must be >= 1")
        return problems


def _pick(env: dict[str, str], key: str, default: str) -> str:
    if os.environ.get(key, "").strip():
        return os.environ[key]
    if key in env and env[key].strip():
        return env[key]
    return default


def load_settings(path: Path | None = None) -> EdgeSettings:
    file_values: dict[str, str] = {}
    if path is not None and path.exists():
        file_values = parse_env(path.read_text(encoding="utf-8"))
    fps = _pick(file_values, "SENTINEL_FPS_INFERENCE", "5")
    conf = _pick(file_values, "SENTINEL_YOLO_CONFIDENCE", "0.35")
    return EdgeSettings(
        api_url=_pick(file_values, "SENTINEL_API_URL", "http://localhost:8000").rstrip("/"),
        api_key=_pick(file_values, "SENTINEL_API_KEY", ""),
        agent_id=_pick(file_values, "SENTINEL_AGENT_ID", "edge"),
        agent_name=_pick(file_values, "SENTINEL_AGENT_NAME", "edge-1"),
        cameras=_pick(file_values, "SENTINEL_CAMERAS", ""),
        fps_inference=int(fps),
        yolo_model=_pick(file_values, "SENTINEL_YOLO_MODEL", "yolo11n.pt"),
        yolo_confidence=float(conf),
        heartbeat_interval=int(_pick(file_values, "SENTINEL_HEARTBEAT_INTERVAL", "30")),
        event_batch_size=int(_pick(file_values, "SENTINEL_EVENT_BATCH_SIZE", "10")),
        event_flush_interval=int(_pick(file_values, "SENTINEL_EVENT_FLUSH_INTERVAL", "5")),
        queue_max=int(_pick(file_values, "SENTINEL_QUEUE_MAX", "1000")),
        log_level=_pick(file_values, "LOG_LEVEL", "INFO"),
        data_dir=_pick(file_values, "SENTINEL_DATA_DIR", ""),
    )
