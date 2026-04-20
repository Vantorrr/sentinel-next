"""Edge agent configuration from env / .env file."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class EdgeConfig:
    API_URL: str = os.getenv("SENTINEL_API_URL", "http://localhost:8000")
    API_KEY: str = os.getenv("SENTINEL_API_KEY", "")
    AGENT_ID: str = os.getenv("SENTINEL_AGENT_ID", str(uuid.uuid4())[:8])
    AGENT_NAME: str = os.getenv("SENTINEL_AGENT_NAME", "edge-1")

    CAMERAS: str = os.getenv("SENTINEL_CAMERAS", "0")
    FPS_INFERENCE: int = int(os.getenv("SENTINEL_FPS_INFERENCE", "10"))
    YOLO_MODEL: str = os.getenv("SENTINEL_YOLO_MODEL", "yolo11n.pt")
    YOLO_CONFIDENCE: float = float(os.getenv("SENTINEL_YOLO_CONFIDENCE", "0.35"))

    HEARTBEAT_INTERVAL: int = int(os.getenv("SENTINEL_HEARTBEAT_INTERVAL", "30"))
    EVENT_BATCH_SIZE: int = int(os.getenv("SENTINEL_EVENT_BATCH_SIZE", "10"))
    EVENT_FLUSH_INTERVAL: int = int(os.getenv("SENTINEL_EVENT_FLUSH_INTERVAL", "5"))

    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")


cfg = EdgeConfig()
