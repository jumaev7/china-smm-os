"""Add operator auto draft settings and inbox auto_drafted flag."""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260529_add_operator_auto_draft"
down_revision = "20260529_add_operator_inbox_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "clients",
        sa.Column(
            "operator_auto_draft_enabled",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )
    add_column_if_missing(
        "telegram_group_buffer_messages",
        sa.Column(
            "auto_drafted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
    )


def downgrade() -> None:
    drop_column_if_exists("telegram_group_buffer_messages", "auto_drafted")
    drop_column_if_exists("clients", "operator_auto_draft_enabled")
