"""Media library assets linked to existing media_files storage."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260621_add_media_library"
down_revision = "20260620_add_campaigns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "media_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", UUID(as_uuid=True), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("media_file_id", UUID(as_uuid=True), sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("file_type", sa.String(length=20), nullable=False),
        sa.Column("original_filename", sa.String(length=500), nullable=False),
        sa.Column("storage_path", sa.String(length=1000), nullable=False),
        sa.Column("tags_json", JSONB(), nullable=True),
        sa.Column("ai_labels_json", JSONB(), nullable=True),
        sa.Column("uploaded_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_media_assets_client_id", "media_assets", ["client_id"])
    create_index_if_missing("ix_media_assets_campaign_id", "media_assets", ["campaign_id"])
    create_index_if_missing("ix_media_assets_file_type", "media_assets", ["file_type"])
    create_index_if_missing("ix_media_assets_media_file_id", "media_assets", ["media_file_id"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_media_file_id", table_name="media_assets")
    op.drop_index("ix_media_assets_file_type", table_name="media_assets")
    op.drop_index("ix_media_assets_campaign_id", table_name="media_assets")
    op.drop_index("ix_media_assets_client_id", table_name="media_assets")
    op.drop_table("media_assets")
