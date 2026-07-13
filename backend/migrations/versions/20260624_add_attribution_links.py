"""Attribution links and click tracking."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import (
    add_column_if_missing,
    create_index_if_missing,
    create_table_if_missing,
    drop_column_if_exists,
    drop_index_if_exists,
)

revision = "20260624_add_attribution_links"
down_revision = "20260623_add_communication_hub"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "attribution_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="SET NULL"), nullable=True),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False, unique=True),
        sa.Column("destination_url", sa.String(length=2000), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("clicks_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("leads_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_attribution_links_client_id", "attribution_links", ["client_id"])
    create_index_if_missing("ix_attribution_links_campaign_id", "attribution_links", ["campaign_id"])
    create_index_if_missing("ix_attribution_links_product_id", "attribution_links", ["product_id"])
    create_index_if_missing("ix_attribution_links_partner_id", "attribution_links", ["partner_id"])
    create_index_if_missing("ix_attribution_links_channel", "attribution_links", ["channel"])
    create_index_if_missing("ix_attribution_links_code", "attribution_links", ["code"])

    create_table_if_missing(
        "click_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("attribution_link_id", UUID(as_uuid=True), sa.ForeignKey("attribution_links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_ip", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("referrer", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_click_events_attribution_link_id", "click_events", ["attribution_link_id"])

    add_column_if_missing(
        "crm_leads",
        sa.Column(
            "attribution_link_id",
            UUID(as_uuid=True),
            sa.ForeignKey("attribution_links.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    create_index_if_missing("ix_crm_leads_attribution_link_id", "crm_leads", ["attribution_link_id"])


def downgrade() -> None:
    drop_index_if_exists("ix_crm_leads_attribution_link_id", "crm_leads")
    drop_column_if_exists("crm_leads", "attribution_link_id")
    op.drop_index("ix_click_events_attribution_link_id", table_name="click_events")
    op.drop_table("click_events")
    op.drop_index("ix_attribution_links_code", table_name="attribution_links")
    op.drop_index("ix_attribution_links_channel", table_name="attribution_links")
    op.drop_index("ix_attribution_links_partner_id", table_name="attribution_links")
    op.drop_index("ix_attribution_links_product_id", table_name="attribution_links")
    op.drop_index("ix_attribution_links_campaign_id", table_name="attribution_links")
    op.drop_index("ix_attribution_links_client_id", table_name="attribution_links")
    op.drop_table("attribution_links")
