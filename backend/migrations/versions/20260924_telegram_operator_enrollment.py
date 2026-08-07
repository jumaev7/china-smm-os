"""Secure Telegram operator-alert recipient self-enrollment.

Revision ID: 20260924_telegram_operator_enrollment
Revises: 20260923_publish_alert_telegram_delivery
"""
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

revision = "20260924_telegram_operator_enrollment"
down_revision = "20260923_publish_alert_telegram_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "publish_alert_telegram_enrollments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by_admin_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "purpose",
            sa.String(length=64),
            nullable=False,
            server_default="operator_alert_enrollment",
        ),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending_start"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_chat_id", sa.BigInteger(), nullable=True),
        sa.Column("telegram_chat_id_masked", sa.String(length=32), nullable=True),
        sa.Column("telegram_display_name", sa.String(length=120), nullable=True),
        sa.Column("telegram_username", sa.String(length=120), nullable=True),
        sa.Column("telegram_chat_type", sa.String(length=32), nullable=True),
        sa.Column("source_update_id", sa.BigInteger(), nullable=True),
        sa.Column("bot_username", sa.String(length=64), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rejection_reason_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_publish_alert_tg_enroll_token_hash"),
        sa.CheckConstraint(
            "status IN ("
            "'pending_start', 'candidate_received', 'confirmed', "
            "'expired', 'revoked', 'rejected'"
            ")",
            name="ck_publish_alert_tg_enroll_status",
        ),
    )

    if table_exists("publish_alert_telegram_enrollments"):
        create_index_if_missing(
            "ix_publish_alert_tg_enroll_tenant_id",
            "publish_alert_telegram_enrollments",
            ["tenant_id"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_enroll_status",
            "publish_alert_telegram_enrollments",
            ["status"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_enroll_expires_at",
            "publish_alert_telegram_enrollments",
            ["expires_at"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_enroll_tenant_status",
            "publish_alert_telegram_enrollments",
            ["tenant_id", "status"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_enroll_creator_status",
            "publish_alert_telegram_enrollments",
            ["tenant_id", "created_by_admin_id", "status"],
        )
        create_index_if_missing(
            "ix_publish_alert_tg_enroll_source_update",
            "publish_alert_telegram_enrollments",
            ["source_update_id"],
            unique=True,
        )
        # Partial unique: at most one active unfinished enrollment per tenant+creator
        op.execute(
            sa.text(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS
                uq_publish_alert_tg_enroll_active_creator
                ON publish_alert_telegram_enrollments (tenant_id, created_by_admin_id)
                WHERE status IN ('pending_start', 'candidate_received')
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE INDEX IF NOT EXISTS
                ix_publish_alert_tg_enroll_cleanup
                ON publish_alert_telegram_enrollments (status, expires_at)
                WHERE status IN ('pending_start', 'candidate_received')
                """
            )
        )


def downgrade() -> None:
    if table_exists("publish_alert_telegram_enrollments"):
        op.execute(sa.text("DROP INDEX IF EXISTS uq_publish_alert_tg_enroll_active_creator"))
        op.execute(sa.text("DROP INDEX IF EXISTS ix_publish_alert_tg_enroll_cleanup"))
        drop_index_if_exists(
            "ix_publish_alert_tg_enroll_source_update",
            "publish_alert_telegram_enrollments",
        )
        drop_index_if_exists(
            "ix_publish_alert_tg_enroll_creator_status",
            "publish_alert_telegram_enrollments",
        )
        drop_index_if_exists(
            "ix_publish_alert_tg_enroll_tenant_status",
            "publish_alert_telegram_enrollments",
        )
        drop_index_if_exists(
            "ix_publish_alert_tg_enroll_expires_at",
            "publish_alert_telegram_enrollments",
        )
        drop_index_if_exists(
            "ix_publish_alert_tg_enroll_status",
            "publish_alert_telegram_enrollments",
        )
        drop_index_if_exists(
            "ix_publish_alert_tg_enroll_tenant_id",
            "publish_alert_telegram_enrollments",
        )
        drop_table_if_exists("publish_alert_telegram_enrollments")
