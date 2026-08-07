"""Add governed per-client auto-publish opt-in."""
from alembic import op
import sqlalchemy as sa

from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260920_auto_publish_after_client_approval"
down_revision = "20260919_telegram_auto_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "clients",
        sa.Column(
            "auto_publish_after_client_approval",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    drop_column_if_exists("clients", "auto_publish_after_client_approval")
