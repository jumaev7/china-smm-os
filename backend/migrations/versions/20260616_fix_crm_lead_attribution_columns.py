"""Ensure CRM lead attribution columns exist (fix create_tables / partial migration drift)."""
from alembic import op

revision = "20260616_fix_crm_lead_attribution_columns"
down_revision = "20260615_fix_crm_deal_revenue_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_source VARCHAR(50)"
    )
    op.execute(
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_campaign VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_notes TEXT"
    )
    op.execute(
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attributed_by VARCHAR(100)"
    )
    op.execute(
        """
        UPDATE crm_leads
        SET attribution_source = source
        WHERE attribution_source IS NULL AND source IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_column("crm_leads", "attributed_by")
    op.drop_column("crm_leads", "attribution_notes")
    op.drop_column("crm_leads", "attribution_campaign")
    op.drop_column("crm_leads", "attribution_source")
