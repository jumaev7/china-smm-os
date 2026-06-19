"""Ensure crm_leads attribution_link_id exists (schema drift fix)."""
from alembic import op

revision = "20260629_fix_crm_leads_attribution_link"
down_revision = "20260628_fix_operator_tasks_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE crm_leads ADD COLUMN IF NOT EXISTS attribution_link_id UUID"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_crm_leads_attribution_link_id "
        "ON crm_leads (attribution_link_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_crm_leads_attribution_link_id")
    op.execute("ALTER TABLE crm_leads DROP COLUMN IF EXISTS attribution_link_id")
