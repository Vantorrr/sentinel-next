"""HTTP sender — batches events and sends to central Sentinel API."""

from __future__ import annotations

import asyncio
import platform
import time
from collections import deque
from typing import Any

import httpx
import psutil
from loguru import logger

from sentinel_edge.config import cfg


class EventSender:
    """Accumulates events, sends in batches to /api/v1/agent/events."""

    def __init__(self) -> None:
        self._buffer: deque[dict[str, Any]] = deque(maxlen=1000)
        self._client = httpx.AsyncClient(
            base_url=cfg.API_URL,
            headers={"X-API-Key": cfg.API_KEY},
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        self._running = False

    async def start(self) -> None:
        self._running = True
        asyncio.create_task(self._flush_loop(), name="event-flush")
        asyncio.create_task(self._heartbeat_loop(), name="heartbeat")
        logger.info("Sender started → {}", cfg.API_URL)

    async def stop(self) -> None:
        self._running = False
        await self._flush()
        await self._client.aclose()

    def push(self, event: dict[str, Any]) -> None:
        event.setdefault("timestamp_ms", int(time.time() * 1000))
        self._buffer.append(event)

    async def _flush_loop(self) -> None:
        while self._running:
            await asyncio.sleep(cfg.EVENT_FLUSH_INTERVAL)
            await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return

        batch = []
        while self._buffer and len(batch) < cfg.EVENT_BATCH_SIZE:
            batch.append(self._buffer.popleft())

        try:
            resp = await self._client.post("/api/v1/agent/events", json={
                "agent_id": cfg.AGENT_ID,
                "events": batch,
            })
            if resp.status_code == 200:
                data = resp.json()
                logger.debug("Sent {} events → accepted={}", len(batch), data.get("accepted"))
            else:
                logger.warning("Event send failed: {} {}", resp.status_code, resp.text[:200])
                for ev in reversed(batch):
                    self._buffer.appendleft(ev)
        except httpx.HTTPError as exc:
            logger.error("Event send error: {}", exc)
            for ev in reversed(batch):
                self._buffer.appendleft(ev)

    async def _heartbeat_loop(self) -> None:
        while self._running:
            try:
                mem = psutil.virtual_memory()
                cpu = psutil.cpu_percent(interval=1)
                await self._client.post("/api/v1/agent/heartbeat", json={
                    "agent_id": cfg.AGENT_ID,
                    "agent_name": cfg.AGENT_NAME,
                    "hostname": platform.node(),
                    "cameras_count": len(cfg.CAMERAS.split(",")),
                    "cpu_usage": cpu,
                    "memory_mb": mem.used / (1024 * 1024),
                    "fps": 0.0,
                    "version": "0.1.0",
                })
                logger.debug("Heartbeat sent (cpu={:.1f}%)", cpu)
            except Exception as exc:
                logger.warning("Heartbeat error: {}", exc)

            await asyncio.sleep(cfg.HEARTBEAT_INTERVAL)
