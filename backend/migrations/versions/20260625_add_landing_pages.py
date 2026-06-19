"""Landing pages and lead capture."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260625_add_landing_pages"
down_revision = "20260624_add_attribution_links"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "landing_pages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("attribution_link_id", UUID(as_uuid=True), sa.ForeignKey("attribution_links.id", ondelete="SET NULL"), nullable=True),
        sa.Column("slug", sa.String(length=120), nullable=False, unique=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("subtitle", sa.String(length=500), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("hero_image_url", sa.String(length=2000), nullable=True),
        sa.Column("cta_text", sa.String(length=120), nullable=False, server_default="Get in touch"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_landing_pages_client_id", "landing_pages", ["client_id"])
    create_index_if_missing("ix_landing_pages_campaign_id", "landing_pages", ["campaign_id"])
    create_index_if_missing("ix_landing_pages_product_id", "landing_pages", ["product_id"])
    create_index_if_missing("ix_landing_pages_status", "landing_pages", ["status"])
    create_index_if_missing("ix_landing_pages_slug", "landing_pages", ["slug"])

    create_table_if_missing(
        "landing_leads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("landing_page_id", UUID(as_uuid=True), sa.ForeignKey("landing_pages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("telegram", sa.String(length=100), nullable=True),
        sa.Column("whatsapp", sa.String(length=100), nullable=True),
        sa.Column("wechat", sa.String(length=100), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("crm_lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_landing_leads_landing_page_id", "landing_leads", ["landing_page_id"])
    create_index_if_missing("ix_landing_leads_crm_lead_id", "landing_leads", ["crm_lead_id"])


def downgrade() -> None:
    op.drop_index("ix_landing_leads_crm_lead_id", table_name="landing_leads")
    op.drop_index("ix_landing_leads_landing_page_id", table_name="landing_leads")
    op.drop_table("landing_leads")
    op.drop_index("ix_landing_pages_slug", table_name="landing_pages")
    op.drop_index("ix_landing_pages_status", table_name="landing_pages")
    op.drop_index("ix_landing_pages_product_id", table_name="landing_pages")
    op.drop_index("ix_landing_pages_campaign_id", table_name="landing_pages")
    op.drop_index("ix_landing_pages_client_id", table_name="landing_pages")
    op.drop_table("landing_pages")
