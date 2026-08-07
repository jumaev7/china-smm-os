"""Tenant Telegram settings and durable outbox for publish operator alert delivery."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from migrations.helpers import (
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    table_exists,
)

revision = "20260923_publish_alert_telegram_delivery"
down_revision = "20260922_publish_operator_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "tenant_publish_alert_telegram_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recipient_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("recipient_label", sa.String(length=120), nullable=True),
        sa.Column("allowed_chat_ids", postgresql.JSONB(), nullable=True),
        sa.Column("severity_threshold", sa.String(length=20), nullable=False, server_default="warning"),
        sa.Column("alert_types", postgresql.JSONB(), nullable=True),
        sa.Column("quiet_hours_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("quiet_hours_start", sa.Time(), nullable=True),
        sa.Column("quiet_hours_end", sa.Time(), nullable=True),
        sa.Column("quiet_hours_timezone", sa.String(length=64), nullable=True),
        sa.Column("recovery_messages_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", name="uq_tenant_publish_alert_telegram_settings_tenant"),
    )

    if table_exists("tenant_publish_alert_telegram_settings"):
        create_index_if_missing(
            "ix_tenant_publish_alert_telegram_settings_tenant_id",
            "tenant_publish_alert_telegram_settings",
            ["tenant_id"],
        )
        create_index_if_missing(
            "ix_tenant_publish_alert_tg_settings_enabled",
            "tenant_publish_alert_telegram_settings",
            ["enabled"],
        )

    create_table_if_missing(
        "publish_alert_telegram_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "alert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("publish_operator_alerts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("dedupe_key", sa.String(length=420), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False, server_default="telegram"),
        sa.Column("message_kind", sa.String(length=20), nullable=False, server_default="alert"),
        sa.Column("alert_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("recipient_chat_id", sa.BigInteger(), nullable=False),
        sa.Column("recipient_label", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="8"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("failure_message", sa.String(length=480), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_publish_alert_tg_deliveries_dedupe"),
    )

    if table_exists("publish_alert_telegram_deliveries"):
        create_index_if_missing(
            "ix_publish_alert_telegram_deliveries_tenant_id",
            "publish_alert_telegram_deliveries",
            ["tenant_id"],
        )
        create_index_if_missing(
            "ix_publish_alert_telegram_deliveries_status",
            "publish_alert_telegram_deliveries",
            ["status"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_deliveries_tenant_status",
            "publish_alert_telegram_deliveries",
            ["tenant_id", "status"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_deliveries_alert",
            "publish_alert_telegram_deliveries",
            ["alert_id"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_deliveries_due",
            "publish_alert_telegram_deliveries",
            ["status", "next_attempt_at", "created_at"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_deliveries_lease",
            "publish_alert_telegram_deliveries",
            ["lease_expires_at"],
        )
        # Partial stale-sending index via raw SQL for idempotency
        op.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS ix_publish_alert_tg_deliveries_sending_stale
                ON publish_alert_telegram_deliveries (status, lease_expires_at)
                WHERE status = 'sending'
                """
            )
        )


def downgrade() -> None:
    if table_exists("publish_alert_telegram_deliveries"):
        op.execute(sa.text("DROP INDEX IF EXISTS ix_publish_alert_tg_deliveries_sending_stale"))
        drop_index_if_exists("ix_publish_alert_tg_deliveries_lease", "publish_alert_telegram_deliveries")
        drop_index_if_exists("ix_publish_alert_tg_deliveries_due", "publish_alert_telegram_deliveries")
        drop_index_if_exists("ix_publish_alert_tg_deliveries_alert", "publish_alert_telegram_deliveries")
        drop_index_if_exists(
            "ix_publish_alert_tg_deliveries_tenant_status",
            "publish_alert_telegram_deliveries",
        )
        drop_index_if_exists(
            "ix_publish_alert_telegram_deliveries_status",
            "publish_alert_telegram_deliveries",
        )
        drop_index_if_exists(
            "ix_publish_alert_telegram_deliveries_tenant_id",
            "publish_alert_telegram_deliveries",
        )
        drop_table_if_exists("publish_alert_telegram_deliveries")

    if table_exists("tenant_publish_alert_telegram_settings"):
        drop_index_if_exists(
            "ix_tenant_publish_alert_tg_settings_enabled",
            "tenant_publish_alert_telegram_settings",
        )
        drop_index_if_exists(
            "ix_tenant_publish_alert_telegram_settings_tenant_id",
            "tenant_publish_alert_telegram_settings",
        )
        drop_table_if_exists("tenant_publish_alert_telegram_settings")
