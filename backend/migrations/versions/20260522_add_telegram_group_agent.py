"""Telegram group buffer agent tables and client workflow mode.

Revision ID: 20260522_tg_agent
Revises: 20260522_context_override
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing, drop_column_if_exists

revision = "20260522_tg_agent"
down_revision = "20260522_context_override"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "clients",
        sa.Column(
            "telegram_workflow_mode",
            sa.String(length=40),
            nullable=False,
            server_default="auto_create_from_media",
        ),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("telegram_buffer_refs", sa.Text(), nullable=True),
    )

    create_table_if_missing(
        "telegram_group_buffer_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.String(length=50), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("sender_id", sa.String(length=50), nullable=False),
        sa.Column("sender_role", sa.String(length=20), nullable=False),
        sa.Column("message_type", sa.String(length=20), nullable=False),
        sa.Column("telegram_file_id", sa.String(length=255), nullable=True),
        sa.Column("media_file_id", UUID(as_uuid=True), sa.ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_path", sa.String(length=1000), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("message_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "message_id", name="uq_tg_buffer_group_message"),
    )
    create_index_if_missing("ix_tg_buffer_client_id", "telegram_group_buffer_messages", ["client_id"])
    create_index_if_missing("ix_tg_buffer_group_id", "telegram_group_buffer_messages", ["group_id"])

    create_table_if_missing(
        "telegram_processed_updates",
        sa.Column("update_id", sa.BigInteger(), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("telegram_processed_updates")
    op.drop_index("ix_tg_buffer_group_id", table_name="telegram_group_buffer_messages")
    op.drop_index("ix_tg_buffer_client_id", table_name="telegram_group_buffer_messages")
    op.drop_table("telegram_group_buffer_messages")
    drop_column_if_exists("content_items", "telegram_buffer_refs")
    drop_column_if_exists("clients", "telegram_workflow_mode")
