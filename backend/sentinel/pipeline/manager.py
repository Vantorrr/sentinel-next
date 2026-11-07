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
from sentinel.pipeline.stream_target import (
    StreamState,
    classify_stream_url,
    diagnostic_message,
    redact_stream_url,
    redact_text,
)
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
        self._states: dict[str, StreamState] = {}
        # Bumped on every start and stop so an in-flight _start_camera cannot
        # install a processor after remove/reimport.
        self._generations: dict[str, int] = {}
        # One physical weight load for the process. Cancelling a camera does not
        # cancel this task: run_in_executor keeps running after the await is dropped.
        self._model_flight: asyncio.Task[None] | None = None
        self._closing = False

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

    def _models_ready(self) -> bool:
        return (
            self._detection is not None
            and self._detection.ready
            and self._reid is not None
            and self._reid.ready
        )

    def _drop_unready_models(self) -> None:
        """A cancelled or failed load must not stick as a non-ready singleton."""
        if self._detection is not None and not self._detection.ready:
            self._detection = None
        if self._reid is not None and not self._reid.ready:
            self._reid = None

    async def _load_service(self, current: Any, factory: Any) -> Any:
        if current is not None and current.ready:
            return current
        service = factory()
        await service.load()
        if not service.ready:
            raise RuntimeError("AI service load returned before it was ready")
        return service

    async def _run_model_flight(self) -> None:
        """Own the only in-flight weight load. Camera tasks only wait on it."""
        try:
            logger.info("🚀 Loading AI models (YOLO + InsightFace)…")
            self._detection = await self._load_service(self._detection, DetectionService)
            self._reid = await self._load_service(self._reid, FaceReIDService)
            if not self._models_ready():
                raise RuntimeError("AI service load returned before it was ready")
            logger.success("✅ AI models ready")
        except asyncio.CancelledError:
            self._drop_unready_models()
            raise
        except Exception as exc:
            self._drop_unready_models()
            logger.error("AI model load failed: {} — cameras will not process frames", exc)
            raise

    async def _ensure_models(self) -> None:
        if self._models_ready():
            return
        flight = self._model_flight
        if flight is None or flight.done():
            if self._closing:
                raise RuntimeError("AI model load rejected: manager is shutting down")
            flight = asyncio.create_task(self._run_model_flight(), name="model-flight")
            self._model_flight = flight
        # shield: cancelling the camera must not cancel the executor load,
        # and must not let the next camera allocate a second copy.
        await asyncio.shield(flight)

    async def shutdown(self) -> None:
        logger.info("🛑 PipelineManager shutdown — cancelling {} camera tasks", len(self._tasks))
        self._closing = True
        for camera_id in list(self._generations):
            self._bump_generation(camera_id)
        pending = [task for task in self._tasks.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()
        # The model flight is intentionally not cancelled. Its worker thread
        # cannot be stopped, and a second flight must not start over it.

    def add_camera(self, config: CameraConfig, *, start: bool = True) -> None:
        if config.id in self._tasks and not self._tasks[config.id].done():
            logger.warning("Camera '{}' already running — skipping", config.id)
            return
        if config.id not in self._cameras and len(self._cameras) >= cfg.MAX_CAMERAS:
            raise RuntimeError(f"Max cameras reached ({cfg.MAX_CAMERAS})")

        self._bump_generation(config.id)
        target = classify_stream_url(config.url)
        state = StreamState(
            host_class=target.host_class,
            requirement=target.requirement,
            scheme=target.scheme,
        )
        self._cameras[config.id] = config
        self._states[config.id] = state
        if target.blocked or not start:
            # Legacy placeholder / passwordless rows stay stored and visible.
            # Do not open them and do not rewrite the host.
            if target.blocked:
                state.status = "unreachable"
                state.last_error = target.reason
                logger.warning("📷 Camera '{}' not started: {}", config.id, target.host_class)
            return

        self._tracking_pool[config.id] = TrackingService(max_age=cfg.TRACK_MAX_AGE)
        generation = self._generations[config.id]
        starter = asyncio.create_task(
            self._start_camera(config, state, generation),
            name=f"start-{config.id}",
        )
        self._tasks[config.id] = starter
        starter.add_done_callback(lambda t, cid=config.id: self._on_task_done(cid, t))

    def _bump_generation(self, camera_id: str) -> int:
        generation = self._generations.get(camera_id, 0) + 1
        self._generations[camera_id] = generation
        return generation

    def _is_current(self, camera_id: str, generation: int, state: StreamState) -> bool:
        return (
            self._generations.get(camera_id) == generation
            and self._states.get(camera_id) is state
        )

    async def _start_camera(
        self,
        config: CameraConfig,
        state: StreamState,
        generation: int,
    ) -> None:
        """Load zones then start the processor task.

        The starter itself is the owned task until the processor replaces it.
        remove/reimport cancels that task and bumps generation, so a late
        resume cannot publish into a newer StreamState.
        """
        try:
            await self._ensure_models()
            if not self._is_current(config.id, generation, state):
                return
            try:
                zone_configs = await load_zones_for_camera(config.id)
            except Exception as exc:
                logger.warning("Failed to load zones for camera {}: {}", config.id, exc)
                zone_configs = []
            if not self._is_current(config.id, generation, state):
                return

            zt = ZoneTracker(
                camera_id=config.id,
                location_id=config.location_id,
                tenant_id=config.tenant_id,
                zones=zone_configs,
            )
            self._zone_trackers[config.id] = zt

            reader = CameraReader(config, state)
            processor = CameraProcessor(
                reader=reader,
                detection_svc=self._detection,  # type: ignore[arg-type]
                tracking_svc=self._tracking_pool[config.id],
                reid_svc=self._reid,  # type: ignore[arg-type]
                heatmap_svc=self._heatmap,
                bus=self._bus,
                zone_tracker=zt,
            )
            worker = asyncio.create_task(processor.run(), name=f"cam-{config.id}")
            if not self._is_current(config.id, generation, state):
                worker.cancel()
                return
            self._tasks[config.id] = worker
            worker.add_done_callback(lambda t, cid=config.id: self._on_task_done(cid, t))
            logger.info(
                "📷 Camera '{}' reader started ({})",
                config.id, state.host_class or "unknown",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self._is_current(config.id, generation, state):
                state.status = "offline"
                state.last_error = "Модели ИИ не загрузились, поток не запущен"
            logger.error("Cannot start camera '{}': AI unavailable — {}", config.id, exc)

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
        self._bump_generation(camera_id)
        task = self._tasks.pop(camera_id, None)
        self._cameras.pop(camera_id, None)
        self._states.pop(camera_id, None)
        self._tracking_pool.pop(camera_id, None)
        self._zone_trackers.pop(camera_id, None)
        if task and not task.done():
            task.cancel()
            asyncio.create_task(self._bus.publish(SentinelEvent(
                type=EventType.CAMERA_OFFLINE,
                camera_id=camera_id,
                location_id="unknown",
            )))
            logger.info("📷 Camera '{}' removed", camera_id)
            return True
        return False

    def _public_row(self, cam: CameraConfig) -> dict[str, Any]:
        state = self._states.get(cam.id) or StreamState(status="offline")
        live = state.status in {"online", "demo"} and state.frames_received > 0
        return {
            "id": cam.id,
            "name": cam.name,
            "url": redact_stream_url(cam.url),
            "location_id": cam.location_id,
            "tenant_id": cam.tenant_id,
            "enabled": cam.enabled,
            "running": live,
            "stream_status": state.status,
            "frames_received": state.frames_received,
            "last_frame_at": state.last_frame_at,
            "last_error": redact_text(state.last_error),
            "host_class": state.host_class,
            "requirement": state.requirement,
        }

    def list_cameras(self) -> list[dict[str, Any]]:
        return [self._public_row(cam) for cam in self._cameras.values()]

    def diagnostics(self, camera_id: str) -> dict[str, Any] | None:
        cam = self._cameras.get(camera_id)
        if cam is None:
            return None
        state = self._states.get(camera_id) or StreamState(status="offline")
        row = self._public_row(cam)
        row["task_alive"] = camera_id in self._tasks and not self._tasks[camera_id].done()
        row["lan_substituted"] = False
        row["message"] = diagnostic_message(
            cam.url,
            status=state.status,
            frames_received=state.frames_received,
            last_error=state.last_error,
        )
        return row

    def get_heatmap(self, camera_id: str) -> dict[str, Any]:
        return self._heatmap.get_snapshot(camera_id)

    def _on_task_done(self, camera_id: str, task: asyncio.Task[None]) -> None:
        if self._tasks.get(camera_id) is not task:
            return
        if task.cancelled():
            logger.debug("Camera task '{}' cancelled", camera_id)
            self._tasks.pop(camera_id, None)
            return
        if exc := task.exception():
            logger.error("❌ Camera task '{}' crashed: {}", camera_id, exc)
            self._tasks.pop(camera_id, None)


_manager: PipelineManager | None = None


def get_manager() -> PipelineManager:
    global _manager
    if _manager is None:
        _manager = PipelineManager()
    return _manager
