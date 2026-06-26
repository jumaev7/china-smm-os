"""Meta Graph API publishing foundation — OAuth tokens, page/IG linkage on publishing_accounts."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import add_column_if_missing

revision = "20260826_add_meta_publishing_foundation"
down_revision = "20260825_add_platform_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "publishing_accounts",
        sa.Column("refresh_token_encrypted", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "publishing_accounts",
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "publishing_accounts",
        sa.Column("facebook_page_id", sa.String(length=64), nullable=True),
    )
    add_column_if_missing(
        "publishing_accounts",
        sa.Column("instagram_business_account_id", sa.String(length=64), nullable=True),
    )
    add_column_if_missing(
        "publishing_accounts",
        sa.Column("permissions_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "publishing_accounts",
        sa.Column("account_metadata_json", sa.Text(), nullable=True),
    )
    op.alter_column(
        "publishing_accounts",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=30),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "publishing_accounts",
        "status",
        existing_type=sa.String(length=30),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.drop_column("publishing_accounts", "account_metadata_json")
    op.drop_column("publishing_accounts", "permissions_json")
    op.drop_column("publishing_accounts", "instagram_business_account_id")
    op.drop_column("publishing_accounts", "facebook_page_id")
    op.drop_column("publishing_accounts", "expires_at")
    op.drop_column("publishing_accounts", "refresh_token_encrypted")
