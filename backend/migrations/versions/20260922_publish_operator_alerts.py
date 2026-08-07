"""Add publish_operator_alerts for deduplicated publishing failure notifications."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    index_exists,
    table_exists,
)

revision = "20260922_publish_operator_alerts"
down_revision = "20260921_publish_attempt_resilience"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "publish_operator_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dedupe_key", sa.String(length=320), nullable=False),
        sa.Column("alert_type", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("severity", sa.String(length=20), nullable=False, server_default="warning"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("publish_attempts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("platform", sa.String(length=20), nullable=True),
        sa.Column("account_name", sa.String(length=255), nullable=True),
        sa.Column("company_name", sa.String(length=255), nullable=True),
        sa.Column("attempt_status", sa.String(length=40), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("first_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolve_note", sa.Text(), nullable=True),
        sa.Column("resolved_by_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("action_url", sa.String(length=500), nullable=True),
        sa.Column("context", postgresql.JSONB(), nullable=True),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_delivery_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_delivery_channel", sa.String(length=40), nullable=True),
        sa.Column("last_delivery_error", sa.String(length=480), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    if table_exists("publish_operator_alerts"):
        create_index_if_missing(
            "ix_publish_operator_alerts_tenant_id",
            "publish_operator_alerts",
            ["tenant_id"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_alert_type",
            "publish_operator_alerts",
            ["alert_type"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_state",
            "publish_operator_alerts",
            ["state"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_severity",
            "publish_operator_alerts",
            ["severity"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_content_id",
            "publish_operator_alerts",
            ["content_id"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_attempt_id",
            "publish_operator_alerts",
            ["attempt_id"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_tenant_state",
            "publish_operator_alerts",
            ["tenant_id", "state"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_tenant_severity",
            "publish_operator_alerts",
            ["tenant_id", "severity"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_tenant_platform",
            "publish_operator_alerts",
            ["tenant_id", "platform"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_tenant_client",
            "publish_operator_alerts",
            ["tenant_id", "client_id"],
        )
        create_index_if_missing(
            "ix_publish_operator_alerts_tenant_latest",
            "publish_operator_alerts",
            ["tenant_id", "latest_occurred_at"],
        )
        if not index_exists("publish_operator_alerts", "uq_publish_operator_alerts_open_dedupe"):
            op.create_index(
                "uq_publish_operator_alerts_open_dedupe",
                "publish_operator_alerts",
                ["tenant_id", "dedupe_key"],
                unique=True,
                postgresql_where=sa.text("state IN ('open', 'acknowledged')"),
            )
        if not index_exists("publish_operator_alerts", "ix_publish_operator_alerts_open_destination"):
            op.create_index(
                "ix_publish_operator_alerts_open_destination",
                "publish_operator_alerts",
                ["tenant_id", "content_id", "platform", "account_id"],
                postgresql_where=sa.text("state IN ('open', 'acknowledged')"),
            )


def downgrade() -> None:
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_open_destination")
    drop_index_if_exists("publish_operator_alerts", "uq_publish_operator_alerts_open_dedupe")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_tenant_latest")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_tenant_client")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_tenant_platform")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_tenant_severity")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_tenant_state")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_attempt_id")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_content_id")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_severity")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_state")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_alert_type")
    drop_index_if_exists("publish_operator_alerts", "ix_publish_operator_alerts_tenant_id")
    drop_table_if_exists("publish_operator_alerts")
