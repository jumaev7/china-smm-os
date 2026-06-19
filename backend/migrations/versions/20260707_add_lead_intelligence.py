"""Add AI lead intelligence fields to crm_leads."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260707_add_lead_intelligence"
down_revision = "20260706_add_sales_playbooks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing("crm_leads", sa.Column("lead_score", sa.Integer(), nullable=True))
    add_column_if_missing(
        "crm_leads",
        sa.Column("qualification_level", sa.String(50), nullable=True),
    )
    add_column_if_missing("crm_leads", sa.Column("ai_summary", sa.Text(), nullable=True))
    add_column_if_missing(
        "crm_leads",
        sa.Column("recommended_action", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "crm_leads",
        sa.Column("last_scored_at", sa.DateTime(timezone=True), nullable=True),
    )
    create_index_if_missing("ix_crm_leads_lead_score", "crm_leads", ["lead_score"])
    create_index_if_missing("ix_crm_leads_qualification_level", "crm_leads", ["qualification_level"])


def downgrade() -> None:
    op.drop_index("ix_crm_leads_qualification_level", table_name="crm_leads")
    op.drop_index("ix_crm_leads_lead_score", table_name="crm_leads")
    op.drop_column("crm_leads", "last_scored_at")
    op.drop_column("crm_leads", "recommended_action")
    op.drop_column("crm_leads", "ai_summary")
    op.drop_column("crm_leads", "qualification_level")
    op.drop_column("crm_leads", "lead_score")
