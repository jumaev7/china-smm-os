"""Executive CRM pipeline — 12-stage lifecycle, timeline events, commercial entity links."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260828_executive_crm_pipeline"
down_revision = "20260827_add_publishing_accounts_tenant_id"
branch_labels = None
depends_on = None

_LEGACY_STAGE_MAP = {
    "new_lead": "lead",
    "contacted": "contacted",
    "negotiation": "negotiation",
    "proposal_sent": "proposal_sent",
    "won": "closed_won",
    "lost": "closed_lost",
}


def _remap_deal_stages() -> None:
    bind = op.get_bind()
    for old, new in _LEGACY_STAGE_MAP.items():
        bind.execute(
            sa.text("UPDATE sales_deals SET stage = :new WHERE stage = :old"),
            {"old": old, "new": new},
        )


def upgrade() -> None:
    # ── SalesCustomer commercial links + account manager ─────────────────────
    add_column_if_missing(
        "sales_customers",
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
    )
    add_column_if_missing(
        "sales_customers",
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True),
    )
    add_column_if_missing(
        "sales_customers",
        sa.Column(
            "primary_publishing_account_id",
            UUID(as_uuid=True),
            sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    create_index_if_missing("ix_sales_customers_client_id", "sales_customers", ["client_id"])
    create_index_if_missing("ix_sales_customers_owner_id", "sales_customers", ["owner_id"])
    create_index_if_missing(
        "ix_sales_customers_primary_publishing_account_id",
        "sales_customers",
        ["primary_publishing_account_id"],
    )

    # ── SalesDeal pipeline fields ─────────────────────────────────────────────
    add_column_if_missing(
        "sales_deals",
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "sales_deals",
        sa.Column("owner_id", UUID(as_uuid=True), sa.ForeignKey("tenant_users.id", ondelete="SET NULL"), nullable=True),
    )
    add_column_if_missing(
        "sales_deals",
        sa.Column("stage_source", sa.String(20), server_default="manual", nullable=False),
    )
    add_column_if_missing(
        "sales_deals",
        sa.Column("stage_override", sa.Boolean(), server_default="false", nullable=False),
    )
    create_index_if_missing("ix_sales_deals_owner_id", "sales_deals", ["owner_id"])

    _remap_deal_stages()

    # ── SalesProposal first-class fields ──────────────────────────────────────
    add_column_if_missing(
        "sales_proposals",
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
    )
    add_column_if_missing(
        "sales_proposals",
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "sales_proposals",
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "sales_proposals",
        sa.Column("attachment_url", sa.String(1024), nullable=True),
    )

    # ── Pipeline timeline events ──────────────────────────────────────────────
    create_table_if_missing(
        "crm_pipeline_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("payload", JSONB(), nullable=True),
        sa.Column("customer_id", UUID(as_uuid=True), sa.ForeignKey("sales_customers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("sales_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("sales_deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_crm_pipeline_events_tenant_id", "crm_pipeline_events", ["tenant_id"])
    create_index_if_missing("ix_crm_pipeline_events_event_type", "crm_pipeline_events", ["event_type"])
    create_index_if_missing("ix_crm_pipeline_events_customer_id", "crm_pipeline_events", ["customer_id"])
    create_index_if_missing("ix_crm_pipeline_events_lead_id", "crm_pipeline_events", ["lead_id"])
    create_index_if_missing("ix_crm_pipeline_events_deal_id", "crm_pipeline_events", ["deal_id"])
    create_index_if_missing("ix_crm_pipeline_events_created_at", "crm_pipeline_events", ["created_at"])


def downgrade() -> None:
    op.drop_table("crm_pipeline_events")

    for col in ("attachment_url", "accepted_at", "sent_at", "version"):
        op.drop_column("sales_proposals", col)

    for col in ("stage_override", "stage_source", "owner_id", "closed_at"):
        op.drop_column("sales_deals", col)

    for col in ("primary_publishing_account_id", "owner_id", "client_id"):
        op.drop_column("sales_customers", col)

    bind = op.get_bind()
    _reverse = {v: k for k, v in _LEGACY_STAGE_MAP.items()}
    for new, old in _reverse.items():
        bind.execute(
            sa.text("UPDATE sales_deals SET stage = :old WHERE stage = :new"),
            {"old": old, "new": new},
        )
