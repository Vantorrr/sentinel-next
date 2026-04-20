"""Initial schema — persons, visits, alerts, narrative_summaries.

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, server_default="Unknown"),
        sa.Column("category", sa.String(20), nullable=False, server_default="new"),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("visit_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("first_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("avatar_path", sa.String(512), nullable=True),
    )
    op.create_index("ix_persons_category", "persons", ["category"])

    op.create_table(
        "visits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("location_id", sa.String(64), nullable=False),
        sa.Column("camera_id", sa.String(64), nullable=False),
        sa.Column("track_id", sa.String(64), nullable=False),
        sa.Column(
            "entered_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("left_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dwell_seconds", sa.Float, nullable=True),
        sa.Column("snapshot_path", sa.String(512), nullable=True),
    )
    op.create_index("ix_visits_person_id", "visits", ["person_id"])
    op.create_index("ix_visits_location_id", "visits", ["location_id"])
    op.create_index("ix_visits_entered_at", "visits", ["entered_at"])
    op.create_index("ix_visits_person_entered", "visits", ["person_id", "entered_at"])
    op.create_index("ix_visits_location_entered", "visits", ["location_id", "entered_at"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("camera_id", sa.String(64), nullable=False),
        sa.Column("location_id", sa.String(64), nullable=False),
        sa.Column("person_id", sa.String(36), sa.ForeignKey("persons.id"), nullable=True),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("acknowledged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_alerts_type", "alerts", ["type"])
    op.create_index("ix_alerts_severity", "alerts", ["severity"])
    op.create_index("ix_alerts_acknowledged", "alerts", ["acknowledged"])
    op.create_index("ix_alerts_created_at", "alerts", ["created_at"])

    op.create_table(
        "narrative_summaries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("location_id", sa.String(64), nullable=False),
        sa.Column("narrative", sa.Text, nullable=False),
        sa.Column("occupancy", sa.Integer, nullable=False, server_default="0"),
        sa.Column("mood", sa.String(32), nullable=False),
        sa.Column("alerts_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("insights_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index("ix_narrative_summaries_location_id", "narrative_summaries", ["location_id"])
    op.create_index("ix_narrative_summaries_created_at", "narrative_summaries", ["created_at"])


def downgrade() -> None:
    op.drop_table("narrative_summaries")
    op.drop_table("alerts")
    op.drop_table("visits")
    op.drop_table("persons")
