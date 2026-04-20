"""
ByteTrack via `supervision` library.

Uses lazy imports so the backend can start (and serve health/API)
even if supervision isn't installed yet (e.g. CI import checks).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from sentinel.services.ai.detection import DetectionResult


@dataclass
class TrackedObject:
    track_id: str
    bbox: list[float]
    confidence: float
    class_name: str
    cx: float
    cy: float


class TrackingService:
    def __init__(self, max_age: int = 30) -> None:
        self._max_age = max_age
        self._tracker: Any = None

    def _get_tracker(self) -> Any:
        if self._tracker is None:
            import supervision as sv  # lazy import
            self._tracker = sv.ByteTrack(
                track_activation_threshold=0.25,
                lost_track_buffer=self._max_age,
                minimum_matching_threshold=0.8,
                frame_rate=10,
            )
        return self._tracker

    async def update(
        self,
        detections: list[DetectionResult],
        image: np.ndarray,
    ) -> list[TrackedObject]:
        if not detections:
            return []

        import supervision as sv  # lazy

        sv_dets = sv.Detections(
            xyxy=np.array([d.bbox for d in detections], dtype=np.float32),
            confidence=np.array([d.confidence for d in detections], dtype=np.float32),
            class_id=np.array([d.class_id for d in detections], dtype=int),
        )
        tracked = self._get_tracker().update_with_detections(sv_dets)

        results: list[TrackedObject] = []
        for i in range(len(tracked)):
            x1, y1, x2, y2 = tracked.xyxy[i].tolist()
            tid = int(tracked.tracker_id[i]) if tracked.tracker_id is not None else i
            conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.5
            results.append(TrackedObject(
                track_id=str(tid),
                bbox=[x1, y1, x2, y2],
                confidence=conf,
                class_name="person",
                cx=(x1 + x2) / 2,
                cy=(y1 + y2) / 2,
            ))
        return results
