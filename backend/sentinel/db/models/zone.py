"""Zone models — camera zones for spatial intelligence."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from sentinel.db.base import Base


class ZoneType(str, enum.Enum):
    RECEPTION = "reception"
    WAITING = "waiting"
    SERVICE = "service"
    ENTRANCE = "entrance"
    STAFF_ONLY = "staff_only"
    CUSTOM = "custom"


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    camera_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    zone_type: Mapped[ZoneType] = mapped_column(String(20), default=ZoneType.CUSTOM, index=True)
    polygon: Mapped[str] = mapped_column(Text, nullable=False)  # JSON [[x,y], ...]
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    staff_required: Mapped[bool] = mapped_column(Boolean, default=False)
    max_absence_seconds: Mapped[int] = mapped_column(Integer, default=300)
    max_wait_seconds: Mapped[int] = mapped_column(Integer, default=120)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
