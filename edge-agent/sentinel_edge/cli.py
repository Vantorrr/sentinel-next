"""Sentinel Edge Agent CLI — run with: sentinel-edge start"""

from __future__ import annotations

import asyncio
import signal
import sys

import typer
from loguru import logger

from sentinel_edge.config import cfg

app = typer.Typer(name="sentinel-edge", help="Sentinel-Next Edge Agent")


async def _run_agent() -> None:
    from sentinel_edge.camera import CameraStream
    from sentinel_edge.detector import LocalDetector
    from sentinel_edge.sender import EventSender

    logger.remove()
    logger.add(sys.stderr, level=cfg.LOG_LEVEL, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level:^7}</level> | {message}")

    logger.info("Sentinel Edge Agent v0.1.0")
    logger.info("API: {}", cfg.API_URL)
    logger.info("Agent: {} ({})", cfg.AGENT_NAME, cfg.AGENT_ID)

    if not cfg.API_KEY:
        logger.error("SENTINEL_API_KEY not set! Cannot authenticate.")
        return

    detector = LocalDetector()
    detector.load()

    sender = EventSender()
    await sender.start()

    camera_sources = [s.strip() for s in cfg.CAMERAS.split(",") if s.strip()]
    logger.info("Cameras: {}", camera_sources)

    stop_event = asyncio.Event()

    def handle_signal() -> None:
        logger.info("Shutting down...")
        stop_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    async def process_camera(source: str, idx: int) -> None:
        cam_id = f"edge-{cfg.AGENT_ID}-cam-{idx}"
        stream = CameraStream(source, camera_id=cam_id)

        try:
            async for frame in stream.frames():
                if stop_event.is_set():
                    break
                events = detector.process_frame(frame, cam_id)
                for ev in events:
                    sender.push(ev)
        finally:
            stream.release()

    tasks = [
        asyncio.create_task(process_camera(src, i))
        for i, src in enumerate(camera_sources)
    ]

    await stop_event.wait()

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await sender.stop()
    logger.info("Agent stopped.")


@app.command()
def start() -> None:
    """Start the edge agent and begin processing cameras."""
    asyncio.run(_run_agent())


@app.command()
def check() -> None:
    """Verify connection to central API."""
    import httpx

    logger.remove()
    logger.add(sys.stderr, level="INFO", colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level:^7}</level> | {message}")

    if not cfg.API_KEY:
        logger.error("SENTINEL_API_KEY not set!")
        raise typer.Exit(1)

    try:
        resp = httpx.get(
            f"{cfg.API_URL}/health",
            headers={"X-API-Key": cfg.API_KEY},
            timeout=5.0,
        )
        logger.info("API response: {}", resp.json())
        logger.success("Connection OK")
    except Exception as exc:
        logger.error("Connection failed: {}", exc)
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Print agent version."""
    from sentinel_edge import __version__
    typer.echo(f"Sentinel Edge Agent v{__version__}")


if __name__ == "__main__":
    app()
