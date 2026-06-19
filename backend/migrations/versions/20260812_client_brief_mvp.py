"""Client brief MVP — new fields and status values."""
from alembic import op
import sqlalchemy as sa

revision = "20260812_client_brief_mvp"
down_revision = "20260811_add_client_briefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS product_description TEXT"
    ))
    bind.execute(sa.text(
        "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS notes TEXT"
    ))
    bind.execute(sa.text(
        "ALTER TABLE client_briefs ADD COLUMN IF NOT EXISTS languages JSON"
    ))
    bind.execute(sa.text(
        "UPDATE client_briefs SET status = 'new' WHERE status = 'submitted'"
    ))
    bind.execute(sa.text(
        "UPDATE client_briefs SET status = 'approved' WHERE status = 'plan_generated'"
    ))
    bind.execute(sa.text(
        "UPDATE client_briefs SET status = 'converted' WHERE status = 'tasks_created'"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE client_briefs SET status = 'submitted' WHERE status = 'new'"
        ),
    )
    bind.execute(
        sa.text(
            "UPDATE client_briefs SET status = 'plan_generated' WHERE status = 'approved'"
        ),
    )
    bind.execute(
        sa.text(
            "UPDATE client_briefs SET status = 'tasks_created' WHERE status = 'converted'"
        ),
    )
    bind.execute(
        sa.text(
            "UPDATE client_briefs SET status = 'reviewing' WHERE status = 'reviewing'"
        ),
    )

    op.drop_column("client_briefs", "languages")
    op.drop_column("client_briefs", "notes")
    op.drop_column("client_briefs", "product_description")
