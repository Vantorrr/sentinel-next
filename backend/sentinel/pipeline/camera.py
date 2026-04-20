"""
Camera source abstraction.

Supports:
  - RTSP streams (IP cameras)
  - Local webcam (index or /dev/video*)
  - File/URL (for testing)
  - DEMO mode: generates synthetic noise frames so the pipeline runs
    without any physical camera attached.

Reconnect strategy: exponential backoff from BASE_DELAY up to MAX_DELAY,
reset to base on successful streaming. The reader NEVER raises — it loops
forever, making each camera self-healing.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import AsyncIterator

import cv2
import numpy as np
from loguru import logger

from sentinel.core.config import get_settings

cfg = get_settings()


class CameraStatus(StrEnum):
    CONNECTING = "connecting"
    ONLINE = "online"
    OFFLINE = "offline"
    DEMO = "demo"


@dataclass
class CameraConfig:
    id: str
    url: str                          # rtsp://... | "0" | /dev/video0 | file.mp4 | "demo"
    location_id: str = "default"
    name: str = ""
    tenant_id: str = "legacy"
    zone_polygons: list[list[tuple[int, int]]] = field(default_factory=list)
    fps_capture: int = 30
    fps_inference: int = 10
    enabled: bool = True


@dataclass
class CameraFrame:
    camera_id: str
    location_id: str
    frame_id: int
    timestamp_ms: int
    image: np.ndarray  # BGR HxWx3
    is_demo: bool = False


class CameraReader:
    """
    Async generator → CameraFrame.

    Never raises. On any failure, waits with exponential backoff and retries.
    """

    def __init__(self, config: CameraConfig) -> None:
        self.config = config
        self.status = CameraStatus.CONNECTING
        self._frame_counter = 0
        self._drop_ratio = max(1, config.fps_capture // max(1, config.fps_inference))
        self._reconnect_delay = cfg.CAMERA_RECONNECT_BASE_DELAY

    # ── Public API ─────────────────────────────────────────────────────────────

    async def stream(self) -> AsyncIterator[CameraFrame]:
        """Infinite generator. Reconnects on failure."""
        url = self.config.url.strip()

        if url == "demo":
            async for frame in self._demo_stream():
                yield frame
            return

        while True:
            try:
                async for frame in self._try_open(url):
                    self._reconnect_delay = cfg.CAMERA_RECONNECT_BASE_DELAY
                    yield frame
            except Exception as exc:
                self.status = CameraStatus.OFFLINE
                logger.warning(
                    "📷 [CAM {}] offline — {}. Retry in {:.0f}s",
                    self.config.id, exc, self._reconnect_delay,
                )
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2,
                    cfg.CAMERA_RECONNECT_MAX_DELAY,
                )

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _try_open(self, url: str) -> AsyncIterator[CameraFrame]:
        """Try PyAV first, fallback to OpenCV."""
        try:
            async for frame in self._read_pyav(url):
                yield frame
            return
        except ImportError:
            pass  # av not installed
        except Exception as exc:
            logger.debug("📷 [CAM {}] PyAV failed ({}), trying OpenCV", self.config.id, exc)

        async for frame in self._read_opencv(url):
            yield frame

    async def _read_pyav(self, url: str) -> AsyncIterator[CameraFrame]:
        import av  # lazy import — optional dep

        options: dict[str, str] = {}
        if url.startswith("rtsp"):
            options = {
                "rtsp_transport": "tcp",
                "stimeout": "10000000",  # 10s connection timeout (Hikvision can be slow)
                "fflags": "nobuffer",
                "flags": "low_delay",
                "allowed_media_types": "video",
                "reorder_queue_size": "0",
            }

        container = av.open(url, options=options)
        video_stream = container.streams.video[0]
        video_stream.thread_type = "AUTO"

        self.status = CameraStatus.ONLINE
        logger.success("📷 [CAM {}] online via PyAV — {}", self.config.id, url)

        loop = asyncio.get_event_loop()
        frame_idx = 0

        try:
            for packet in container.demux(video_stream):
                for av_frame in packet.decode():
                    frame_idx += 1
                    if frame_idx % self._drop_ratio != 0:
                        continue

                    image = await loop.run_in_executor(
                        None, lambda f=av_frame: f.to_ndarray(format="bgr24")
                    )
                    self._frame_counter += 1
                    yield CameraFrame(
                        camera_id=self.config.id,
                        location_id=self.config.location_id,
                        frame_id=self._frame_counter,
                        timestamp_ms=int(time.time() * 1000),
                        image=image,
                    )
                    await asyncio.sleep(0)
        finally:
            container.close()

    async def _read_opencv(self, url: str) -> AsyncIterator[CameraFrame]:
        src: str | int = int(url) if url.isdigit() else url

        if isinstance(src, str) and src.startswith("rtsp"):
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        else:
            cap = cv2.VideoCapture(src)  # type: ignore[call-arg]

        if not cap.isOpened():
            raise RuntimeError(f"OpenCV cannot open: {url}")

        self.status = CameraStatus.ONLINE
        logger.success("📷 [CAM {}] online via OpenCV — {}", self.config.id, url)

        loop = asyncio.get_event_loop()
        frame_idx = 0
        interval = 1.0 / max(1, self.config.fps_inference)

        try:
            while True:
                t0 = time.monotonic()
                ret, image = await loop.run_in_executor(None, cap.read)
                if not ret:
                    raise RuntimeError("cap.read() returned False — stream ended or disconnected")

                frame_idx += 1
                if frame_idx % self._drop_ratio != 0:
                    continue

                self._frame_counter += 1
                yield CameraFrame(
                    camera_id=self.config.id,
                    location_id=self.config.location_id,
                    frame_id=self._frame_counter,
                    timestamp_ms=int(time.time() * 1000),
                    image=image,
                )
                elapsed = time.monotonic() - t0
                await asyncio.sleep(max(0, interval - elapsed))
        finally:
            cap.release()

    async def _demo_stream(self) -> AsyncIterator[CameraFrame]:
        """
        Generates synthetic 640x480 BGR frames at fps_inference rate.
        Useful for local development without a real camera.
        """
        self.status = CameraStatus.DEMO
        logger.info("📷 [CAM {}] running in DEMO mode (synthetic frames)", self.config.id)

        interval = 1.0 / max(1, self.config.fps_inference)
        rng = np.random.default_rng(42)

        while True:
            t0 = time.monotonic()
            # Dark grey frame with noise + timestamp watermark
            frame = (rng.integers(20, 40, (480, 640, 3)) ).astype(np.uint8)
            ts = time.strftime("%H:%M:%S")
            cv2.putText(frame, f"DEMO | {self.config.id} | {ts}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 200, 200), 1)

            self._frame_counter += 1
            yield CameraFrame(
                camera_id=self.config.id,
                location_id=self.config.location_id,
                frame_id=self._frame_counter,
                timestamp_ms=int(time.time() * 1000),
                image=frame,
                is_demo=True,
            )
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, interval - elapsed))
