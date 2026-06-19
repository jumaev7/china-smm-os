"""Smart Inbox v2 fields on telegram buffer messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, drop_column_if_exists

revision = "20260530_add_smart_inbox_v2"
down_revision = "20260530_add_client_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("ai_summary", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("priority", sa.String(length=10), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("suggested_publish_date", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("suggested_platforms_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("detected_deadline", sa.String(length=255), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("detected_offer", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("detected_language", sa.String(length=10), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("grouped_task_id", UUID(as_uuid=True), nullable=True),
    )
    create_index_if_missing(
        "ix_tg_buffer_grouped_task_id",
        "telegram_group_buffer_messages",
        ["grouped_task_id"],
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("smart_analyzed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    drop_column_if_exists("telegram_group_buffer_messages", "smart_analyzed_at")
    op.drop_index("ix_tg_buffer_grouped_task_id", table_name="telegram_group_buffer_messages")
    drop_column_if_exists("telegram_group_buffer_messages", "grouped_task_id")
    drop_column_if_exists("telegram_group_buffer_messages", "detected_language")
    drop_column_if_exists("telegram_group_buffer_messages", "detected_offer")
    drop_column_if_exists("telegram_group_buffer_messages", "detected_deadline")
    drop_column_if_exists("telegram_group_buffer_messages", "suggested_platforms_json")
    drop_column_if_exists("telegram_group_buffer_messages", "suggested_publish_date")
    drop_column_if_exists("telegram_group_buffer_messages", "priority")
    drop_column_if_exists("telegram_group_buffer_messages", "ai_summary")
