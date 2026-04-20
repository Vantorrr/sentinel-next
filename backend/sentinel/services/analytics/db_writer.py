"""
DB Writer — persists business events from EventBus → PostgreSQL.

Handles: CLIENT_ENTERED, PERSON_LOST, FACE_IDENTIFIED, FRAUD_ALERT, LLM_SUMMARY.
Runs as background asyncio task. Errors logged, never crash the service.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone

from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.events import EventBus, EventType, SentinelEvent
from sentinel.db.base import AsyncSessionLocal
from sentinel.db.models.person import Alert, NarrativeSummary, Person, PersonCategory, Visit


class DBWriter:
    def __init__(self) -> None:
        self._bus = EventBus.get()
        self._open_visits: dict[str, int] = {}

    async def run(self) -> None:
        q = self._bus.subscribe()
        logger.info("📝 DBWriter started — persisting events to PostgreSQL")
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=10.0)
                    asyncio.create_task(self._handle(event))
                except TimeoutError:
                    pass
        except asyncio.CancelledError:
            pass
        finally:
            self._bus.unsubscribe(q)

    async def _handle(self, event: SentinelEvent) -> None:
        try:
            async with AsyncSessionLocal() as session:
                if event.type == EventType.CLIENT_ENTERED:
                    await self._on_entered(session, event)
                elif event.type == EventType.PERSON_LOST:
                    await self._on_lost(session, event)
                elif event.type == EventType.FACE_IDENTIFIED:
                    await self._on_identified(session, event)
                elif event.type in (
                    EventType.FRAUD_ALERT,
                    EventType.ZONE_VIOLATION,
                    EventType.STAFF_ABSENT,
                    EventType.CLIENT_UNATTENDED,
                ):
                    await self._on_alert(session, event)
                elif event.type == EventType.LLM_SUMMARY:
                    await self._on_summary(session, event)
                await session.commit()
        except Exception as exc:
            logger.error("❌ DBWriter failed for {}: {}", event.type, exc)

    async def _on_entered(self, session: AsyncSession, event: SentinelEvent) -> None:
        track_id = event.track_id or str(uuid.uuid4())
        visit = Visit(
            tenant_id=event.tenant_id,
            person_id=event.person_id,
            location_id=event.location_id,
            camera_id=event.camera_id,
            track_id=track_id,
            entered_at=datetime.fromtimestamp(event.timestamp_ms / 1000, tz=timezone.utc),
        )
        session.add(visit)
        await session.flush()
        self._open_visits[track_id] = visit.id

    async def _on_lost(self, session: AsyncSession, event: SentinelEvent) -> None:
        track_id = event.track_id or ""
        visit_id = self._open_visits.pop(track_id, None)
        if visit_id is None:
            return
        dwell = float(event.payload.get("dwell_seconds", 0))
        left_at = datetime.fromtimestamp(event.timestamp_ms / 1000, tz=timezone.utc)
        await session.execute(
            update(Visit).where(Visit.id == visit_id).values(left_at=left_at, dwell_seconds=dwell)
        )

    async def _on_identified(self, session: AsyncSession, event: SentinelEvent) -> None:
        if not event.person_id:
            return
        person = (await session.execute(
            select(Person).where(Person.id == event.person_id)
        )).scalar_one_or_none()

        if person:
            person.visit_count += 1  # type: ignore[assignment]
            person.last_seen = datetime.fromtimestamp(event.timestamp_ms / 1000, tz=timezone.utc)
        else:
            person = Person(
                id=event.person_id,
                tenant_id=event.tenant_id,
                name=str(event.payload.get("name", "Незнакомец")),
                category=PersonCategory.NEW,
                visit_count=1,
            )
            session.add(person)

        track_id = event.track_id or ""
        visit_id = self._open_visits.get(track_id)
        if visit_id:
            await session.execute(
                update(Visit).where(Visit.id == visit_id).values(person_id=event.person_id)
            )

    async def _on_alert(self, session: AsyncSession, event: SentinelEvent) -> None:
        high_severity = {EventType.FRAUD_ALERT, EventType.STAFF_ABSENT, EventType.CLIENT_UNATTENDED}
        severity = "high" if event.type in high_severity else "medium"
        description = str(event.payload.get("description", event.type))
        alert = Alert(
            tenant_id=event.tenant_id,
            type=event.type,
            severity=severity,
            camera_id=event.camera_id,
            location_id=event.location_id,
            person_id=event.person_id,
            description=description,
        )
        session.add(alert)
        from sentinel.core.logging_setup import log_alert
        log_alert(description, event.camera_id)

    async def _on_summary(self, session: AsyncSession, event: SentinelEvent) -> None:
        summary = NarrativeSummary(
            tenant_id=event.tenant_id,
            location_id=event.location_id,
            narrative=str(event.payload.get("narrative", "")),
            occupancy=int(event.payload.get("occupancy", 0)),
            mood=str(event.payload.get("mood", "нейтральное")),
            alerts_json=json.dumps(event.payload.get("alerts", []), ensure_ascii=False),
            insights_json=json.dumps(event.payload.get("insights", []), ensure_ascii=False),
        )
        session.add(summary)
        from sentinel.core.logging_setup import log_llm_summary
        log_llm_summary(summary.narrative, summary.occupancy, summary.mood)
