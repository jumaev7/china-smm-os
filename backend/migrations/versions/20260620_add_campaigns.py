"""Campaigns — group content items under marketing campaigns."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing, drop_column_if_exists

revision = "20260620_add_campaigns"
down_revision = "20260619_add_export_agent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "campaigns",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_campaigns_client_id", "campaigns", ["client_id"])
    create_index_if_missing("ix_campaigns_name", "campaigns", ["name"])
    create_index_if_missing("ix_campaigns_status", "campaigns", ["status"])

    add_column_if_missing(
        "content_items",
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
    )
    create_index_if_missing("ix_content_items_campaign_id", "content_items", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_content_items_campaign_id", table_name="content_items")
    drop_column_if_exists("content_items", "campaign_id")
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_index("ix_campaigns_name", table_name="campaigns")
    op.drop_index("ix_campaigns_client_id", table_name="campaigns")
    op.drop_table("campaigns")
