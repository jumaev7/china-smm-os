"""CRM deals and deal timeline events."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260611_add_crm_deals"
down_revision = "20260610_add_crm_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "crm_deals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("expected_value", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("expected_close_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_crm_deals_lead_id", "crm_deals", ["lead_id"])
    create_index_if_missing("ix_crm_deals_client_id", "crm_deals", ["client_id"])
    create_index_if_missing("ix_crm_deals_status", "crm_deals", ["status"])

    create_table_if_missing(
        "crm_deal_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("crm_deals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("payload_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_crm_deal_events_deal_id", "crm_deal_events", ["deal_id"])


def downgrade() -> None:
    op.drop_index("ix_crm_deal_events_deal_id", table_name="crm_deal_events")
    op.drop_table("crm_deal_events")
    op.drop_index("ix_crm_deals_status", table_name="crm_deals")
    op.drop_index("ix_crm_deals_client_id", table_name="crm_deals")
    op.drop_index("ix_crm_deals_lead_id", table_name="crm_deals")
    op.drop_table("crm_deals")
