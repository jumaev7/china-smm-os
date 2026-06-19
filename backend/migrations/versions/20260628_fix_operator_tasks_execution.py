"""Ensure operator_tasks execution columns exist (schema drift fix)."""
from alembic import op

revision = "20260628_fix_operator_tasks_execution"
down_revision = "20260627_add_ai_command_center"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS execution_status VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS execution_result TEXT"
    )
    op.execute(
        "ALTER TABLE operator_tasks ADD COLUMN IF NOT EXISTS executed_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE operator_tasks DROP COLUMN IF EXISTS executed_at")
    op.execute("ALTER TABLE operator_tasks DROP COLUMN IF EXISTS execution_result")
    op.execute("ALTER TABLE operator_tasks DROP COLUMN IF EXISTS execution_status")
