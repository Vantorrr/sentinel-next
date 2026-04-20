"""Persisted camera configuration — survives server restarts."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from sentinel.db.base import Base


class CameraRecord(Base):
    __tablename__ = "cameras"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    location_id: Mapped[str] = mapped_column(String(128), default="default")
    fps_inference: Mapped[int] = mapped_column(Integer, default=10)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )

    # Hik-Connect / EZVIZ cloud fields (null for RTSP-direct cameras)
    ezviz_serial: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, default=None)
    ezviz_channel: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
