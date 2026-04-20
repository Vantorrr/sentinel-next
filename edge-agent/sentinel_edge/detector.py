"""Local YOLO detection + ByteTrack tracking pipeline."""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np
import supervision as sv
from loguru import logger
from ultralytics import YOLO

from sentinel_edge.config import cfg


class LocalDetector:
    """Runs YOLO inference on frames, tracks with ByteTrack, emits events."""

    PERSON_CLASS_ID = 0

    def __init__(self) -> None:
        self._model: YOLO | None = None
        self._tracker = sv.ByteTrack(
            track_activation_threshold=0.4,
            lost_track_buffer=60,
            minimum_matching_threshold=0.7,
            frame_rate=cfg.FPS_INFERENCE,
        )
        self._active_tracks: set[int] = set()
        self._frame_count = 0
        self._fps = 0.0
        self._last_fps_time = time.time()

    def load(self) -> None:
        model_path = cfg.YOLO_MODEL
        logger.info("Loading YOLO: {}", model_path)
        self._model = YOLO(model_path, verbose=False)
        logger.success("YOLO loaded: {}", model_path)

    def process_frame(self, frame: np.ndarray, camera_id: str) -> list[dict]:
        """Run detection + tracking on a single frame. Returns event dicts."""
        if self._model is None:
            return []

        self._frame_count += 1
        now = time.time()
        if now - self._last_fps_time >= 1.0:
            self._fps = self._frame_count / (now - self._last_fps_time)
            self._frame_count = 0
            self._last_fps_time = now

        results = self._model(frame, conf=cfg.YOLO_CONFIDENCE, verbose=False)[0]

        detections = sv.Detections.from_ultralytics(results)
        person_mask = detections.class_id == self.PERSON_CLASS_ID
        detections = detections[person_mask]

        tracked = self._tracker.update_with_detections(detections)

        events: list[dict] = []
        current_ids: set[int] = set()

        if tracked.tracker_id is not None:
            for i, track_id in enumerate(tracked.tracker_id):
                current_ids.add(int(track_id))
                if int(track_id) not in self._active_tracks:
                    x1, y1, x2, y2 = tracked.xyxy[i].astype(int)
                    events.append({
                        "type": "client.entered",
                        "camera_id": camera_id,
                        "track_id": str(track_id),
                        "confidence": float(tracked.confidence[i]) if tracked.confidence is not None else 0.0,
                        "payload": {
                            "bbox": [int(x1), int(y1), int(x2), int(y2)],
                            "total_visible": len(current_ids),
                        },
                    })

        left_ids = self._active_tracks - current_ids
        for tid in left_ids:
            events.append({
                "type": "person.lost",
                "camera_id": camera_id,
                "track_id": str(tid),
                "payload": {"total_visible": len(current_ids)},
            })

        self._active_tracks = current_ids

        if tracked.tracker_id is not None and len(tracked.tracker_id) > 0:
            events.append({
                "type": "occupancy.update",
                "camera_id": camera_id,
                "payload": {
                    "count": len(current_ids),
                    "fps": round(self._fps, 1),
                },
            })

        return events

    @property
    def fps(self) -> float:
        return self._fps
