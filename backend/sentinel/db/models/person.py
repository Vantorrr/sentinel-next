"""Person & Visit ORM models."""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sentinel.db.base import Base


class PersonCategory(str, enum.Enum):
    NEW = "new"
    REGULAR = "regular"
    VIP = "vip"
    STAFF = "staff"
    BLOCKLIST = "blocklist"


class Person(Base):
    __tablename__ = "persons"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
        server_default="legacy",
    )
    name: Mapped[str] = mapped_column(String(255), default="Unknown")
    category: Mapped[PersonCategory] = mapped_column(
        String(20), default=PersonCategory.NEW, index=True
    )
    phone: Mapped[str | None] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)
    visit_count: Mapped[int] = mapped_column(Integer, default=0)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())
    avatar_path: Mapped[str | None] = mapped_column(String(512))

    visits: Mapped[list["Visit"]] = relationship(back_populates="person", lazy="select")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="person", lazy="select")


class Visit(Base):
    __tablename__ = "visits"
    __table_args__ = (
        Index("ix_visits_person_entered", "person_id", "entered_at"),
        Index("ix_visits_location_entered", "location_id", "entered_at"),
        Index("ix_visits_tenant", "tenant_id", "entered_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
        server_default="legacy",
    )
    person_id: Mapped[str | None] = mapped_column(ForeignKey("persons.id"), index=True)
    location_id: Mapped[str] = mapped_column(String(64), index=True)
    camera_id: Mapped[str] = mapped_column(String(64))
    track_id: Mapped[str] = mapped_column(String(64))
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dwell_seconds: Mapped[float | None] = mapped_column(Float)
    snapshot_path: Mapped[str | None] = mapped_column(String(512))

    person: Mapped["Person | None"] = relationship(back_populates="visits")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
        server_default="legacy",
    )
    type: Mapped[str] = mapped_column(String(64), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="medium", index=True)
    camera_id: Mapped[str] = mapped_column(String(64))
    location_id: Mapped[str] = mapped_column(String(64))
    person_id: Mapped[str | None] = mapped_column(ForeignKey("persons.id"))
    description: Mapped[str] = mapped_column(Text)
    acknowledged: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)

    person: Mapped["Person | None"] = relationship(back_populates="alerts")


class NarrativeSummary(Base):
    """LLM-generated summaries stored for history & search."""
    __tablename__ = "narrative_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
        server_default="legacy",
    )
    location_id: Mapped[str] = mapped_column(String(64), index=True)
    narrative: Mapped[str] = mapped_column(Text)
    occupancy: Mapped[int] = mapped_column(Integer, default=0)
    mood: Mapped[str] = mapped_column(String(32))
    alerts_json: Mapped[str] = mapped_column(Text, default="[]")
    insights_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
