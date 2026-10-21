"""
Sentinel Event Bus — Redis pub/sub + in-process asyncio broadcast.

All pipeline components publish SentinelEvent objects.
WebSocket gateway fans out to all connected browsers.
DBWriter persists business events to PostgreSQL.
"""

from __future__ import annotations

import asyncio
import json
from enum import StrEnum
from typing import Any
from uuid import uuid4

import redis.asyncio as aioredis
from loguru import logger
from pydantic import BaseModel, Field

from sentinel.core.config import get_settings

cfg = get_settings()
CHANNEL_ALL = "sentinel:events"


class EventType(StrEnum):
    PERSON_DETECTED  = "person.detected"
    PERSON_LOST      = "person.lost"
    FACE_IDENTIFIED  = "face.identified"
    FACE_UNKNOWN     = "face.unknown"
    EMOTION_ANALYZED = "emotion.analyzed"

    CLIENT_ENTERED   = "client.entered"
    CLIENT_LEFT      = "client.left"
    VIP_DETECTED     = "vip.detected"
    STAFF_DETECTED   = "staff.detected"

    FRAUD_ALERT      = "fraud.alert"
    ZONE_VIOLATION   = "zone.violation"
    ZONE_ENTERED     = "zone.entered"
    ZONE_EXITED      = "zone.exited"
    STAFF_ABSENT     = "staff.absent"
    CLIENT_UNATTENDED = "client.unattended"

    HEATMAP_UPDATE   = "heatmap.update"
    OCCUPANCY_UPDATE = "occupancy.update"
    LLM_SUMMARY      = "llm.summary"

    CAMERA_ONLINE    = "camera.online"
    CAMERA_OFFLINE   = "camera.offline"
    PIPELINE_ERROR   = "pipeline.error"


class SentinelEvent(BaseModel):
    id:           str = Field(default_factory=lambda: str(uuid4()))
    type:         EventType
    camera_id:    str
    location_id:  str = "default"
    tenant_id:    str = "legacy"
    track_id:     str | None = None
    person_id:    str | None = None
    confidence:   float = 1.0
    payload:      dict[str, Any] = Field(default_factory=dict)
    timestamp_ms: int = Field(default_factory=lambda: int(__import__("time").time() * 1000))

    def to_json(self) -> str:
        return self.model_dump_json()


class EventBus:
    _instance: EventBus | None = None

    def __init__(self) -> None:
        self._redis_url = cfg.REDIS_URL
        self._pub:  aioredis.Redis | None = None
        self._sub:  aioredis.client.PubSub | None = None
        self._local_listeners: list[asyncio.Queue[SentinelEvent]] = []
        # Skip Redis echo of events we already delivered locally
        self._locally_published: set[str] = set()

    @classmethod
    def get(cls) -> EventBus:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def connect(self) -> None:
        url = (self._redis_url or "").strip()
        if not url or "localhost:6379" in url or "127.0.0.1:6379" in url:
            # Still allow local dev defaults; on Railway this must be a real service URL
            import os
            if os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_SERVICE_NAME"):
                raise RuntimeError(
                    "REDIS_URL is missing or still points to localhost. "
                    "Railway → + New → Database → Redis, then backend Variables → "
                    "Add Reference → Redis → REDIS_URL (or REDIS_PRIVATE_URL)."
                )
        try:
            self._pub = aioredis.from_url(url, decode_responses=True)
            sub_conn = aioredis.from_url(url, decode_responses=True)
            self._sub = sub_conn.pubsub()
            await self._sub.subscribe(CHANNEL_ALL)
        except Exception as exc:
            raise RuntimeError(
                f"Cannot connect to Redis at {url!r}. "
                "Add a Redis service in the same Railway project and set REDIS_URL "
                "via Variable Reference."
            ) from exc
        asyncio.create_task(self._dispatch_loop(), name="eventbus-dispatch")
        logger.info("📡 EventBus connected — redis={}", url)

    async def disconnect(self) -> None:
        if self._sub:
            await self._sub.unsubscribe(CHANNEL_ALL)
            await self._sub.aclose()
        if self._pub:
            await self._pub.aclose()
        logger.info("📡 EventBus disconnected")

    async def publish(self, event: SentinelEvent) -> None:
        self._locally_published.add(event.id)
        if len(self._locally_published) > 2000:
            # Bound memory — drop oldest half
            self._locally_published = set(list(self._locally_published)[1000:])

        # Local in-process broadcast (same process, zero serialisation)
        for q in list(self._local_listeners):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

        if self._pub:
            try:
                await self._pub.publish(CHANNEL_ALL, event.to_json())
            except Exception as exc:
                logger.warning("EventBus.publish Redis error: {}", exc)
                self._locally_published.discard(event.id)

    def subscribe(self) -> asyncio.Queue[SentinelEvent]:
        q: asyncio.Queue[SentinelEvent] = asyncio.Queue(maxsize=512)
        self._local_listeners.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[SentinelEvent]) -> None:
        try:
            self._local_listeners.remove(q)
        except ValueError:
            pass

    async def _dispatch_loop(self) -> None:
        """Forward Redis messages from other processes → local listeners."""
        assert self._sub is not None
        try:
            async for message in self._sub.listen():
                if message["type"] != "message":
                    continue
                try:
                    event = SentinelEvent.model_validate_json(message["data"])
                    if event.id in self._locally_published:
                        self._locally_published.discard(event.id)
                        continue
                    for q in list(self._local_listeners):
                        try:
                            q.put_nowait(event)
                        except asyncio.QueueFull:
                            pass
                except Exception as exc:
                    logger.warning("EventBus dispatch error: {}", exc)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("EventBus dispatch loop crashed: {}", exc)
