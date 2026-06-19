"""Client brief pipeline — admin feedback and changes_requested status."""
from alembic import op
import sqlalchemy as sa

revision = "20260813_client_brief_pipeline"
down_revision = "20260812_client_brief_mvp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS admin_feedback TEXT"
    ))


def downgrade() -> None:
    op.drop_column("client_briefs", "admin_feedback")
