"""Add client_review_status to content_items."""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260525_add_client_review_status"
down_revision = "20260524_add_publishing_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "content_items",
        sa.Column("client_review_status", sa.String(length=30), nullable=True),
    )


def downgrade() -> None:
    drop_column_if_exists("content_items", "client_review_status")
