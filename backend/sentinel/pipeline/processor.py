"""
Core inference pipeline for a single camera stream.

Flow:
  CameraFrame
    → YOLOv11 Detection
    → ByteTrack Tracking
    → InsightFace ReID (face crop)
    → EventBus (SentinelEvent)
    → DBWriter (async, separate task) persists to PostgreSQL

Publishes occupancy updates every OCCUPANCY_UPDATE_INTERVAL frames.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import numpy as np
from loguru import logger

from sentinel.core.config import get_settings
from sentinel.core.events import EventBus, EventType, SentinelEvent
from sentinel.core.logging_setup import log_camera_event
from sentinel.pipeline.camera import CameraFrame, CameraReader
from sentinel.services.ai.detection import DetectionResult, DetectionService
from sentinel.services.ai.face_reid import FaceReIDService, Identity
from sentinel.services.ai.tracking import TrackingService
from sentinel.services.ai.zone_tracker import ZoneTracker
from sentinel.services.analytics.heatmap import HeatmapService

cfg = get_settings()

OCCUPANCY_UPDATE_INTERVAL = 30   # frames between occupancy publishes
REID_INTERVAL_FRAMES = 25        # re-attempt ReID every N frames per track


class CameraProcessor:
    """
    Per-camera pipeline orchestrator. Runs forever inside a dedicated asyncio task.
    """

    def __init__(
        self,
        reader: CameraReader,
        detection_svc: DetectionService,
        tracking_svc: TrackingService,
        reid_svc: FaceReIDService,
        heatmap_svc: HeatmapService,
        bus: EventBus,
        zone_tracker: ZoneTracker | None = None,
    ) -> None:
        self.reader = reader
        self.detection = detection_svc
        self.tracking = tracking_svc
        self.reid = reid_svc
        self.heatmap = heatmap_svc
        self.bus = bus
        self.zone_tracker = zone_tracker
        self.camera_id = reader.config.id
        self.location_id = reader.config.location_id
        self.tenant_id = reader.config.tenant_id

        self._active_tracks: dict[str, dict[str, Any]] = {}
        self._frame_count = 0
        self._t_start = time.monotonic()

    async def run(self) -> None:
        log_camera_event("START", self.camera_id)
        async for frame in self.reader.stream():
            try:
                await self._process_frame(frame)
            except Exception as exc:
                logger.error("❌ [CAM {}] frame error: {}", self.camera_id, exc)
                await self.bus.publish(SentinelEvent(
                    type=EventType.PIPELINE_ERROR,
                    camera_id=self.camera_id,
                    location_id=self.location_id,
                    tenant_id=self.tenant_id,
                    payload={"error": str(exc)},
                ))

    async def _process_frame(self, frame: CameraFrame) -> None:
        self._frame_count += 1

        # Demo frames skip heavy inference (no real image data)
        if frame.is_demo:
            await self._inject_demo_events()
            return

        # 1 — YOLO detection
        detections = await self.detection.detect(frame.image)

        # 2 — ByteTrack
        tracks = await self.tracking.update(detections, frame.image)

        # 3 — Per-track ReID
        await asyncio.gather(*[
            self._process_track(frame, t) for t in tracks
        ], return_exceptions=True)

        # 3.5 — Zone tracking
        if self.zone_tracker and self.zone_tracker.active:
            known = {
                tid: {
                    "person_id": s.get("person_id"),
                    "category": s.get("category", "new"),
                    "name": s.get("name"),
                }
                for tid, s in self._active_tracks.items()
            }
            zone_events = self.zone_tracker.update(tracks, known)
            for ze in zone_events:
                await self.bus.publish(ze)

        # 4 — Heatmap (fire-and-forget)
        asyncio.create_task(
            self.heatmap.update(self.camera_id, [(t.cx, t.cy) for t in tracks])
        )

        # 5 — Handle departed tracks
        current_ids = {t.track_id for t in tracks}
        for gone_id in [k for k in self._active_tracks if k not in current_ids]:
            state = self._active_tracks.pop(gone_id)
            await self.bus.publish(SentinelEvent(
                type=EventType.PERSON_LOST,
                camera_id=self.camera_id,
                location_id=self.location_id,
                tenant_id=self.tenant_id,
                track_id=gone_id,
                person_id=state.get("person_id"),
                payload={"dwell_seconds": round(time.time() - state["first_seen"], 1)},
            ))

        # 6 — Periodic occupancy broadcast
        if self._frame_count % OCCUPANCY_UPDATE_INTERVAL == 0:
            await self.bus.publish(SentinelEvent(
                type=EventType.OCCUPANCY_UPDATE,
                camera_id=self.camera_id,
                location_id=self.location_id,
                tenant_id=self.tenant_id,
                payload={"count": len(self._active_tracks)},
            ))
            elapsed = time.monotonic() - self._t_start
            fps = self._frame_count / max(elapsed, 0.001)
            logger.debug("📊 [CAM {}] occupancy={} fps={:.1f}",
                         self.camera_id, len(self._active_tracks), fps)

    async def _process_track(self, frame: CameraFrame, track: Any) -> None:
        track_id = str(track.track_id)
        is_new = track_id not in self._active_tracks

        if is_new:
            self._active_tracks[track_id] = {
                "first_seen": time.time(),
                "person_id": None,
                "reid_frame": 0,
                "reid_done": False,
            }
            await self.bus.publish(SentinelEvent(
                type=EventType.PERSON_DETECTED,
                camera_id=self.camera_id,
                location_id=self.location_id,
                tenant_id=self.tenant_id,
                track_id=track_id,
                confidence=float(track.confidence),
                payload={"bbox": track.bbox},
            ))

        state = self._active_tracks[track_id]
        state["reid_frame"] += 1

        # Try ReID on new track and every REID_INTERVAL_FRAMES
        if is_new or state["reid_frame"] % REID_INTERVAL_FRAMES == 0:
            face_crop = _crop_face(frame.image, track.bbox)
            if face_crop is not None and self.reid.ready:
                identity: Identity | None = await self.reid.identify(face_crop)
                if identity and identity.person_id != state.get("person_id"):
                    state["person_id"] = identity.person_id
                    state["category"] = identity.category
                    state["name"] = identity.name
                    state["reid_done"] = True
                    await self.bus.publish(SentinelEvent(
                        type=EventType.FACE_IDENTIFIED,
                        camera_id=self.camera_id,
                        location_id=self.location_id,
                        tenant_id=self.tenant_id,
                        track_id=track_id,
                        person_id=identity.person_id,
                        confidence=identity.similarity,
                        payload={
                            "name": identity.name,
                            "category": identity.category,
                            "visit_count": identity.visit_count,
                        },
                    ))
                    if identity.category == "vip":
                        await self.bus.publish(SentinelEvent(
                            type=EventType.VIP_DETECTED,
                            camera_id=self.camera_id,
                            location_id=self.location_id,
                            tenant_id=self.tenant_id,
                            track_id=track_id,
                            person_id=identity.person_id,
                            payload={"name": identity.name},
                        ))
                    elif identity.category == "staff":
                        await self.bus.publish(SentinelEvent(
                            type=EventType.STAFF_DETECTED,
                            camera_id=self.camera_id,
                            location_id=self.location_id,
                            tenant_id=self.tenant_id,
                            track_id=track_id,
                            person_id=identity.person_id,
                            payload={"name": identity.name},
                        ))
                elif is_new and not identity:
                    await self.bus.publish(SentinelEvent(
                        type=EventType.CLIENT_ENTERED,
                        camera_id=self.camera_id,
                        location_id=self.location_id,
                        tenant_id=self.tenant_id,
                        track_id=track_id,
                        payload={"category": "new"},
                    ))

    # ── Demo mode ──────────────────────────────────────────────────────────────

    async def _inject_demo_events(self) -> None:
        """Every 150 demo frames synthesise a plausible event sequence."""
        if self._frame_count % 150 != 0:
            return
        import random
        demo_names = ["Андрей", "Маша", "Новый клиент", "Иван", "VIP гость"]
        demo_cats = ["staff", "regular", "new", "vip", "new"]
        idx = random.randint(0, len(demo_names) - 1)
        name = demo_names[idx]
        cat = demo_cats[idx]
        track_id = f"demo-{self._frame_count}"
        person_id = f"demo-person-{idx}"

        await self.bus.publish(SentinelEvent(
            type=EventType.CLIENT_ENTERED,
            camera_id=self.camera_id,
            location_id=self.location_id,
            tenant_id=self.tenant_id,
            track_id=track_id,
            payload={"category": cat},
        ))
        await asyncio.sleep(0.05)
        await self.bus.publish(SentinelEvent(
            type=EventType.FACE_IDENTIFIED,
            camera_id=self.camera_id,
            location_id=self.location_id,
            tenant_id=self.tenant_id,
            track_id=track_id,
            person_id=person_id,
            confidence=round(0.75 + random.random() * 0.2, 2),
            payload={"name": name, "category": cat, "visit_count": random.randint(1, 20)},
        ))
        if cat == "vip":
            await self.bus.publish(SentinelEvent(
                type=EventType.VIP_DETECTED,
                camera_id=self.camera_id,
                location_id=self.location_id,
                tenant_id=self.tenant_id,
                track_id=track_id,
                person_id=person_id,
                payload={"name": name},
            ))

        await self.bus.publish(SentinelEvent(
            type=EventType.OCCUPANCY_UPDATE,
            camera_id=self.camera_id,
            location_id=self.location_id,
            tenant_id=self.tenant_id,
            payload={"count": random.randint(1, 8)},
        ))

        # Zone demo events (less frequent)
        if self._frame_count % 450 == 0:
            zone_event_type = random.choice([EventType.STAFF_ABSENT, EventType.CLIENT_UNATTENDED])
            if zone_event_type == EventType.STAFF_ABSENT:
                absence_min = round(random.uniform(5, 15), 1)
                await self.bus.publish(SentinelEvent(
                    type=EventType.STAFF_ABSENT,
                    camera_id=self.camera_id,
                    location_id=self.location_id,
                    tenant_id=self.tenant_id,
                    payload={
                        "zone_name": "Ресепшн",
                        "zone_type": "reception",
                        "absence_minutes": absence_min,
                        "description": f"Персонал отсутствует в зоне «Ресепшн» уже {absence_min} мин",
                    },
                ))
            else:
                wait_min = round(random.uniform(2, 8), 1)
                await self.bus.publish(SentinelEvent(
                    type=EventType.CLIENT_UNATTENDED,
                    camera_id=self.camera_id,
                    location_id=self.location_id,
                    tenant_id=self.tenant_id,
                    track_id=track_id,
                    payload={
                        "zone_name": "Зал ожидания",
                        "zone_type": "waiting",
                        "wait_minutes": wait_min,
                        "description": f"Клиент ожидает в «Зал ожидания» {wait_min} мин без внимания персонала",
                    },
                ))


def _crop_face(image: np.ndarray, bbox: list[float]) -> np.ndarray | None:
    h, w = image.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    pad_w = int((x2 - x1) * 0.3)
    pad_h = int((y2 - y1) * 0.3)
    x1, y1 = max(0, x1 - pad_w), max(0, y1 - pad_h)
    x2, y2 = min(w, x2 + pad_w), min(h, y2 + pad_h)
    crop = image[y1:y2, x1:x2]
    return crop if crop.size > 0 else None
