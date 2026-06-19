"""Partners, referral links, and partner commission on CRM."""
import uuid

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing, drop_column_if_exists

revision = "20260613_add_partners"
down_revision = "20260612_add_revenue_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "partners",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("telegram", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_partners_status", "partners", ["status"])

    create_table_if_missing(
        "referral_links",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_referral_links_partner_id", "referral_links", ["partner_id"])
    create_index_if_missing("ix_referral_links_code", "referral_links", ["code"])

    add_column_if_missing(
        "crm_leads",
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="SET NULL"), nullable=True),
    )
    add_column_if_missing("crm_leads", sa.Column("referral_code", sa.String(length=50), nullable=True))
    create_index_if_missing("ix_crm_leads_partner_id", "crm_leads", ["partner_id"])

    add_column_if_missing("crm_deals", sa.Column("partner_commission_percent", sa.Numeric(precision=5, scale=2), nullable=True))
    add_column_if_missing("crm_deals", sa.Column("partner_commission_amount", sa.Numeric(precision=12, scale=2), nullable=True))


def downgrade() -> None:
    drop_column_if_exists("crm_deals", "partner_commission_amount")
    drop_column_if_exists("crm_deals", "partner_commission_percent")
    op.drop_index("ix_crm_leads_partner_id", table_name="crm_leads")
    drop_column_if_exists("crm_leads", "referral_code")
    drop_column_if_exists("crm_leads", "partner_id")
    op.drop_index("ix_referral_links_code", table_name="referral_links")
    op.drop_index("ix_referral_links_partner_id", table_name="referral_links")
    op.drop_table("referral_links")
    op.drop_index("ix_partners_status", table_name="partners")
    op.drop_table("partners")
