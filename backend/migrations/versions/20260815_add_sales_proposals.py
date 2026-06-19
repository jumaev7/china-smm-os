"""Add tenant-scoped commercial proposals tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260815_add_sales_proposals"
down_revision = "20260814_add_sales_crm"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "sales_proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("proposal_number", sa.String(50), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("sales_deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("issue_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("currency", sa.String(10), server_default="USD", nullable=False),
        sa.Column("subtotal", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("discount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("tax", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("status", sa.String(20), server_default="draft", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("terms", sa.Text(), nullable=True),
        sa.Column("status_history", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_sales_proposals_tenant_id", "sales_proposals", ["tenant_id"])
    create_index_if_missing("ix_sales_proposals_proposal_number", "sales_proposals", ["proposal_number"])
    create_index_if_missing("ix_sales_proposals_status", "sales_proposals", ["status"])
    create_index_if_missing("ix_sales_proposals_customer_id", "sales_proposals", ["customer_id"])
    create_index_if_missing("ix_sales_proposals_lead_id", "sales_proposals", ["lead_id"])
    create_index_if_missing("ix_sales_proposals_deal_id", "sales_proposals", ["deal_id"])

    create_table_if_missing(
        "sales_proposal_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("proposal_id", UUID(as_uuid=True), sa.ForeignKey("sales_proposals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_or_service_name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), server_default="1", nullable=False),
        sa.Column("unit_price", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("discount", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("total", sa.Numeric(18, 2), server_default="0", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_sales_proposal_items_proposal_id", "sales_proposal_items", ["proposal_id"])


def downgrade() -> None:
    op.drop_table("sales_proposal_items")
    op.drop_table("sales_proposals")
