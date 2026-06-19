"""Operator inbox status, linking, and AI suggestion cache on buffer messages."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, drop_column_if_exists

revision = "20260529_add_operator_inbox_ai"
down_revision = "20260525_add_client_review_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column(
            "inbox_status",
            sa.String(length=20),
            nullable=False,
            server_default="new",
        ),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column(
            "linked_content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("content_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    create_index_if_missing(
        "ix_tg_buffer_linked_content_id",
        "telegram_group_buffer_messages",
        ["linked_content_id"],
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("ai_suggestion_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("ai_suggested_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    drop_column_if_exists("telegram_group_buffer_messages", "ai_suggested_at")
    drop_column_if_exists("telegram_group_buffer_messages", "ai_suggestion_json")
    op.drop_index("ix_tg_buffer_linked_content_id", table_name="telegram_group_buffer_messages")
    drop_column_if_exists("telegram_group_buffer_messages", "linked_content_id")
    drop_column_if_exists("telegram_group_buffer_messages", "inbox_status")
