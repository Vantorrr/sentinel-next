"""
Loguru-based logging for Sentinel-Next.

Provides colour-coded, structured terminal output that shows:
  - Camera status changes (green / red)
  - Face identifications (cyan with name)
  - LLM summaries (magenta)
  - Security alerts (red bold)
  - Pipeline FPS metrics (dim)

Import and call setup_logging() once at startup.
"""

from __future__ import annotations

import logging
import sys

from loguru import logger

# Silence noisy third-party loggers
_SUPPRESS = [
    "uvicorn.access",
    "uvicorn.error",
    "httpx",
    "httpcore",
    "multipart",
    "PIL",
    "asyncio",
]


class _InterceptHandler(logging.Handler):
    """Route stdlib logging → loguru."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = str(record.levelno)

        frame, depth = sys._getframe(6), 6
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back  # type: ignore[assignment]
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


_FORMAT = (
    "<green>{time:HH:mm:ss}</green> "
    "<level>{level: <8}</level> "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> "
    "— <level>{message}</level>"
)

_SENTINEL_COLORS = {
    "CAMERA_ONLINE": "green",
    "CAMERA_OFFLINE": "red",
    "FACE_ID": "cyan",
    "VIP": "yellow",
    "ALERT": "red bold",
    "LLM": "magenta",
    "FPS": "dim",
}


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.add(
        sys.stderr,
        format=_FORMAT,
        level=level,
        colorize=True,
        enqueue=True,           # thread-safe async logging
        backtrace=True,
        diagnose=False,         # don't leak secrets in tracebacks
    )

    # File sink — keeps last 7 days
    logger.add(
        "logs/sentinel_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention="7 days",
        compression="gz",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{line} | {message}",
        enqueue=True,
    )

    # Intercept stdlib
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in _SUPPRESS:
        logging.getLogger(name).setLevel(logging.WARNING)

    logger.info("🛡  Sentinel logging active — level={}", level)


def log_camera_event(event: str, camera_id: str, **kwargs: object) -> None:
    color = _SENTINEL_COLORS.get(event, "white")
    msg = f"[<{color}>CAM</{color}>] {camera_id} — {event}"
    for k, v in kwargs.items():
        msg += f" | {k}={v}"
    logger.opt(colors=True).info(msg)


def log_face_id(name: str, category: str, similarity: float, camera_id: str) -> None:
    cat_color = {
        "vip": "yellow",
        "staff": "cyan",
        "regular": "white",
        "new": "green",
    }.get(category, "white")

    logger.opt(colors=True).info(
        "👤 [<cyan>FACE</cyan>] <bold>{}</bold> (<{}>{}</{}>) sim={:.2f} cam={}",
        name, cat_color, category.upper(), cat_color, similarity, camera_id,
    )


def log_alert(description: str, camera_id: str) -> None:
    logger.opt(colors=True).warning(
        "🚨 [<red><bold>ALERT</bold></red>] {} — cam={}",
        description, camera_id,
    )


def log_llm_summary(narrative: str, occupancy: int, mood: str) -> None:
    mood_color = {"позитивное": "green", "нейтральное": "blue", "напряжённое": "red"}.get(mood, "white")
    logger.opt(colors=True).info(
        "🧠 [<magenta>LLM</magenta>] occupancy={} mood=<{}>{}​</{}> | {}",
        occupancy, mood_color, mood, mood_color, narrative[:120],
    )
