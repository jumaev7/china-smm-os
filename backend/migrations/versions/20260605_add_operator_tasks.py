"""Operator task board table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260605_add_operator_tasks"
down_revision = "20260604_add_account_manager"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "operator_tasks",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_id", UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(length=10), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="todo"),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assigned_to", sa.String(length=100), nullable=True),
        sa.Column("created_by", sa.String(length=30), nullable=False, server_default="admin"),
        sa.Column("linked_content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_operator_tasks_client_id", "operator_tasks", ["client_id"])
    create_index_if_missing("ix_operator_tasks_status", "operator_tasks", ["status"])
    create_index_if_missing("ix_operator_tasks_source_type", "operator_tasks", ["source_type"])
    create_index_if_missing("ix_operator_tasks_source_id", "operator_tasks", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_operator_tasks_source_id", table_name="operator_tasks")
    op.drop_index("ix_operator_tasks_source_type", table_name="operator_tasks")
    op.drop_index("ix_operator_tasks_status", table_name="operator_tasks")
    op.drop_index("ix_operator_tasks_client_id", table_name="operator_tasks")
    op.drop_table("operator_tasks")
