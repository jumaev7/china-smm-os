"""Telegram group instruction fields on content_items."""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, create_index_if_missing, drop_column_if_exists

revision = "20260522_tg_instructions"
down_revision = "20260522_tg_group"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "content_items",
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=True),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("telegram_excluded", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("telegram_instructions", sa.Text(), nullable=True),
    )
    create_index_if_missing(
        "ix_content_items_telegram_message_id",
        "content_items",
        ["telegram_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_telegram_message_id", table_name="content_items")
    drop_column_if_exists("content_items", "telegram_instructions")
    drop_column_if_exists("content_items", "telegram_excluded")
    drop_column_if_exists("content_items", "telegram_message_id")
