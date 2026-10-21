"""Analytics & reporting endpoints — tenant-scoped."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from sentinel.core.auth import TenantContext, get_current_tenant
from sentinel.db.base import get_db
from sentinel.db.queries.analytics import (
    get_alerts,
    get_latest_summaries,
    get_occupancy_by_hour,
    get_visits,
)

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/visits")
async def visits(
    start: str = Query(..., description="ISO datetime"),
    end: str = Query(..., description="ISO datetime"),
    category: str = "all",
    location_id: str | None = None,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await get_visits(db, tenant.tenant_id, start, end, category, location_id)


@router.get("/alerts")
async def alerts(
    start: str = Query(...),
    severity: str = "all",
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await get_alerts(db, tenant.tenant_id, start, severity)


@router.get("/occupancy")
async def occupancy(
    date: str = Query(..., description="YYYY-MM-DD"),
    location_id: str | None = None,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await get_occupancy_by_hour(db, tenant.tenant_id, date, location_id)


@router.get("/summaries")
async def summaries(
    location_id: str | None = None,
    limit: int = 20,
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    return await get_latest_summaries(db, tenant.tenant_id, location_id, limit)


@router.get("/redbook/remarks")
async def redbook_remarks(
    start: str = Query(..., description="ISO datetime"),
    tenant: TenantContext = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Замечания Красной книги за период (из alerts)."""
    alerts = await get_alerts(db, tenant.tenant_id, start, "all")
    redbook_types = {"staff.absent", "client.unattended", "zone.violation", "fraud.alert"}
    remarks = [a for a in alerts if a.get("type") in redbook_types]
    critical = [a for a in remarks if a.get("severity") == "high"]
    return {
        "total": len(remarks),
        "critical": len(critical),
        "score": max(0, 100 - len(critical) * 15 - (len(remarks) - len(critical)) * 5),
        "standard": "Красная книга Вай Тай",
        "remarks": remarks[:100],
        "note": "Оценка по таймерам зон (детерминировано). Поза «вай»/униформа — отдельно.",
    }
