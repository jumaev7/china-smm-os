"""Content repurposing lineage — parent content/media links."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, drop_column_if_exists

revision = "20260622_add_content_repurpose_lineage"
down_revision = "20260621_add_media_library"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "content_items",
        sa.Column(
            "parent_content_id",
            UUID(as_uuid=True),
            sa.ForeignKey("content_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    add_column_if_missing(
        "content_items",
        sa.Column(
            "parent_media_asset_id",
            UUID(as_uuid=True),
            sa.ForeignKey("media_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    create_index_if_missing("ix_content_items_parent_content_id", "content_items", ["parent_content_id"])
    create_index_if_missing("ix_content_items_parent_media_asset_id", "content_items", ["parent_media_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_content_items_parent_media_asset_id", table_name="content_items")
    op.drop_index("ix_content_items_parent_content_id", table_name="content_items")
    drop_column_if_exists("content_items", "parent_media_asset_id")
    drop_column_if_exists("content_items", "parent_content_id")
