"""Add operator user settings for UI language preference."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import (
    add_column_if_missing,
    create_table_if_missing,
    drop_table_if_exists,
    table_exists,
)

revision = "20260703_add_operator_user_settings"
down_revision = "20260702_add_proposal_workflow_fields"
branch_labels = None
depends_on = None

DEFAULT_USER_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    create_table_if_missing(
        "operator_users",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="ru"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    add_column_if_missing(
        "operator_users",
        sa.Column("preferred_language", sa.String(10), nullable=False, server_default="ru"),
    )
    if table_exists("operator_users"):
        op.execute(
            sa.text(
                f"INSERT INTO operator_users (id, preferred_language) "
                f"VALUES ('{DEFAULT_USER_ID}', 'ru') "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


def downgrade() -> None:
    drop_table_if_exists("operator_users")
