"""Camera capture with RTSP reconnection + frame skipping."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import cv2
import numpy as np
from loguru import logger


def capture_interval(fps: int) -> float:
    """Seconds between captured frames. Zero or negative falls back to 1 fps."""
    return 1.0 / max(1, int(fps))


class CameraStream:
    """Async camera reader with reconnection and frame-rate control."""

    def __init__(
        self,
        source: str,
        camera_id: str = "cam-0",
        *,
        reconnect_delay: float = 2.0,
        frame_interval: float = 0.2,
        on_change=None,
    ) -> None:
        self._source = source
        self.camera_id = camera_id
        self._cap: cv2.VideoCapture | None = None
        self._reconnect_delay = reconnect_delay
        self._reconnect_floor = reconnect_delay
        self._frames = 0
        self.opened = False
        self.last_open_wall: float | None = None
        self.last_frame_wall: float | None = None
        self.last_error = ""
        self._frame_interval = frame_interval
        self._on_change = on_change

    def _notify(self) -> None:
        if self._on_change is not None:
            self._on_change(self)

    def _open(self) -> bool:
        try:
            src = int(self._source)
        except ValueError:
            src = self._source

        self._cap = cv2.VideoCapture(src)
        if self._cap.isOpened():
            # Opened is not a decoded frame. The URL is not logged.
            self.opened = True
            self.last_open_wall = time.time()
            self.last_error = ""
            logger.info("Camera {} opened", self.camera_id)
            self._reconnect_delay = self._reconnect_floor
            self._notify()
            return True
        self.opened = False
        self.last_error = "open failed"
        logger.warning("Camera {} failed to open", self.camera_id)
        self._notify()
        return False

    async def frames(self) -> AsyncIterator[np.ndarray]:
        """Yield frames at configured FPS."""
        frame_interval = self._frame_interval
        loop = asyncio.get_event_loop()

        while True:
            if self._cap is None or not self._cap.isOpened():
                if not self._open():
                    logger.info("Reconnecting in {:.0f}s...", self._reconnect_delay)
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 1.5, 60.0)
                    continue

            start = time.monotonic()
            ret, frame = await loop.run_in_executor(None, self._cap.read)

            if not ret or frame is None:
                self.opened = False
                self.last_error = "read failed"
                self._notify()
                logger.warning("Camera {} lost frame, reconnecting...", self.camera_id)
                self._cap.release()
                self._cap = None
                await asyncio.sleep(self._reconnect_delay)
                continue

            self._frames += 1
            self.last_frame_wall = time.time()
            self.last_error = ""
            if self._frames == 1:
                logger.info("Camera {} first frame received", self.camera_id)
            self._notify()

            yield frame

            elapsed = time.monotonic() - start
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    def release(self) -> None:
        if self._cap:
            self._cap.release()
