"""Content planner tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260531_add_content_planner"
down_revision = "20260530_add_smart_inbox_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "content_plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("posts_per_month", sa.Integer(), nullable=False, server_default="8"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("client_id", "month", "year", name="uq_content_plan_client_month"),
    )
    create_index_if_missing("ix_content_plans_client_id", "content_plans", ["client_id"])

    create_table_if_missing(
        "content_plan_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("plan_id", UUID(as_uuid=True), sa.ForeignKey("content_plans.id", ondelete="CASCADE"), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=False),
        sa.Column("theme", sa.String(length=500), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("platform_suggestions_json", sa.Text(), nullable=True),
        sa.Column("content_type", sa.String(length=20), nullable=False, server_default="image"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"),
        sa.Column("linked_content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_content_plan_items_plan_id", "content_plan_items", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_content_plan_items_plan_id", table_name="content_plan_items")
    op.drop_table("content_plan_items")
    op.drop_index("ix_content_plans_client_id", table_name="content_plans")
    op.drop_table("content_plans")
