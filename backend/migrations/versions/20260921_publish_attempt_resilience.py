"""Add publish attempt resilience columns and claim index."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

from migrations.helpers import (
    add_column_if_missing,
    column_exists,
    drop_column_if_exists,
    drop_index_if_exists,
    index_exists,
)

revision = "20260921_publish_attempt_resilience"
down_revision = "20260920_auto_publish_after_client_approval"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "publish_attempts",
        sa.Column("idempotency_key", sa.String(length=220), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("publish_version", sa.String(length=64), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("failure_code", sa.String(length=80), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("failure_category", sa.String(length=40), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("retryable", sa.Boolean(), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("external_post_id", sa.String(length=255), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("external_post_url", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "publish_attempts",
        sa.Column("retry_after_seconds", sa.Integer(), nullable=True),
    )

    if column_exists("publish_attempts", "idempotency_key") and not index_exists(
        "publish_attempts", "ix_publish_attempts_idempotency_key"
    ):
        op.create_index(
            "ix_publish_attempts_idempotency_key",
            "publish_attempts",
            ["idempotency_key"],
        )

    if column_exists("publish_attempts", "next_retry_at") and not index_exists(
        "publish_attempts", "ix_publish_attempts_retry_claim"
    ):
        op.create_index(
            "ix_publish_attempts_retry_claim",
            "publish_attempts",
            ["status", "next_retry_at"],
        )

    # Only one active in-progress claim per destination key.
    if column_exists("publish_attempts", "idempotency_key") and not index_exists(
        "publish_attempts", "uq_publish_attempts_active_claim"
    ):
        op.execute(
            text(
                "CREATE UNIQUE INDEX uq_publish_attempts_active_claim "
                "ON publish_attempts (idempotency_key) "
                "WHERE status = 'in_progress' AND idempotency_key IS NOT NULL"
            )
        )


def downgrade() -> None:
    drop_index_if_exists("uq_publish_attempts_active_claim", "publish_attempts")
    drop_index_if_exists("ix_publish_attempts_retry_claim", "publish_attempts")
    drop_index_if_exists("ix_publish_attempts_idempotency_key", "publish_attempts")
    for column in (
        "retry_after_seconds",
        "lease_expires_at",
        "lease_owner",
        "external_post_url",
        "external_post_id",
        "finished_at",
        "started_at",
        "next_retry_at",
        "retryable",
        "failure_category",
        "failure_code",
        "attempt_number",
        "publish_version",
        "idempotency_key",
    ):
        drop_column_if_exists("publish_attempts", column)
