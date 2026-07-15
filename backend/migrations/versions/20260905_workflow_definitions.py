"""Workflow Builder Phase 1 — versioned workflow definitions and executions."""
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

revision = "20260905_workflow_definitions"
down_revision = "20260904_automation_scheduler"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenants"):
        return

    if not table_exists("tenant_workflows"):
        op.create_table(
            "tenant_workflows",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("key", sa.String(120), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("active_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("draft_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("draft_revision", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("trigger_event", sa.String(80), nullable=True),
            sa.Column(
                "failure_policy",
                sa.String(40),
                nullable=False,
                server_default="stop_on_failure",
            ),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
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
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_workflows_tenant_key"),
        )

    create_index_if_missing(
        "ix_tenant_workflows_tenant_id",
        "tenant_workflows",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflows_tenant_status_updated",
        "tenant_workflows",
        ["tenant_id", "status", "updated_at"],
    )
    create_index_if_missing(
        "ix_tenant_workflows_tenant_trigger",
        "tenant_workflows",
        ["tenant_id", "trigger_event"],
    )
    create_index_if_missing(
        "ix_tenant_workflows_status",
        "tenant_workflows",
        ["status"],
    )

    if not table_exists("tenant_workflow_versions"):
        op.create_table(
            "tenant_workflow_versions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workflow_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_workflows.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version_number", sa.Integer(), nullable=False),
            sa.Column("state", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("definition", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("definition_hash", sa.String(64), nullable=True),
            sa.Column(
                "validation_status",
                sa.String(20),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("validation_errors", JSONB(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "workflow_id",
                "version_number",
                name="uq_tenant_workflow_versions_workflow_number",
            ),
        )

    create_index_if_missing(
        "ix_tenant_workflow_versions_tenant_id",
        "tenant_workflow_versions",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_versions_workflow_id",
        "tenant_workflow_versions",
        ["workflow_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_versions_state",
        "tenant_workflow_versions",
        ["state"],
    )

    # Add deferred FKs from workflows → versions (circular dependency).
    bind = op.get_bind()
    existing_fks = {
        row[0]
        for row in bind.execute(
            sa.text(
                "SELECT constraint_name FROM information_schema.table_constraints "
                "WHERE table_name = 'tenant_workflows' AND constraint_type = 'FOREIGN KEY'"
            )
        )
    }
    if "fk_tenant_workflows_active_version" not in existing_fks and table_exists("tenant_workflow_versions"):
        op.create_foreign_key(
            "fk_tenant_workflows_active_version",
            "tenant_workflows",
            "tenant_workflow_versions",
            ["active_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "fk_tenant_workflows_draft_version" not in existing_fks and table_exists("tenant_workflow_versions"):
        op.create_foreign_key(
            "fk_tenant_workflows_draft_version",
            "tenant_workflows",
            "tenant_workflow_versions",
            ["draft_version_id"],
            ["id"],
            ondelete="SET NULL",
        )

    if not table_exists("tenant_workflow_executions"):
        op.create_table(
            "tenant_workflow_executions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workflow_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_workflows.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workflow_version_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_workflow_versions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("platform_event_id", UUID(as_uuid=True), nullable=True),
            sa.Column("execution_kind", sa.String(20), nullable=False, server_default="event"),
            sa.Column("deduplication_key", sa.String(200), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("trigger_event", sa.String(80), nullable=False),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("matched_conditions", JSONB(), nullable=True),
            sa.Column("current_step_id", sa.String(80), nullable=True),
            sa.Column("input_summary", JSONB(), nullable=True),
            sa.Column("result_summary", JSONB(), nullable=True),
            sa.Column("error_code", sa.String(60), nullable=True),
            sa.Column("error_category", sa.String(40), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "workflow_id",
                "deduplication_key",
                name="uq_tenant_workflow_executions_dedup",
            ),
        )

    create_index_if_missing(
        "ix_tenant_workflow_executions_tenant_id",
        "tenant_workflow_executions",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_executions_workflow_created",
        "tenant_workflow_executions",
        ["workflow_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_executions_tenant_status_created",
        "tenant_workflow_executions",
        ["tenant_id", "status", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_executions_platform_event_id",
        "tenant_workflow_executions",
        ["platform_event_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_executions_workflow_version_id",
        "tenant_workflow_executions",
        ["workflow_version_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_executions_status",
        "tenant_workflow_executions",
        ["status"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_executions_created_at",
        "tenant_workflow_executions",
        ["created_at"],
    )

    if not table_exists("tenant_workflow_step_executions"):
        op.create_table(
            "tenant_workflow_step_executions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "workflow_execution_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_workflow_executions.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("step_id", sa.String(80), nullable=False),
            sa.Column("step_type", sa.String(40), nullable=False),
            sa.Column("action_type", sa.String(60), nullable=True),
            sa.Column("step_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("duration_ms", sa.Integer(), nullable=True),
            sa.Column("input_summary", JSONB(), nullable=True),
            sa.Column("result_summary", JSONB(), nullable=True),
            sa.Column("error_code", sa.String(60), nullable=True),
            sa.Column("error_category", sa.String(40), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "workflow_execution_id",
                "step_id",
                name="uq_tenant_workflow_step_executions_exec_step",
            ),
        )

    create_index_if_missing(
        "ix_tenant_workflow_step_executions_tenant_id",
        "tenant_workflow_step_executions",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_step_executions_execution_id",
        "tenant_workflow_step_executions",
        ["workflow_execution_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_step_executions_exec_step",
        "tenant_workflow_step_executions",
        ["workflow_execution_id", "step_id"],
    )
    create_index_if_missing(
        "ix_tenant_workflow_step_executions_status",
        "tenant_workflow_step_executions",
        ["status"],
    )


def downgrade() -> None:
    drop_index_if_exists("ix_tenant_workflow_step_executions_status", "tenant_workflow_step_executions")
    drop_index_if_exists("ix_tenant_workflow_step_executions_exec_step", "tenant_workflow_step_executions")
    drop_index_if_exists("ix_tenant_workflow_step_executions_execution_id", "tenant_workflow_step_executions")
    drop_index_if_exists("ix_tenant_workflow_step_executions_tenant_id", "tenant_workflow_step_executions")
    drop_table_if_exists("tenant_workflow_step_executions")

    drop_index_if_exists("ix_tenant_workflow_executions_created_at", "tenant_workflow_executions")
    drop_index_if_exists("ix_tenant_workflow_executions_status", "tenant_workflow_executions")
    drop_index_if_exists("ix_tenant_workflow_executions_workflow_version_id", "tenant_workflow_executions")
    drop_index_if_exists("ix_tenant_workflow_executions_platform_event_id", "tenant_workflow_executions")
    drop_index_if_exists("ix_tenant_workflow_executions_tenant_status_created", "tenant_workflow_executions")
    drop_index_if_exists("ix_tenant_workflow_executions_workflow_created", "tenant_workflow_executions")
    drop_index_if_exists("ix_tenant_workflow_executions_tenant_id", "tenant_workflow_executions")
    drop_table_if_exists("tenant_workflow_executions")

    if table_exists("tenant_workflows"):
        bind = op.get_bind()
        existing_fks = {
            row[0]
            for row in bind.execute(
                sa.text(
                    "SELECT constraint_name FROM information_schema.table_constraints "
                    "WHERE table_name = 'tenant_workflows' AND constraint_type = 'FOREIGN KEY'"
                )
            )
        }
        if "fk_tenant_workflows_draft_version" in existing_fks:
            op.drop_constraint("fk_tenant_workflows_draft_version", "tenant_workflows", type_="foreignkey")
        if "fk_tenant_workflows_active_version" in existing_fks:
            op.drop_constraint("fk_tenant_workflows_active_version", "tenant_workflows", type_="foreignkey")

    drop_index_if_exists("ix_tenant_workflow_versions_state", "tenant_workflow_versions")
    drop_index_if_exists("ix_tenant_workflow_versions_workflow_id", "tenant_workflow_versions")
    drop_index_if_exists("ix_tenant_workflow_versions_tenant_id", "tenant_workflow_versions")
    drop_table_if_exists("tenant_workflow_versions")

    drop_index_if_exists("ix_tenant_workflows_status", "tenant_workflows")
    drop_index_if_exists("ix_tenant_workflows_tenant_trigger", "tenant_workflows")
    drop_index_if_exists("ix_tenant_workflows_tenant_status_updated", "tenant_workflows")
    drop_index_if_exists("ix_tenant_workflows_tenant_id", "tenant_workflows")
    drop_table_if_exists("tenant_workflows")
