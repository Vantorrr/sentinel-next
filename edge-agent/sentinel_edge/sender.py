"""Send JSON events and heartbeats. Video frames are not uploaded.

Delivery is at-least-once. If the process dies after the server accepts a
batch and before the local queue file is updated, that batch is sent again.
The server does not deduplicate. Overflow drops the oldest events on purpose.
"""

from __future__ import annotations

import asyncio
import platform
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import psutil
from loguru import logger

from sentinel_edge.config import EdgeSettings
from sentinel_edge.health import RuntimeHealth
from sentinel_edge.queuefile import DurableQueue


class EventSender:
    def __init__(
        self,
        settings: EdgeSettings,
        queue_path: Path,
        health: RuntimeHealth,
        *,
        fps_provider: Callable[[], float] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._health = health
        self._fps_provider = fps_provider or (lambda: 0.0)
        self._queue = DurableQueue(queue_path, maxlen=settings.queue_max)
        self._client = client or httpx.AsyncClient(
            base_url=settings.api_url,
            headers={"X-API-Key": settings.api_key},
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        self._running = False
        self._health.queue_depth = len(self._queue.events)
        self._health.dropped_oldest = self._queue.dropped

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._flush_loop(), name="event-flush")
        asyncio.create_task(self._heartbeat_loop(), name="heartbeat")
        logger.info("Sender started")

    async def stop(self) -> None:
        self._running = False
        await self._flush()
        await self._client.aclose()

    def push(self, event: dict[str, Any]) -> None:
        event.setdefault("timestamp_ms", int(time.time() * 1000))
        event.setdefault("location_id", "default")
        self._queue.push(event)
        self._sync_depth()

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self._settings.event_flush_interval)
            await self._flush()

    async def _flush(self) -> None:
        if not self._queue.events:
            return
        batch = self._queue.events[: self._settings.event_batch_size]
        try:
            resp = await self._client.post("/api/v1/agent/events", json={
                "agent_id": self._settings.agent_id,
                "events": batch,
            })
        except httpx.HTTPError as exc:
            self._health.last_event_status = None
            logger.error("Event send error: {}", type(exc).__name__)
            return
        self._health.last_event_status = resp.status_code
        if resp.status_code == 200:
            self._queue.ack(len(batch))
            self._health.last_event_ack_wall = time.time()
            self._sync_depth()
            logger.debug("Event batch accepted: {}", len(batch))
            return
        logger.warning("Event send failed: {}", resp.status_code)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            await self.send_heartbeat()
            await asyncio.sleep(self._settings.heartbeat_interval)

    async def send_heartbeat(self) -> None:
        fps = float(self._fps_provider())
        self._health.fps = fps
        try:
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=None)
            resp = await self._client.post("/api/v1/agent/heartbeat", json={
                "agent_id": self._settings.agent_id,
                "agent_name": self._settings.agent_name,
                "hostname": platform.node(),
                "cameras_count": len(self._settings.camera_list()),
                "cpu_usage": cpu,
                "memory_mb": mem.used / (1024 * 1024),
                "fps": fps,
                "version": "0.2.0",
            })
        except httpx.HTTPError as exc:
            self._health.last_heartbeat_status = None
            logger.warning("Heartbeat error: {}", type(exc).__name__)
            return
        self._health.last_heartbeat_status = resp.status_code
        if resp.status_code == 200:
            self._health.last_heartbeat_ack_wall = time.time()

    def _sync_depth(self) -> None:
        self._health.queue_depth = len(self._queue.events)
        self._health.dropped_oldest = self._queue.dropped
