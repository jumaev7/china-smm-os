"""Platform event bus tables — activity, notifications, automation triggers."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260831_platform_event_bus"
down_revision = "20260830_customer_success_journey"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "tenant_activity_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(20), nullable=True),
        sa.Column("actor_id", UUID(as_uuid=True), nullable=True),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="recorded"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing("ix_tenant_activity_events_tenant_id", "tenant_activity_events", ["tenant_id"])
    create_index_if_missing("ix_tenant_activity_events_event_type", "tenant_activity_events", ["event_type"])
    create_index_if_missing("ix_tenant_activity_events_occurred_at", "tenant_activity_events", ["occurred_at"])

    create_table_if_missing(
        "tenant_event_notifications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("severity", sa.String(20), nullable=False, server_default="info"),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="unread"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_tenant_event_notifications_tenant_id",
        "tenant_event_notifications",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_event_notifications_status",
        "tenant_event_notifications",
        ["status"],
    )

    create_table_if_missing(
        "tenant_automation_triggers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("trigger_key", sa.String(120), nullable=False),
        sa.Column("workflow_hint", sa.String(60), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_tenant_automation_triggers_tenant_id",
        "tenant_automation_triggers",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_automation_triggers_status",
        "tenant_automation_triggers",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_automation_triggers_status", table_name="tenant_automation_triggers")
    op.drop_index("ix_tenant_automation_triggers_tenant_id", table_name="tenant_automation_triggers")
    op.drop_table("tenant_automation_triggers")
    op.drop_index("ix_tenant_event_notifications_status", table_name="tenant_event_notifications")
    op.drop_index("ix_tenant_event_notifications_tenant_id", table_name="tenant_event_notifications")
    op.drop_table("tenant_event_notifications")
    op.drop_index("ix_tenant_activity_events_occurred_at", table_name="tenant_activity_events")
    op.drop_index("ix_tenant_activity_events_event_type", table_name="tenant_activity_events")
    op.drop_index("ix_tenant_activity_events_tenant_id", table_name="tenant_activity_events")
    op.drop_table("tenant_activity_events")
