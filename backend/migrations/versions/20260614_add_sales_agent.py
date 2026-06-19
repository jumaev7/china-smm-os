"""Sales agent recommendations table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260614_add_sales_agent"
down_revision = "20260613_add_partners"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "sales_agent_recommendations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recommendation_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("suggested_message", sa.Text(), nullable=True),
        sa.Column("suggested_action", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("linked_task_id", UUID(as_uuid=True), sa.ForeignKey("operator_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_sales_agent_recommendations_client_id", "sales_agent_recommendations", ["client_id"])
    create_index_if_missing("ix_sales_agent_recommendations_status", "sales_agent_recommendations", ["status"])
    create_index_if_missing("ix_sales_agent_recommendations_priority", "sales_agent_recommendations", ["priority"])
    create_index_if_missing("ix_sales_agent_recommendations_type", "sales_agent_recommendations", ["recommendation_type"])
    create_index_if_missing("ix_sales_agent_recommendations_dedupe_key", "sales_agent_recommendations", ["dedupe_key"])


def downgrade() -> None:
    op.drop_index("ix_sales_agent_recommendations_dedupe_key", table_name="sales_agent_recommendations")
    op.drop_index("ix_sales_agent_recommendations_type", table_name="sales_agent_recommendations")
    op.drop_index("ix_sales_agent_recommendations_priority", table_name="sales_agent_recommendations")
    op.drop_index("ix_sales_agent_recommendations_status", table_name="sales_agent_recommendations")
    op.drop_index("ix_sales_agent_recommendations_client_id", table_name="sales_agent_recommendations")
    op.drop_table("sales_agent_recommendations")
