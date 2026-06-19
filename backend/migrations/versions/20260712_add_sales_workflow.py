"""Sales workflow automation recommendations table."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260712_add_sales_workflow"
down_revision = "20260711_add_operator_task_engine"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "sales_workflow_recommendations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=True),
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("proposal_id", UUID(as_uuid=True), sa.ForeignKey("proposal_documents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", sa.String(length=80), nullable=True),
        sa.Column("channel", sa.String(length=30), nullable=True),
        sa.Column("workflow_type", sa.String(length=40), nullable=False),
        sa.Column("detection_type", sa.String(length=40), nullable=False),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recommended_actions", JSONB(), nullable=False, server_default="[]"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("linked_task_id", UUID(as_uuid=True), sa.ForeignKey("operator_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("entity_type", sa.String(length=30), nullable=True),
        sa.Column("entity_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_sales_workflow_recommendations_client_id", "sales_workflow_recommendations", ["client_id"])
    create_index_if_missing("ix_sales_workflow_recommendations_lead_id", "sales_workflow_recommendations", ["lead_id"])
    create_index_if_missing("ix_sales_workflow_recommendations_deal_id", "sales_workflow_recommendations", ["deal_id"])
    create_index_if_missing("ix_sales_workflow_recommendations_proposal_id", "sales_workflow_recommendations", ["proposal_id"])
    create_index_if_missing("ix_sales_workflow_recommendations_conversation_id", "sales_workflow_recommendations", ["conversation_id"])
    create_index_if_missing("ix_sales_workflow_recommendations_workflow_type", "sales_workflow_recommendations", ["workflow_type"])
    create_index_if_missing("ix_sales_workflow_recommendations_detection_type", "sales_workflow_recommendations", ["detection_type"])
    create_index_if_missing("ix_sales_workflow_recommendations_priority", "sales_workflow_recommendations", ["priority"])
    create_index_if_missing("ix_sales_workflow_recommendations_status", "sales_workflow_recommendations", ["status"])
    create_index_if_missing("ix_sales_workflow_recommendations_dedupe_key", "sales_workflow_recommendations", ["dedupe_key"])


def downgrade() -> None:
    op.drop_index("ix_sales_workflow_recommendations_dedupe_key", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_status", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_priority", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_detection_type", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_workflow_type", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_conversation_id", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_proposal_id", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_deal_id", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_lead_id", table_name="sales_workflow_recommendations")
    op.drop_index("ix_sales_workflow_recommendations_client_id", table_name="sales_workflow_recommendations")
    op.drop_table("sales_workflow_recommendations")
