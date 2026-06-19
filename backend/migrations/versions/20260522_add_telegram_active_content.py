"""Add telegram_active_content_id to clients for group task memory."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from migrations.helpers import add_column_if_missing, create_foreign_key_if_missing, drop_column_if_exists

revision = "20260522_add_telegram_active_content"
down_revision = "20260522_tg_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "clients",
        sa.Column("telegram_active_content_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    create_foreign_key_if_missing(
        "fk_clients_telegram_active_content_id",
        "clients",
        "content_items",
        ["telegram_active_content_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_clients_telegram_active_content_id", "clients", type_="foreignkey")
    drop_column_if_exists("clients", "telegram_active_content_id")
