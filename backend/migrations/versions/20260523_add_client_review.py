"""Add client review link fields to content_items."""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, create_index_if_missing, drop_column_if_exists

revision = "20260523_add_client_review"
down_revision = "20260522_add_telegram_active_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing("content_items", sa.Column("review_token", sa.String(length=64), nullable=True))
    add_column_if_missing("content_items", sa.Column("client_approved_at", sa.DateTime(timezone=True), nullable=True))
    add_column_if_missing("content_items", sa.Column("client_review_feedback", sa.Text(), nullable=True))
    create_index_if_missing("ix_content_items_review_token", "content_items", ["review_token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_content_items_review_token", table_name="content_items")
    drop_column_if_exists("content_items", "client_review_feedback")
    drop_column_if_exists("content_items", "client_approved_at")
    drop_column_if_exists("content_items", "review_token")
