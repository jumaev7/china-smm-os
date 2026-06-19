"""Client brief intake table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260811_add_client_briefs"
down_revision = "20260731_factory_platform_v2_management"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "client_briefs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("target_market", sa.String(length=255), nullable=False),
        sa.Column("campaign_goal", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False, server_default="en"),
        sa.Column("desired_platforms", JSON(), nullable=True),
        sa.Column("media_urls", JSON(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="submitted"),
        sa.Column("ai_content_plan", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_client_briefs_client_id", "client_briefs", ["client_id"])
    create_index_if_missing("ix_client_briefs_tenant_id", "client_briefs", ["tenant_id"])
    create_index_if_missing("ix_client_briefs_status", "client_briefs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_client_briefs_status", table_name="client_briefs")
    op.drop_index("ix_client_briefs_tenant_id", table_name="client_briefs")
    op.drop_index("ix_client_briefs_client_id", table_name="client_briefs")
    op.drop_table("client_briefs")
