"""Add media request fields to content_items."""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260602_add_media_request"
down_revision = "20260601_content_plan_linked_content"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "content_items",
        sa.Column("media_request_sent_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing("content_items", sa.Column("media_request_message", sa.Text(), nullable=True))
    add_column_if_missing("content_items", sa.Column("media_request_status", sa.String(length=20), nullable=True))
    add_column_if_missing("content_items", sa.Column("media_request_format", sa.String(length=20), nullable=True))


def downgrade() -> None:
    drop_column_if_exists("content_items", "media_request_format")
    drop_column_if_exists("content_items", "media_request_status")
    drop_column_if_exists("content_items", "media_request_message")
    drop_column_if_exists("content_items", "media_request_sent_at")
