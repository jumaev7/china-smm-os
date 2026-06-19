"""CRM documents table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260610_add_crm_documents"
down_revision = "20260609_add_crm_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "crm_documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("proposal_id", UUID(as_uuid=True), sa.ForeignKey("crm_proposals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=10), nullable=False, server_default="ru"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("document_text", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="UZS"),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_crm_documents_proposal_id", "crm_documents", ["proposal_id"])
    create_index_if_missing("ix_crm_documents_lead_id", "crm_documents", ["lead_id"])
    create_index_if_missing("ix_crm_documents_status", "crm_documents", ["status"])


def downgrade() -> None:
    op.drop_index("ix_crm_documents_status", table_name="crm_documents")
    op.drop_index("ix_crm_documents_lead_id", table_name="crm_documents")
    op.drop_index("ix_crm_documents_proposal_id", table_name="crm_documents")
    op.drop_table("crm_documents")
