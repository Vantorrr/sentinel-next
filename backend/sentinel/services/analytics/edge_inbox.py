"""Idempotent durable ingestion; live delivery is at-least-once."""
import asyncio
import json
import hashlib
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sentinel.core.events import SentinelEvent, EventBus
from sentinel.db.base import AsyncSessionLocal
from sentinel.db.models.edge_event import EdgeEventRecord
from loguru import logger

async def store_batch(db, tenant_id, agent_id, events):
    ids = []
    for ev in events:
        source_id = ev.payload.get('edge_event_id')
        if source_id is None:
            # Older agents (including PR 2) have no UUID. Content-based fallback
            # preserves compatibility; new agents must use unique source IDs.
            canonical = json.dumps(ev.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
            source_id = 'legacy-' + hashlib.sha256(canonical.encode()).hexdigest()
        if not isinstance(source_id, str) or not 1 <= len(source_id) <= 128:
            raise ValueError('edge_event_id is required (1..128 characters)')
        identifier = str(uuid5(NAMESPACE_URL, json.dumps([tenant_id, agent_id, source_id])))
        previous = await db.scalar(select(EdgeEventRecord.event_json).where(EdgeEventRecord.id == identifier))
        timestamp = ev.timestamp_ms or (json.loads(previous)['timestamp_ms'] if previous else int(datetime.now(timezone.utc).timestamp()*1000))
        event = SentinelEvent(id=identifier, tenant_id=tenant_id, camera_id=ev.camera_id,
            location_id=ev.location_id, type=ev.type, track_id=ev.track_id,
            person_id=ev.person_id, confidence=ev.confidence,
            timestamp_ms=timestamp,
            payload={**ev.payload, 'agent_id':agent_id})
        body = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        statement = insert(EdgeEventRecord).values(id=identifier, tenant_id=tenant_id,
            agent_id=agent_id, source_id=source_id, event_json=body).on_conflict_do_nothing(index_elements=['id'])
        await db.execute(statement)
        existing = await db.scalar(select(EdgeEventRecord.event_json).where(EdgeEventRecord.id==identifier))
        if not ev.timestamp_ms and existing:
            # Concurrent legacy retries may choose different receive times.
            event.timestamp_ms = json.loads(existing)['timestamp_ms']
            body = json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        if existing != body:
            raise ValueError('An event ID was reused with different content')
        ids.append(source_id)
    await db.commit()
    return ids

async def dispatch_once(session_factory=AsyncSessionLocal, bus=None):
    bus = bus or EventBus.get()
    async with session_factory() as db:
        async with db.begin():
            rows = (await db.scalars(select(EdgeEventRecord).where(
                EdgeEventRecord.published_at.is_(None)).order_by(EdgeEventRecord.received_at)
                .limit(100).with_for_update(skip_locked=True))).all()
            for row in rows:
                await bus.publish(SentinelEvent.model_validate_json(row.event_json), reliable=True)
                row.published_at = datetime.now(timezone.utc)
            return len(rows)

async def run_outbox():
    while True:
        try:
            count = await dispatch_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning('Edge outbox delivery failed; stored events retained')
            count = 0
        await asyncio.sleep(.1 if count else 2)
