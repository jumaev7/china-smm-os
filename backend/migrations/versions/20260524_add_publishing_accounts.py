"""Add publishing_accounts and publish_attempts tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260524_add_publishing_accounts"
down_revision = "20260523_add_client_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "publishing_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("account_name", sa.String(length=255), nullable=False),
        sa.Column("account_id", sa.String(length=255), nullable=False),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="mock", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_publishing_accounts_platform", "publishing_accounts", ["platform"])

    create_table_if_missing(
        "publish_attempts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), sa.ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_publish_attempts_content_id", "publish_attempts", ["content_id"])


def downgrade() -> None:
    op.drop_index("ix_publish_attempts_content_id", table_name="publish_attempts")
    op.drop_table("publish_attempts")
    op.drop_index("ix_publishing_accounts_platform", table_name="publishing_accounts")
    op.drop_table("publishing_accounts")
