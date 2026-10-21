"""
Pipeline Manager — hot-add/remove cameras at runtime.

Owns all CameraProcessor tasks. Thread-safe via asyncio.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

from loguru import logger

from sentinel.core.config import get_settings
from sentinel.core.events import EventBus, EventType, SentinelEvent
from sentinel.pipeline.camera import CameraConfig, CameraReader
from sentinel.pipeline.processor import CameraProcessor
from sentinel.services.ai.detection import DetectionService
from sentinel.services.ai.face_reid import FaceReIDService
from sentinel.services.ai.tracking import TrackingService
from sentinel.services.ai.zone_tracker import ZoneTracker, load_zones_for_camera
from sentinel.services.analytics.heatmap import HeatmapService

cfg = get_settings()


class PipelineManager:
    def __init__(self) -> None:
        self._cameras: dict[str, CameraConfig] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._bus = EventBus.get()
        self._detection: DetectionService | None = None
        self._tracking_pool: dict[str, TrackingService] = {}
        self._zone_trackers: dict[str, ZoneTracker] = {}
        self._reid: FaceReIDService | None = None
        self._heatmap = HeatmapService()

    async def startup(self) -> None:
        # Lazy AI load: Railway/small VMs OOM if YOLO+InsightFace warm at boot.
        # Models load on first camera add (or explicit warm).
        skip = str(__import__("os").environ.get("SKIP_AI_WARMUP", "true")).lower() in (
            "1", "true", "yes",
        )
        if skip:
            logger.info("🚀 PipelineManager ready — AI models deferred until first camera")
            return
        await self._ensure_models()

    async def _ensure_models(self) -> None:
        if self._detection is not None and self._reid is not None:
            return
        logger.info("🚀 Loading AI models (YOLO + InsightFace)…")
        try:
            if self._detection is None:
                self._detection = DetectionService()
                await self._detection.load()
            if self._reid is None:
                self._reid = FaceReIDService()
                await self._reid.load()
            logger.success("✅ AI models ready")
        except Exception as exc:
            logger.error("AI model load failed: {} — cameras will not process frames", exc)
            raise

    async def shutdown(self) -> None:
        logger.info("🛑 PipelineManager shutdown — cancelling {} camera tasks", len(self._tasks))
        for task in self._tasks.values():
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()

    def add_camera(self, config: CameraConfig) -> None:
        if config.id in self._tasks and not self._tasks[config.id].done():
            logger.warning("Camera '{}' already running — skipping", config.id)
            return
        if len(self._cameras) >= cfg.MAX_CAMERAS:
            raise RuntimeError(f"Max cameras reached ({cfg.MAX_CAMERAS})")

        self._cameras[config.id] = config
        self._tracking_pool[config.id] = TrackingService(max_age=cfg.TRACK_MAX_AGE)

        asyncio.create_task(self._start_camera(config))

    async def _start_camera(self, config: CameraConfig) -> None:
        """Load zones then start the processor task."""
        try:
            await self._ensure_models()
        except Exception as exc:
            logger.error("Cannot start camera '{}': AI unavailable — {}", config.id, exc)
            return

        try:
            zone_configs = await load_zones_for_camera(config.id)
        except Exception as exc:
            logger.warning("Failed to load zones for camera {}: {}", config.id, exc)
            zone_configs = []

        zt = ZoneTracker(
            camera_id=config.id,
            location_id=config.location_id,
            tenant_id=config.tenant_id,
            zones=zone_configs,
        )
        self._zone_trackers[config.id] = zt

        reader = CameraReader(config)
        processor = CameraProcessor(
            reader=reader,
            detection_svc=self._detection,  # type: ignore[arg-type]
            tracking_svc=self._tracking_pool[config.id],
            reid_svc=self._reid,  # type: ignore[arg-type]
            heatmap_svc=self._heatmap,
            bus=self._bus,
            zone_tracker=zt,
        )
        task = asyncio.create_task(processor.run(), name=f"cam-{config.id}")
        self._tasks[config.id] = task
        task.add_done_callback(lambda t, cid=config.id: self._on_task_done(cid, t))

        await self._bus.publish(SentinelEvent(
            type=EventType.CAMERA_ONLINE,
            camera_id=config.id,
            location_id=config.location_id,
            tenant_id=config.tenant_id,
            payload={"name": config.name, "url": config.url},
        ))
        logger.success("📷 Camera '{}' added — url={}", config.id, config.url)

    async def reload_zones(self, camera_id: str) -> None:
        """Hot-reload zones for a running camera."""
        zt = self._zone_trackers.get(camera_id)
        if not zt:
            return
        try:
            zone_configs = await load_zones_for_camera(camera_id)
            zt.reload_zones(zone_configs)
        except Exception as exc:
            logger.error("Failed to reload zones for {}: {}", camera_id, exc)

    def remove_camera(self, camera_id: str) -> bool:
        task = self._tasks.pop(camera_id, None)
        self._cameras.pop(camera_id, None)
        self._tracking_pool.pop(camera_id, None)
        self._zone_trackers.pop(camera_id, None)
        if task:
            task.cancel()
            asyncio.create_task(self._bus.publish(SentinelEvent(
                type=EventType.CAMERA_OFFLINE,
                camera_id=camera_id,
                location_id="unknown",
            )))
            logger.info("📷 Camera '{}' removed", camera_id)
            return True
        return False

    def list_cameras(self) -> list[dict[str, Any]]:
        return [
            {
                "id": cam.id,
                "name": cam.name,
                "url": cam.url,
                "location_id": cam.location_id,
                "tenant_id": cam.tenant_id,
                "enabled": cam.enabled,
                "running": cam.id in self._tasks and not self._tasks[cam.id].done(),
            }
            for cam in self._cameras.values()
        ]

    def get_heatmap(self, camera_id: str) -> dict[str, Any]:
        return self._heatmap.get_snapshot(camera_id)

    def _on_task_done(self, camera_id: str, task: asyncio.Task[None]) -> None:
        if task.cancelled():
            logger.debug("Camera task '{}' cancelled", camera_id)
        elif exc := task.exception():
            logger.error("❌ Camera task '{}' crashed: {}", camera_id, exc)
            self._tasks.pop(camera_id, None)


_manager: PipelineManager | None = None


def get_manager() -> PipelineManager:
    global _manager
    if _manager is None:
        _manager = PipelineManager()
    return _manager
