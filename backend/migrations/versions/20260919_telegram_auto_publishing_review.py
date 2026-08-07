"""Automatically run advisory publishing review after Telegram ingestion."""
from __future__ import annotations

import sqlalchemy as sa

from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260919_telegram_auto_review"
down_revision = "20260918_telegram_webhook_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "telegram_ingestion_settings",
        sa.Column(
            "auto_publishing_review",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    drop_column_if_exists("telegram_ingestion_settings", "auto_publishing_review")
