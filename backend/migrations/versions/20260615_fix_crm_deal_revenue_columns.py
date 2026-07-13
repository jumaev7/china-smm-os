"""Ensure CRM deal revenue columns exist (fix create_tables / partial migration drift)."""
from alembic import op

revision = "20260615_fix_crm_deal_revenue_columns"
down_revision = "20260614_add_sales_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS deal_amount NUMERIC(18, 2)"
    )
    op.execute(
        "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS currency VARCHAR(10) DEFAULT 'UZS'"
    )
    op.execute(
        "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS commission_percent NUMERIC(5, 2)"
    )
    op.execute(
        "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS commission_amount NUMERIC(12, 2)"
    )
    op.execute(
        "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS commission_status VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS partner_commission_percent NUMERIC(5, 2)"
    )
    op.execute(
        "ALTER TABLE crm_deals ADD COLUMN IF NOT EXISTS partner_commission_amount NUMERIC(12, 2)"
    )
    op.execute("UPDATE crm_deals SET currency = 'UZS' WHERE currency IS NULL")
    op.execute(
        """
        UPDATE crm_deals
        SET deal_amount = expected_value
        WHERE deal_amount IS NULL
          AND status = 'won'
          AND expected_value IS NOT NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_deals_commission_status "
        "ON crm_deals (commission_status)"
    )


def downgrade() -> None:
    # No-op: deal revenue columns and commission_status index are owned by earlier
    # revisions (20260612_add_revenue_attribution, 20260613_add_partners).
    # This revision only idempotently ensures they exist for schema drift recovery.
    pass
