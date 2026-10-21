"""Central configuration via pydantic-settings — all values overridable via env."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _auto_device() -> str:
    """Detect best available inference device: cuda > cpu. MPS removed for Railway/Linux compat."""
    try:
        import torch  # type: ignore[import-untyped]
        if torch.cuda.is_available():
            return "cuda"
    except ImportError:
        pass
    return "cpu"


# Resolve from package location so keys work whether cwd is repo root or backend/
_REPO_ROOT = Path(__file__).resolve().parents[3]  # …/sentinel-next
_ENV_CANDIDATES = (
    _REPO_ROOT / ".env",
    Path(".env"),
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=tuple(str(p) for p in _ENV_CANDIDATES if p.exists()) or (".env",),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "Sentinel-Next"
    APP_VERSION: str = "2026.1.0"
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    SECRET_KEY: str = Field(default="change-me-in-production-32chars+", description="JWT signing secret")
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3001", "http://localhost"]

    # ── Server ────────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    WORKERS: int = 1

    # ── PostgreSQL ────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"  # on Railway set via Redis plugin reference

    # ── Qdrant ────────────────────────────────────────────────────────────────
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION_FACES: str = "sentinel_faces"
    QDRANT_VECTOR_SIZE: int = 512

    # ── AI Models ────────────────────────────────────────────────────────────
    YOLO_MODEL: str = "yolo11n.pt"
    YOLO_CONFIDENCE: float = 0.45
    YOLO_IOU: float = 0.45
    YOLO_DEVICE: str = ""           # "" = auto-detect at runtime (cuda → cpu)
    FACE_REID_MODEL: str = "buffalo_s"
    FACE_SIMILARITY_THRESHOLD: float = 0.45
    EMOTION_ENABLED: bool = False   # disable by default — expensive

    # ── LLM ──────────────────────────────────────────────────────────────────
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    LLM_PROVIDER: Literal["anthropic", "openai"] = "anthropic"
    LLM_MODEL: str = "claude-3-5-sonnet-20241022"
    LLM_SUMMARIZE_EVERY_SECONDS: int = 30

    # ── Pipeline ─────────────────────────────────────────────────────────────
    FRAME_BUFFER_SIZE: int = 4
    MAX_CAMERAS: int = 128
    INFERENCE_FPS_TARGET: int = 10
    TRACK_MAX_AGE: int = 30
    CAMERA_RECONNECT_BASE_DELAY: float = 3.0   # seconds
    CAMERA_RECONNECT_MAX_DELAY: float = 60.0   # cap exponential backoff

    # ── Demo mode ─────────────────────────────────────────────────────────────
    DEMO_MODE: bool = False   # if True, inject synthetic events for UI testing

    # ── Storage ──────────────────────────────────────────────────────────────
    SNAPSHOTS_DIR: Path = Path("data/snapshots")
    MODELS_DIR: Path = Path("data/models")

    # ── Hik-Connect / EZVIZ ───────────────────────────────────────────────
    HIKCONNECT_EMAIL: str = ""
    HIKCONNECT_PASSWORD: str = ""
    HIKCONNECT_REGION: str = "ru"  # ru, eu, us, cn, sg, in

    # ── Telegram ───────────────────────────────────────────────────────────
    TELEGRAM_BOT_TOKEN: str = ""

    # ── Sentry ───────────────────────────────────────────────────────────────
    SENTRY_DSN: str = ""

    @field_validator("SNAPSHOTS_DIR", "MODELS_DIR", mode="before")
    @classmethod
    def _make_path(cls, v: str | Path) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        from sentinel.db.url import normalize_database_url

        if isinstance(v, str) and v.strip():
            return normalize_database_url(v.strip())
        return v

    @model_validator(mode="before")
    @classmethod
    def _redis_from_railway(cls, data: object) -> object:
        # Railway Redis plugin may expose REDIS_PRIVATE_URL / REDIS_URL
        if isinstance(data, dict):
            if not data.get("REDIS_URL"):
                alt = data.get("REDIS_PRIVATE_URL") or __import__("os").environ.get("REDIS_PRIVATE_URL")
                if alt:
                    data["REDIS_URL"] = alt
        elif not __import__("os").environ.get("REDIS_URL"):
            alt = __import__("os").environ.get("REDIS_PRIVATE_URL")
            if alt:
                # pydantic v2 before-validator on model may get mapping; env is read automatically
                pass
        return data

    @model_validator(mode="after")
    def _resolve_device(self) -> "Settings":
        if not self.YOLO_DEVICE:
            self.YOLO_DEVICE = _auto_device()
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
