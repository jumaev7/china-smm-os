"""Communication Hub tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260623_add_communication_hub"
down_revision = "20260622_add_content_repurpose_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "communication_contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("telegram", sa.String(length=100), nullable=True),
        sa.Column("whatsapp", sa.String(length=100), nullable=True),
        sa.Column("wechat", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_communication_contacts_client_id", "communication_contacts", ["client_id"])
    create_index_if_missing("ix_communication_contacts_lead_id", "communication_contacts", ["lead_id"])
    create_index_if_missing("ix_communication_contacts_partner_id", "communication_contacts", ["partner_id"])

    create_table_if_missing(
        "communication_threads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("contact_id", UUID(as_uuid=True), sa.ForeignKey("communication_contacts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("external_thread_id", sa.String(length=100), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_communication_threads_contact_id", "communication_threads", ["contact_id"])
    create_index_if_missing("ix_communication_threads_client_id", "communication_threads", ["client_id"])
    create_index_if_missing("ix_communication_threads_lead_id", "communication_threads", ["lead_id"])
    create_index_if_missing("ix_communication_threads_channel", "communication_threads", ["channel"])
    create_index_if_missing("ix_communication_threads_status", "communication_threads", ["status"])
    create_index_if_missing("ix_communication_threads_external_thread_id", "communication_threads", ["external_thread_id"])

    create_table_if_missing(
        "communication_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("thread_id", UUID(as_uuid=True), sa.ForeignKey("communication_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("sender_name", sa.String(length=255), nullable=False),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("attachments_json", JSONB(), nullable=True),
        sa.Column("ai_summary", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_communication_messages_thread_id", "communication_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_communication_messages_thread_id", table_name="communication_messages")
    op.drop_table("communication_messages")
    op.drop_index("ix_communication_threads_external_thread_id", table_name="communication_threads")
    op.drop_index("ix_communication_threads_status", table_name="communication_threads")
    op.drop_index("ix_communication_threads_channel", table_name="communication_threads")
    op.drop_index("ix_communication_threads_lead_id", table_name="communication_threads")
    op.drop_index("ix_communication_threads_client_id", table_name="communication_threads")
    op.drop_index("ix_communication_threads_contact_id", table_name="communication_threads")
    op.drop_table("communication_threads")
    op.drop_index("ix_communication_contacts_partner_id", table_name="communication_contacts")
    op.drop_index("ix_communication_contacts_lead_id", table_name="communication_contacts")
    op.drop_index("ix_communication_contacts_client_id", table_name="communication_contacts")
    op.drop_table("communication_contacts")
