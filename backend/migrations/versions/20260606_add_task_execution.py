"""Add execution fields to operator_tasks."""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260606_add_task_execution"
down_revision = "20260605_add_operator_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing("operator_tasks", sa.Column("execution_status", sa.String(length=20), nullable=True))
    add_column_if_missing("operator_tasks", sa.Column("execution_result", sa.Text(), nullable=True))
    add_column_if_missing("operator_tasks", sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    drop_column_if_exists("operator_tasks", "executed_at")
    drop_column_if_exists("operator_tasks", "execution_result")
    drop_column_if_exists("operator_tasks", "execution_status")
