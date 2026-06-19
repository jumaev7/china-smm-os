"""WhatsApp Contact Center tables."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import create_foreign_key_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260709_add_whatsapp_contact_center"
down_revision = "20260708_add_wechat_contact_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "whatsapp_contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("phone", sa.String(length=50), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("crm_client_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_foreign_key_if_missing(
        "fk_whatsapp_contacts_crm_client_id",
        "whatsapp_contacts",
        "clients",
        ["crm_client_id"],
        ["id"],
        ondelete="SET NULL",
    )
    create_index_if_missing("ix_whatsapp_contacts_phone", "whatsapp_contacts", ["phone"])
    create_index_if_missing("ix_whatsapp_contacts_crm_client_id", "whatsapp_contacts", ["crm_client_id"])

    create_table_if_missing(
        "whatsapp_threads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("contact_id", UUID(as_uuid=True), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_foreign_key_if_missing(
        "fk_whatsapp_threads_contact_id",
        "whatsapp_threads",
        "whatsapp_contacts",
        ["contact_id"],
        ["id"],
        ondelete="CASCADE",
    )
    create_index_if_missing("ix_whatsapp_threads_contact_id", "whatsapp_threads", ["contact_id"])

    create_table_if_missing(
        "whatsapp_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", UUID(as_uuid=True), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="sent"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_foreign_key_if_missing(
        "fk_whatsapp_messages_thread_id",
        "whatsapp_messages",
        "whatsapp_threads",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    create_index_if_missing("ix_whatsapp_messages_thread_id", "whatsapp_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_whatsapp_messages_thread_id", table_name="whatsapp_messages")
    op.drop_table("whatsapp_messages")
    op.drop_index("ix_whatsapp_threads_contact_id", table_name="whatsapp_threads")
    op.drop_table("whatsapp_threads")
    op.drop_index("ix_whatsapp_contacts_crm_client_id", table_name="whatsapp_contacts")
    op.drop_index("ix_whatsapp_contacts_phone", table_name="whatsapp_contacts")
    op.drop_table("whatsapp_contacts")
