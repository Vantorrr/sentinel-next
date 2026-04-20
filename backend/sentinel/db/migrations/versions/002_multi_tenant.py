"""Multi-tenant: tenants, users, agents, push_subscriptions + tenant_id on existing tables.

Revision ID: 002_multi_tenant
Revises: 001_initial
Create Date: 2026-03-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_multi_tenant"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Tenants ────────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), unique=True, nullable=False),
        sa.Column("api_key", sa.String(128), unique=True, nullable=False),
        sa.Column("plan", sa.String(20), nullable=False, server_default="free"),
        sa.Column("max_cameras", sa.Integer, nullable=False, server_default="4"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("contact_phone", sa.String(20), nullable=True),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_index("ix_tenants_api_key", "tenants", ["api_key"], unique=True)
    op.create_index("ix_tenants_is_active", "tenants", ["is_active"])

    # Seed a legacy tenant for backward compatibility
    op.execute(
        "INSERT INTO tenants (id, name, slug, api_key, plan, max_cameras) "
        "VALUES ('legacy', 'Legacy', 'legacy', 'sk-legacy-placeholder', 'enterprise', 128)"
    )

    # ── Users ──────────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False, server_default=""),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_login", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_tenant_role", "users", ["tenant_id", "role"])

    # ── Agents ─────────────────────────────────────────────────────────────────
    op.create_table(
        "agents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("hostname", sa.String(255), nullable=False, server_default=""),
        sa.Column("ip_address", sa.String(45), nullable=False, server_default=""),
        sa.Column("cameras_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cpu_usage", sa.Float, nullable=False, server_default="0"),
        sa.Column("memory_mb", sa.Float, nullable=False, server_default="0"),
        sa.Column("fps", sa.Float, nullable=False, server_default="0"),
        sa.Column("version", sa.String(32), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default="offline"),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_agents_tenant_id", "agents", ["tenant_id"])

    # ── Push subscriptions (PWA) ───────────────────────────────────────────────
    op.create_table(
        "push_subscriptions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint", sa.Text, nullable=False),
        sa.Column("p256dh", sa.String(255), nullable=False),
        sa.Column("auth", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_push_subscriptions_user_id", "push_subscriptions", ["user_id"])

    # ── Add tenant_id to existing tables ───────────────────────────────────────
    for table in ("persons", "visits", "alerts", "narrative_summaries"):
        op.add_column(table, sa.Column(
            "tenant_id", sa.String(36),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False, server_default="legacy",
        ))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

    # Composite indexes for tenant-scoped queries
    op.create_index("ix_visits_tenant_entered", "visits", ["tenant_id", "entered_at"])
    op.create_index("ix_alerts_tenant_created", "alerts", ["tenant_id", "created_at"])
    op.create_index("ix_summaries_tenant_created", "narrative_summaries", ["tenant_id", "created_at"])


def downgrade() -> None:
    # Drop composite indexes first (before dropping the column they depend on)
    op.drop_index("ix_visits_tenant_entered", "visits")
    op.drop_index("ix_alerts_tenant_created", "alerts")
    op.drop_index("ix_summaries_tenant_created", "narrative_summaries")

    for table in ("persons", "visits", "alerts", "narrative_summaries"):
        op.drop_index(f"ix_{table}_tenant_id", table)
        op.drop_column(table, "tenant_id")

    op.drop_table("push_subscriptions")
    op.drop_table("agents")
    op.drop_table("users")
    op.drop_table("tenants")
