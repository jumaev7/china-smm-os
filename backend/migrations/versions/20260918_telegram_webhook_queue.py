"""Durable Telegram webhook inbox and worker lease state."""
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

revision = "20260918_telegram_webhook_queue"
down_revision = "20260917_listening_webhook_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("telegram_webhook_events"):
        op.create_table(
            "telegram_webhook_events",
            sa.Column("id", UUID(as_uuid=True), primary_key=True),
            sa.Column("update_id", sa.BigInteger(), nullable=False),
            sa.Column("payload", JSONB(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("lease_owner", sa.String(120), nullable=True),
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
            sa.UniqueConstraint("update_id", name="uq_telegram_webhook_events_update_id"),
        )
    create_index_if_missing("ix_telegram_webhook_events_update_id", "telegram_webhook_events", ["update_id"])
    create_index_if_missing("ix_telegram_webhook_events_status", "telegram_webhook_events", ["status"])
    create_index_if_missing("ix_telegram_webhook_events_lease_expires_at", "telegram_webhook_events", ["lease_expires_at"])
    create_index_if_missing(
        "ix_telegram_webhook_events_ready",
        "telegram_webhook_events",
        ["status", "available_at", "created_at"],
    )


def downgrade() -> None:
    drop_index_if_exists("ix_telegram_webhook_events_ready", table_name="telegram_webhook_events")
    drop_index_if_exists("ix_telegram_webhook_events_lease_expires_at", table_name="telegram_webhook_events")
    drop_index_if_exists("ix_telegram_webhook_events_status", table_name="telegram_webhook_events")
    drop_index_if_exists("ix_telegram_webhook_events_update_id", table_name="telegram_webhook_events")
    drop_table_if_exists("telegram_webhook_events")
