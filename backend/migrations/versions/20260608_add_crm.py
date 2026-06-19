"""CRM leads and activities tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260608_add_crm"
down_revision = "20260607_add_content_factory"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "crm_leads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("telegram", sa.String(length=100), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("source", sa.String(length=30), nullable=False, server_default="manual"),
        sa.Column("language", sa.String(length=20), nullable=True),
        sa.Column("interest", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("estimated_value", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("next_follow_up_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_crm_leads_client_id", "crm_leads", ["client_id"])
    create_index_if_missing("ix_crm_leads_status", "crm_leads", ["status"])

    create_table_if_missing(
        "crm_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_crm_activities_lead_id", "crm_activities", ["lead_id"])


def downgrade() -> None:
    op.drop_index("ix_crm_activities_lead_id", table_name="crm_activities")
    op.drop_table("crm_activities")
    op.drop_index("ix_crm_leads_status", table_name="crm_leads")
    op.drop_index("ix_crm_leads_client_id", table_name="crm_leads")
    op.drop_table("crm_leads")
