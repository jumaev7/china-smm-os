"""Revenue attribution, commission fields, and revenue events."""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing, drop_column_if_exists, drop_index_if_exists

revision = "20260612_add_revenue_attribution"
down_revision = "20260611_add_crm_deals"
branch_labels = None
depends_on = None

ATTRIBUTION_SOURCES = (
    "instagram",
    "facebook",
    "telegram",
    "website",
    "referral",
    "manual",
    "other",
)


def upgrade() -> None:
    create_table_if_missing(
        "attribution_sources",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False, unique=True),
    )

    sources_table = sa.table(
        "attribution_sources",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("name", sa.String()),
    )
    op.bulk_insert(
        sources_table,
        [{"id": uuid.uuid4(), "name": name} for name in ATTRIBUTION_SOURCES],
    )

    add_column_if_missing("crm_leads", sa.Column("attribution_source", sa.String(length=50), nullable=True))
    add_column_if_missing("crm_leads", sa.Column("attribution_campaign", sa.String(length=255), nullable=True))
    add_column_if_missing("crm_leads", sa.Column("attribution_notes", sa.Text(), nullable=True))
    add_column_if_missing("crm_leads", sa.Column("attributed_by", sa.String(length=100), nullable=True))

    add_column_if_missing("crm_deals", sa.Column("deal_amount", sa.Numeric(precision=12, scale=2), nullable=True))
    add_column_if_missing("crm_deals", sa.Column("currency", sa.String(length=10), nullable=False, server_default="UZS"))
    add_column_if_missing("crm_deals", sa.Column("commission_percent", sa.Numeric(precision=5, scale=2), nullable=True))
    add_column_if_missing("crm_deals", sa.Column("commission_amount", sa.Numeric(precision=12, scale=2), nullable=True))
    add_column_if_missing(
        "crm_deals",
        sa.Column("commission_status", sa.String(length=20), nullable=True),
    )
    create_index_if_missing("ix_crm_deals_commission_status", "crm_deals", ["commission_status"])

    create_table_if_missing(
        "revenue_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_revenue_events_deal_id", "revenue_events", ["deal_id"])
    create_index_if_missing("ix_revenue_events_type", "revenue_events", ["type"])


def downgrade() -> None:
    op.drop_index("ix_revenue_events_type", table_name="revenue_events")
    op.drop_index("ix_revenue_events_deal_id", table_name="revenue_events")
    op.drop_table("revenue_events")
    drop_index_if_exists("ix_crm_deals_commission_status", "crm_deals")
    drop_column_if_exists("crm_deals", "commission_status")
    drop_column_if_exists("crm_deals", "commission_amount")
    drop_column_if_exists("crm_deals", "commission_percent")
    drop_column_if_exists("crm_deals", "currency")
    drop_column_if_exists("crm_deals", "deal_amount")
    drop_column_if_exists("crm_leads", "attributed_by")
    drop_column_if_exists("crm_leads", "attribution_notes")
    drop_column_if_exists("crm_leads", "attribution_campaign")
    drop_column_if_exists("crm_leads", "attribution_source")
    op.drop_table("attribution_sources")
