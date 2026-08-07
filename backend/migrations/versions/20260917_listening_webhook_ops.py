"""Social Listening Phase 4 - durable webhook operations inbox."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    create_index_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    table_exists,
)

revision = "20260917_listening_webhook_ops"
down_revision = "20260916_listening_live_sources"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenant_listening_sources"):
        return
    if not table_exists("tenant_listening_webhook_events"):
        op.create_table(
            "tenant_listening_webhook_events",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_sources.id", ondelete="CASCADE"), nullable=False),
            sa.Column("event_key", sa.String(64), nullable=False),
            sa.Column("provider_object_ref", sa.String(255), nullable=False),
            sa.Column("provider_field", sa.String(80), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error_code", sa.String(80), nullable=True),
            sa.Column("payload_summary_json", JSONB(), nullable=True),
            sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("source_id", "event_key", name="uq_listening_webhook_source_event"),
        )
    create_index_if_missing("ix_listening_webhook_events_status_due", "tenant_listening_webhook_events", ["status", "next_attempt_at"])
    create_index_if_missing("ix_listening_webhook_events_tenant_created", "tenant_listening_webhook_events", ["tenant_id", "created_at"])


def downgrade() -> None:
    drop_index_if_exists("ix_listening_webhook_events_tenant_created", table_name="tenant_listening_webhook_events")
    drop_index_if_exists("ix_listening_webhook_events_status_due", table_name="tenant_listening_webhook_events")
    drop_table_if_exists("tenant_listening_webhook_events")
