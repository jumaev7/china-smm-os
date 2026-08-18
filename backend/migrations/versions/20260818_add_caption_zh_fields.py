"""Add canonical Simplified Chinese caption columns to content_items.

This is an additive migration: existing RU/UZ/EN and subtitle/video CN pipeline
continue to work without any backfill.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260818_add_caption_zh_fields"
down_revision = "20260924_telegram_operator_enrollment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "content_items",
        sa.Column("caption_short_zh", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("caption_long_zh", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Destructive downgrade (dropping columns) is intentionally left to operator choice.
    drop_column_if_exists("content_items", "caption_short_zh")
    drop_column_if_exists("content_items", "caption_long_zh")

