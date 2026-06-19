"""Add buyer_outreach_messages table."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260704_add_buyer_outreach_messages"
down_revision = "20260703_add_operator_user_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "buyer_outreach_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("proposal_id", UUID(as_uuid=True), sa.ForeignKey("proposal_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("buyer_name", sa.String(255), nullable=True),
        sa.Column("buyer_company", sa.String(255), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="en"),
        sa.Column("outreach_type", sa.String(30), nullable=False),
        sa.Column("subject", sa.String(500), nullable=True),
        sa.Column("message_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_buyer_outreach_messages_client_id", "buyer_outreach_messages", ["client_id"])
    create_index_if_missing("ix_buyer_outreach_messages_lead_id", "buyer_outreach_messages", ["lead_id"])
    create_index_if_missing("ix_buyer_outreach_messages_product_id", "buyer_outreach_messages", ["product_id"])
    create_index_if_missing("ix_buyer_outreach_messages_proposal_id", "buyer_outreach_messages", ["proposal_id"])
    create_index_if_missing("ix_buyer_outreach_messages_country", "buyer_outreach_messages", ["country"])
    create_index_if_missing("ix_buyer_outreach_messages_channel", "buyer_outreach_messages", ["channel"])
    create_index_if_missing("ix_buyer_outreach_messages_outreach_type", "buyer_outreach_messages", ["outreach_type"])
    create_index_if_missing("ix_buyer_outreach_messages_status", "buyer_outreach_messages", ["status"])


def downgrade() -> None:
    op.drop_index("ix_buyer_outreach_messages_status", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_outreach_type", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_channel", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_country", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_proposal_id", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_product_id", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_lead_id", table_name="buyer_outreach_messages")
    op.drop_index("ix_buyer_outreach_messages_client_id", table_name="buyer_outreach_messages")
    op.drop_table("buyer_outreach_messages")
