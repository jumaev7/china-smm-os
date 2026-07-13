"""Automation Center — tenant flow definitions and execution history."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing, drop_index_if_exists, drop_table_if_exists

revision = "20260902_automation_center"
down_revision = "20260901_notification_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "tenant_automation_flows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(40), nullable=False),
        sa.Column("trigger_event", sa.String(80), nullable=False),
        sa.Column("action_type", sa.String(60), nullable=False),
        sa.Column("action_config", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="enabled"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_execution_status", sa.String(20), nullable=True),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_automation_flows_tenant_key"),
    )
    create_index_if_missing(
        "ix_tenant_automation_flows_tenant_status",
        "tenant_automation_flows",
        ["tenant_id", "status"],
    )
    create_index_if_missing(
        "ix_tenant_automation_flows_tenant_trigger",
        "tenant_automation_flows",
        ["tenant_id", "trigger_event"],
    )
    create_index_if_missing(
        "ix_tenant_automation_flows_tenant_updated",
        "tenant_automation_flows",
        ["tenant_id", "updated_at"],
    )

    create_table_if_missing(
        "tenant_automation_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "automation_flow_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenant_automation_flows.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_id", UUID(as_uuid=True), nullable=False),
        sa.Column("trigger_event", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("input_payload", JSONB(), nullable=True),
        sa.Column("result_payload", JSONB(), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_tenant_automation_executions_tenant_created",
        "tenant_automation_executions",
        ["tenant_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_automation_executions_tenant_status_created",
        "tenant_automation_executions",
        ["tenant_id", "status", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_automation_executions_flow_created",
        "tenant_automation_executions",
        ["automation_flow_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_automation_executions_event_id",
        "tenant_automation_executions",
        ["event_id"],
    )


def downgrade() -> None:
    drop_index_if_exists("ix_tenant_automation_executions_event_id", "tenant_automation_executions")
    drop_index_if_exists("ix_tenant_automation_executions_flow_created", "tenant_automation_executions")
    drop_index_if_exists(
        "ix_tenant_automation_executions_tenant_status_created",
        "tenant_automation_executions",
    )
    drop_index_if_exists(
        "ix_tenant_automation_executions_tenant_created",
        "tenant_automation_executions",
    )
    drop_table_if_exists("tenant_automation_executions")

    drop_index_if_exists("ix_tenant_automation_flows_tenant_updated", "tenant_automation_flows")
    drop_index_if_exists("ix_tenant_automation_flows_tenant_trigger", "tenant_automation_flows")
    drop_index_if_exists("ix_tenant_automation_flows_tenant_status", "tenant_automation_flows")
    drop_table_if_exists("tenant_automation_flows")
