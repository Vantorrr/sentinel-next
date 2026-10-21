"""Async DB query helpers — all queries scoped by tenant_id.

When tenant_id == "__all__" (superadmin), the tenant filter is skipped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.db.models.person import Alert, NarrativeSummary, Person, Visit

SUPERADMIN_TENANT = "__all__"


async def get_visits(
    session: AsyncSession,
    tenant_id: str,
    start_iso: str,
    end_iso: str,
    category: str = "all",
    location_id: str | None = None,
) -> list[dict[str, Any]]:
    start = datetime.fromisoformat(start_iso)
    end = datetime.fromisoformat(end_iso)

    stmt = (
        select(Visit, Person)
        .outerjoin(Person, Visit.person_id == Person.id)
        .where(Visit.entered_at >= start, Visit.entered_at <= end)
    )
    if tenant_id != SUPERADMIN_TENANT:
        stmt = stmt.where(Visit.tenant_id == tenant_id)
    if location_id:
        stmt = stmt.where(Visit.location_id == location_id)
    if category != "all":
        stmt = stmt.where(Person.category == category)

    rows = await session.execute(stmt)
    return [
        {
            "visit_id": v.id,
            "person": {
                "id": p.id if p else None,
                "name": p.name if p else "Unknown",
                "category": p.category if p else "new",
                "visit_count": p.visit_count if p else 0,
            },
            "entered_at": v.entered_at.isoformat(),
            "dwell_seconds": v.dwell_seconds,
            "location_id": v.location_id,
        }
        for v, p in rows
    ]


async def get_alerts(
    session: AsyncSession,
    tenant_id: str,
    start_iso: str,
    severity: str = "all",
) -> list[dict[str, Any]]:
    # '+' in query strings is often decoded as space — restore timezone offset
    start = datetime.fromisoformat(start_iso.replace(" ", "+"))
    stmt = select(Alert).where(Alert.created_at >= start)
    if tenant_id != SUPERADMIN_TENANT:
        stmt = stmt.where(Alert.tenant_id == tenant_id)
    if severity != "all":
        stmt = stmt.where(Alert.severity == severity)
    stmt = stmt.order_by(Alert.created_at.desc()).limit(50)

    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": a.id,
            "type": a.type,
            "severity": a.severity,
            "description": a.description,
            "camera_id": a.camera_id,
            "acknowledged": a.acknowledged,
            "created_at": a.created_at.isoformat(),
        }
        for a in rows
    ]


async def get_occupancy_by_hour(
    session: AsyncSession,
    tenant_id: str,
    date: str,
    location_id: str | None = None,
) -> list[dict[str, Any]]:
    day = datetime.fromisoformat(date)
    hour_trunc = func.date_trunc(literal_column("'hour'"), Visit.entered_at)
    stmt = (
        select(
            hour_trunc.label("hour"),
            func.count().label("visits"),
        )
        .where(func.date(Visit.entered_at) == day.date())
        .group_by(hour_trunc)
        .order_by(hour_trunc)
    )
    if tenant_id != SUPERADMIN_TENANT:
        stmt = stmt.where(Visit.tenant_id == tenant_id)
    if location_id:
        stmt = stmt.where(Visit.location_id == location_id)

    rows = (await session.execute(stmt)).all()
    return [{"hour": str(r.hour), "visits": r.visits} for r in rows]


async def get_latest_summaries(
    session: AsyncSession,
    tenant_id: str,
    location_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    stmt = select(NarrativeSummary)
    if tenant_id != SUPERADMIN_TENANT:
        stmt = stmt.where(NarrativeSummary.tenant_id == tenant_id)
    if location_id:
        stmt = stmt.where(NarrativeSummary.location_id == location_id)

    stmt = stmt.order_by(NarrativeSummary.created_at.desc()).limit(limit)
    rows = (await session.execute(stmt)).scalars().all()
    return [
        {
            "id": s.id,
            "narrative": s.narrative,
            "occupancy": s.occupancy,
            "mood": s.mood,
            "created_at": s.created_at.isoformat(),
        }
        for s in rows
    ]
