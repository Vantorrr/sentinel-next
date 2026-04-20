"""
YOLOv11 detection service — CPU/CUDA universal build.

No MPS. Device is auto-selected at startup (cuda if available, else cpu).
Runs in a dedicated ThreadPoolExecutor to avoid blocking the event loop.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import numpy as np
from loguru import logger

from sentinel.core.config import get_settings

cfg = get_settings()

PERSON_CLASS_ID = 0
RELEVANT_CLASSES = {0: "person"}


@dataclass
class DetectionResult:
    track_id: str
    bbox: list[float]       # [x1, y1, x2, y2] absolute pixels
    confidence: float
    class_id: int
    class_name: str
    cx: float
    cy: float

    @property
    def area(self) -> float:
        return (self.bbox[2] - self.bbox[0]) * (self.bbox[3] - self.bbox[1])


class DetectionService:
    """YOLOv11 wrapper. Loads once, reused across all camera threads."""

    def __init__(self) -> None:
        self._model = None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="yolo")
        self._ready = False
        self._frame_count = 0
        self._fps_log_every = 200

    @property
    def ready(self) -> bool:
        return self._ready

    async def load(self) -> None:
        loop = asyncio.get_event_loop()
        logger.info("🤖 Loading YOLOv11 — model={} device={}", cfg.YOLO_MODEL, cfg.YOLO_DEVICE)
        t0 = time.monotonic()
        self._model = await loop.run_in_executor(self._executor, self._load_model)
        elapsed = time.monotonic() - t0
        self._ready = True
        logger.success("✅ YOLOv11 ready in {:.1f}s — device={}", elapsed, cfg.YOLO_DEVICE)

    def _load_model(self):  # type: ignore[no-untyped-def]
        from ultralytics import YOLO  # lazy import
        model = YOLO(str(cfg.MODELS_DIR / cfg.YOLO_MODEL))
        dummy = np.zeros((640, 640, 3), dtype=np.uint8)
        model(dummy, device=cfg.YOLO_DEVICE, verbose=False)
        return model

    async def detect(self, image: np.ndarray) -> list[DetectionResult]:
        if not self._ready or self._model is None:
            return []
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(self._executor, self._run_inference, image)

        self._frame_count += 1
        if self._frame_count % self._fps_log_every == 0:
            logger.debug("🔍 YOLO processed {} frames", self._frame_count)

        return results

    def _run_inference(self, image: np.ndarray) -> list[DetectionResult]:
        results = self._model(
            image,
            device=cfg.YOLO_DEVICE,
            conf=cfg.YOLO_CONFIDENCE,
            iou=cfg.YOLO_IOU,
            classes=[PERSON_CLASS_ID],
            verbose=False,
            imgsz=640,
        )
        detections: list[DetectionResult] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls_id = int(box.cls[0])
                x1, y1, x2, y2 = box.xyxy[0].tolist()
                conf = float(box.conf[0])
                detections.append(DetectionResult(
                    track_id="",
                    bbox=[x1, y1, x2, y2],
                    confidence=conf,
                    class_id=cls_id,
                    class_name=RELEVANT_CLASSES.get(cls_id, str(cls_id)),
                    cx=(x1 + x2) / 2,
                    cy=(y1 + y2) / 2,
                ))
        return detections
