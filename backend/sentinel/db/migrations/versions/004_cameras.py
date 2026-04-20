"""Persistent camera configuration table.

Revision ID: 004_cameras
Revises: 003_zones
Create Date: 2026-03-23
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_cameras"
down_revision: Union[str, None] = "003_zones"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cameras",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column(
            "tenant_id",
            sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("name", sa.String(255), server_default=""),
        sa.Column("location_id", sa.String(128), server_default="default"),
        sa.Column("fps_inference", sa.Integer, server_default=sa.text("10")),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("cameras")
