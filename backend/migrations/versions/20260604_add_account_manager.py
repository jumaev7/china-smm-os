"""Account Manager fields on telegram buffer messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260604_add_account_manager"
down_revision = "20260603_add_client_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("account_manager_intent", sa.String(length=40), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("account_manager_summary", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("account_manager_recommended_action", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("account_manager_priority", sa.String(length=10), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("account_manager_reply_sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("account_manager_reply_text", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column(
            "account_manager_related_content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("content_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("account_manager_processed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_processed_at")
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_related_content_id")
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_reply_text")
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_reply_sent")
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_priority")
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_recommended_action")
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_summary")
    drop_column_if_exists("telegram_group_buffer_messages", "account_manager_intent")
