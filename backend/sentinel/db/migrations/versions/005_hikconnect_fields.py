"""Add ezviz_serial and ezviz_channel to cameras table for Hik-Connect integration.

Revision ID: 005
Revises: 004
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("ezviz_serial", sa.String(64), nullable=True))
    op.add_column("cameras", sa.Column("ezviz_channel", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("cameras", "ezviz_channel")
    op.drop_column("cameras", "ezviz_serial")
