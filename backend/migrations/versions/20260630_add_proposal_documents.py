"""Add proposal_documents table for AI Proposal Generator v2."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260630_add_proposal_documents"
down_revision = "20260629_fix_crm_leads_attribution_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "proposal_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="ru"),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("proposal_json", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("proposal_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_proposal_documents_client_id", "proposal_documents", ["client_id"])
    create_index_if_missing("ix_proposal_documents_lead_id", "proposal_documents", ["lead_id"])
    create_index_if_missing("ix_proposal_documents_deal_id", "proposal_documents", ["deal_id"])
    create_index_if_missing("ix_proposal_documents_product_id", "proposal_documents", ["product_id"])
    create_index_if_missing("ix_proposal_documents_status", "proposal_documents", ["status"])


def downgrade() -> None:
    op.drop_index("ix_proposal_documents_status", table_name="proposal_documents")
    op.drop_index("ix_proposal_documents_product_id", table_name="proposal_documents")
    op.drop_index("ix_proposal_documents_deal_id", table_name="proposal_documents")
    op.drop_index("ix_proposal_documents_lead_id", table_name="proposal_documents")
    op.drop_index("ix_proposal_documents_client_id", table_name="proposal_documents")
    op.drop_table("proposal_documents")
