"""Add tenant-scoped Buyer Network CRM tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260816_add_buyer_crm"
down_revision = "20260815_add_sales_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "buyers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("contact_person", sa.String(255), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("telegram", sa.String(100), nullable=True),
        sa.Column("whatsapp", sa.String(100), nullable=True),
        sa.Column("wechat", sa.String(100), nullable=True),
        sa.Column("annual_purchase_volume", sa.String(100), nullable=True),
        sa.Column("product_categories", JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("tags", JSONB(), nullable=True),
        sa.Column("status", sa.String(30), server_default="prospect", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_buyers_tenant_id", "buyers", ["tenant_id"])
    create_index_if_missing("ix_buyers_company_name", "buyers", ["company_name"])
    create_index_if_missing("ix_buyers_country", "buyers", ["country"])
    create_index_if_missing("ix_buyers_industry", "buyers", ["industry"])
    create_index_if_missing("ix_buyers_status", "buyers", ["status"])

    create_table_if_missing(
        "buyer_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=True), sa.ForeignKey("buyers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata_json", JSONB(), nullable=True),
        sa.Column("activity_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_buyer_activities_tenant_id", "buyer_activities", ["tenant_id"])
    create_index_if_missing("ix_buyer_activities_buyer_id", "buyer_activities", ["buyer_id"])

    create_table_if_missing(
        "buyer_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=True), sa.ForeignKey("buyers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_buyer_notes_tenant_id", "buyer_notes", ["tenant_id"])
    create_index_if_missing("ix_buyer_notes_buyer_id", "buyer_notes", ["buyer_id"])

    create_table_if_missing(
        "buyer_status_history",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=True), sa.ForeignKey("buyers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_status", sa.String(30), nullable=True),
        sa.Column("to_status", sa.String(30), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(255), nullable=True),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_buyer_status_history_tenant_id", "buyer_status_history", ["tenant_id"])
    create_index_if_missing("ix_buyer_status_history_buyer_id", "buyer_status_history", ["buyer_id"])

    create_table_if_missing(
        "buyer_entity_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=True), sa.ForeignKey("buyers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_buyer_entity_links_tenant_id", "buyer_entity_links", ["tenant_id"])
    create_index_if_missing("ix_buyer_entity_links_buyer_id", "buyer_entity_links", ["buyer_id"])
    create_index_if_missing("ix_buyer_entity_links_entity_type", "buyer_entity_links", ["entity_type"])
    create_index_if_missing("ix_buyer_entity_links_entity_id", "buyer_entity_links", ["entity_id"])


def downgrade() -> None:
    op.drop_table("buyer_entity_links")
    op.drop_table("buyer_status_history")
    op.drop_table("buyer_notes")
    op.drop_table("buyer_activities")
    op.drop_table("buyers")
