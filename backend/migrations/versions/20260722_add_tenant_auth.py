"""Tenant Authentication & Access Control v1 — password and refresh token columns."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import add_column_if_missing

revision = "20260722_add_tenant_auth"
down_revision = "20260721_add_factory_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "tenant_users",
        sa.Column("password_hash", sa.String(length=255), nullable=True),
    )
    add_column_if_missing(
        "tenant_users",
        sa.Column("refresh_token_hash", sa.String(length=128), nullable=True),
    )
    add_column_if_missing(
        "tenant_users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_users",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_users", "updated_at")
    op.drop_column("tenant_users", "last_login_at")
    op.drop_column("tenant_users", "refresh_token_hash")
    op.drop_column("tenant_users", "password_hash")
