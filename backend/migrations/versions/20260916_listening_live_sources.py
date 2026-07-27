"""Social Listening Phase 3 — governed live read-only source columns.

Adds binding/health/lock/checkpoint fields on tenant_listening_sources and
widens ingestion cursors for Meta pagination state. Tokens remain exclusively
on publishing_accounts.

down_revision = "20260915_listening_market_intelligence"
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import column_exists, table_exists

revision = "20260916_listening_live_sources"
down_revision = "20260915_listening_market_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenant_listening_sources"):
        return

    cols = [
        (
            "integration_id",
            sa.Column(
                "integration_id",
                UUID(as_uuid=True),
                sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
                nullable=True,
            ),
        ),
        ("provider_resource_ref", sa.Column("provider_resource_ref", sa.String(255), nullable=True)),
        (
            "health_status",
            sa.Column("health_status", sa.String(40), nullable=False, server_default="unknown"),
        ),
        ("last_failure_at", sa.Column("last_failure_at", sa.DateTime(timezone=True), nullable=True)),
        ("last_failure_code", sa.Column("last_failure_code", sa.String(80), nullable=True)),
        ("last_failure_summary", sa.Column("last_failure_summary", sa.String(500), nullable=True)),
        ("last_checkpoint", sa.Column("last_checkpoint", sa.String(1000), nullable=True)),
        ("poll_interval_seconds", sa.Column("poll_interval_seconds", sa.Integer(), nullable=True)),
        (
            "provider_capability_version",
            sa.Column("provider_capability_version", sa.String(40), nullable=True),
        ),
        ("enabled_capabilities_json", sa.Column("enabled_capabilities_json", JSONB(), nullable=True)),
        ("lock_owner", sa.Column("lock_owner", sa.String(120), nullable=True)),
        ("lock_expires_at", sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True)),
    ]
    for name, column in cols:
        if not column_exists("tenant_listening_sources", name):
            op.add_column("tenant_listening_sources", column)

    if table_exists("tenant_listening_ingestion_runs"):
        # Widen cursor columns for JSON checkpoint payloads.
        if column_exists("tenant_listening_ingestion_runs", "cursor_before"):
            op.alter_column(
                "tenant_listening_ingestion_runs",
                "cursor_before",
                existing_type=sa.String(255),
                type_=sa.String(1000),
                existing_nullable=True,
            )
        if column_exists("tenant_listening_ingestion_runs", "cursor_after"):
            op.alter_column(
                "tenant_listening_ingestion_runs",
                "cursor_after",
                existing_type=sa.String(255),
                type_=sa.String(1000),
                existing_nullable=True,
            )


def downgrade() -> None:
    if not table_exists("tenant_listening_sources"):
        return
    for name in (
        "lock_expires_at",
        "lock_owner",
        "enabled_capabilities_json",
        "provider_capability_version",
        "poll_interval_seconds",
        "last_checkpoint",
        "last_failure_summary",
        "last_failure_code",
        "last_failure_at",
        "health_status",
        "provider_resource_ref",
        "integration_id",
    ):
        if column_exists("tenant_listening_sources", name):
            op.drop_column("tenant_listening_sources", name)
