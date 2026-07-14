"""Automation Scheduler Phase 1 — durable jobs table."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    create_index_if_missing,
    drop_index_if_exists,
    table_exists,
)

revision = "20260904_automation_scheduler"
down_revision = "20260903_automation_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenant_automation_flows"):
        return
    if table_exists("tenant_automation_jobs"):
        return

    op.create_table(
        "tenant_automation_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
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
        sa.Column(
            "execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenant_automation_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "root_execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenant_automation_executions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "job_kind",
            sa.String(40),
            nullable=False,
            server_default="automation_retry",
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="scheduled",
        ),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("deduplication_key", sa.String(180), nullable=False),
        sa.Column("lease_owner", sa.String(120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_recovery_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_category", sa.String(40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_payload", JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "deduplication_key",
            name="uq_tenant_automation_jobs_dedup",
        ),
        sa.CheckConstraint(
            "status IN ('scheduled','leased','running','succeeded','failed','dead_letter','cancelled')",
            name="ck_tenant_automation_jobs_status",
        ),
        sa.CheckConstraint(
            "job_kind IN ('automation_retry')",
            name="ck_tenant_automation_jobs_kind",
        ),
    )

    create_index_if_missing(
        "ix_tenant_automation_jobs_claim",
        "tenant_automation_jobs",
        ["status", "available_at", "priority"],
    )
    create_index_if_missing(
        "ix_tenant_automation_jobs_tenant_status_created",
        "tenant_automation_jobs",
        ["tenant_id", "status", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_automation_jobs_lease_expires",
        "tenant_automation_jobs",
        ["lease_expires_at"],
    )
    create_index_if_missing(
        "ix_tenant_automation_jobs_flow_created",
        "tenant_automation_jobs",
        ["automation_flow_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_automation_jobs_root_created",
        "tenant_automation_jobs",
        ["root_execution_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_automation_jobs_tenant_id",
        "tenant_automation_jobs",
        ["tenant_id"],
    )


def downgrade() -> None:
    if not table_exists("tenant_automation_jobs"):
        return

    for name in (
        "ix_tenant_automation_jobs_tenant_id",
        "ix_tenant_automation_jobs_root_created",
        "ix_tenant_automation_jobs_flow_created",
        "ix_tenant_automation_jobs_lease_expires",
        "ix_tenant_automation_jobs_tenant_status_created",
        "ix_tenant_automation_jobs_claim",
    ):
        drop_index_if_exists(name, "tenant_automation_jobs")

    op.drop_table("tenant_automation_jobs")
