"""Camera capture with RTSP reconnection + frame skipping."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator

import cv2
import numpy as np
from loguru import logger

from sentinel_edge.config import cfg


class CameraStream:
    """Async camera reader with reconnection and frame-rate control."""

    def __init__(self, source: str, camera_id: str = "cam-0") -> None:
        self._source = source
        self.camera_id = camera_id
        self._cap: cv2.VideoCapture | None = None
        self._reconnect_delay = 2.0

    def _open(self) -> bool:
        try:
            src = int(self._source)
        except ValueError:
            src = self._source

        self._cap = cv2.VideoCapture(src)
        if self._cap.isOpened():
            logger.info("Camera {} opened: {}", self.camera_id, self._source)
            self._reconnect_delay = 2.0
            return True
        logger.warning("Camera {} failed to open: {}", self.camera_id, self._source)
        return False

    async def frames(self) -> AsyncIterator[np.ndarray]:
        """Yield frames at configured FPS."""
        frame_interval = 1.0 / cfg.FPS_INFERENCE
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
                logger.warning("Camera {} lost frame, reconnecting...", self.camera_id)
                self._cap.release()
                self._cap = None
                await asyncio.sleep(self._reconnect_delay)
                continue

            yield frame

            elapsed = time.monotonic() - start
            sleep_for = frame_interval - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)

    def release(self) -> None:
        if self._cap:
            self._cap.release()
