"""Zones table + telegram_chat_id on tenants.

Revision ID: 003_zones
Revises: 002_multi_tenant
Create Date: 2026-03-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_zones"
down_revision: Union[str, None] = "002_multi_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "zones",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("camera_id", sa.String(64), nullable=False, index=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("zone_type", sa.String(20), server_default="custom", index=True),
        sa.Column("polygon", sa.Text, nullable=False),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("staff_required", sa.Boolean, server_default=sa.text("false")),
        sa.Column("max_absence_seconds", sa.Integer, server_default=sa.text("300")),
        sa.Column("max_wait_seconds", sa.Integer, server_default=sa.text("120")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.add_column(
        "tenants",
        sa.Column("telegram_chat_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenants", "telegram_chat_id")
    op.drop_table("zones")
