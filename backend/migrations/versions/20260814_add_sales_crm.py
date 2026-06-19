"""Add tenant-scoped Sales CRM tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260814_add_sales_crm"
down_revision = "20260813_client_brief_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "sales_customers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("telegram", sa.String(100), nullable=True),
        sa.Column("whatsapp", sa.String(100), nullable=True),
        sa.Column("wechat", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_sales_customers_tenant_id", "sales_customers", ["tenant_id"])

    create_table_if_missing(
        "sales_leads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("company", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("telegram", sa.String(100), nullable=True),
        sa.Column("whatsapp", sa.String(100), nullable=True),
        sa.Column("wechat", sa.String(100), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("source", sa.String(30), server_default="manual", nullable=False),
        sa.Column("status", sa.String(30), server_default="new", nullable=False),
        sa.Column("priority", sa.String(10), server_default="medium", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("assigned_to", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_sales_leads_tenant_id", "sales_leads", ["tenant_id"])
    create_index_if_missing("ix_sales_leads_status", "sales_leads", ["status"])
    create_index_if_missing("ix_sales_leads_customer_id", "sales_leads", ["customer_id"])

    create_table_if_missing(
        "sales_deals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("value", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(10), server_default="USD", nullable=False),
        sa.Column("stage", sa.String(30), server_default="new_lead", nullable=False),
        sa.Column("probability", sa.Integer(), server_default="10", nullable=False),
        sa.Column("expected_close_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_sales_deals_tenant_id", "sales_deals", ["tenant_id"])
    create_index_if_missing("ix_sales_deals_stage", "sales_deals", ["stage"])
    create_index_if_missing("ix_sales_deals_customer_id", "sales_deals", ["customer_id"])
    create_index_if_missing("ix_sales_deals_lead_id", "sales_deals", ["lead_id"])

    create_table_if_missing(
        "sales_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("sales_deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("activity_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_sales_activities_tenant_id", "sales_activities", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("sales_activities")
    op.drop_table("sales_deals")
    op.drop_table("sales_leads")
    op.drop_table("sales_customers")
