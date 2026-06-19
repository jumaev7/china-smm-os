"""Operator task engine — linked CRM/inbox/sales fields on operator_tasks."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260711_add_operator_task_engine"
down_revision = "20260710_add_sales_assistant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "operator_tasks",
        sa.Column(
            "recommendation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("sales_assistant_recommendations.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing("operator_tasks", sa.Column("conversation_id", sa.String(length=80), nullable=True))
    add_column_if_missing(
        "operator_tasks",
        sa.Column("lead_id", UUID(as_uuid=True), sa.ForeignKey("crm_leads.id", ondelete="SET NULL"), nullable=True),
    )
    add_column_if_missing(
        "operator_tasks",
        sa.Column("deal_id", UUID(as_uuid=True), sa.ForeignKey("crm_deals.id", ondelete="SET NULL"), nullable=True),
    )
    add_column_if_missing(
        "operator_tasks",
        sa.Column(
            "proposal_id",
            UUID(as_uuid=True),
            sa.ForeignKey("proposal_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing("operator_tasks", sa.Column("channel", sa.String(length=30), nullable=True))
    add_column_if_missing("operator_tasks", sa.Column("action_type", sa.String(length=40), nullable=True))
    add_column_if_missing("operator_tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing("operator_tasks", sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True))

    create_index_if_missing("ix_operator_tasks_recommendation_id", "operator_tasks", ["recommendation_id"])
    create_index_if_missing("ix_operator_tasks_conversation_id", "operator_tasks", ["conversation_id"])
    create_index_if_missing("ix_operator_tasks_lead_id", "operator_tasks", ["lead_id"])
    create_index_if_missing("ix_operator_tasks_deal_id", "operator_tasks", ["deal_id"])
    create_index_if_missing("ix_operator_tasks_proposal_id", "operator_tasks", ["proposal_id"])
    create_index_if_missing("ix_operator_tasks_action_type", "operator_tasks", ["action_type"])


def downgrade() -> None:
    for idx in (
        "ix_operator_tasks_action_type",
        "ix_operator_tasks_proposal_id",
        "ix_operator_tasks_deal_id",
        "ix_operator_tasks_lead_id",
        "ix_operator_tasks_conversation_id",
        "ix_operator_tasks_recommendation_id",
    ):
        op.drop_index(idx, table_name="operator_tasks")
    for col in (
        "dismissed_at",
        "completed_at",
        "action_type",
        "channel",
        "proposal_id",
        "deal_id",
        "lead_id",
        "conversation_id",
        "recommendation_id",
    ):
        op.drop_column("operator_tasks", col)
