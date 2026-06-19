"""Content Factory tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260607_add_content_factory"
down_revision = "20260606_add_task_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "content_factories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_media_id", UUID(as_uuid=True), sa.ForeignKey("media_files.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="generated"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_content_factories_client_id", "content_factories", ["client_id"])

    create_table_if_missing(
        "content_factory_items",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("factory_id", UUID(as_uuid=True), sa.ForeignKey("content_factories.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_type", sa.String(length=20), nullable=False),
        sa.Column("theme", sa.String(length=500), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("platforms_json", sa.Text(), nullable=True),
        sa.Column("hashtags", sa.Text(), nullable=True),
        sa.Column("preview_caption", sa.Text(), nullable=True),
        sa.Column("captions_json", sa.Text(), nullable=True),
        sa.Column("generated_content_id", UUID(as_uuid=True), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_content_factory_items_factory_id", "content_factory_items", ["factory_id"])


def downgrade() -> None:
    op.drop_index("ix_content_factory_items_factory_id", table_name="content_factory_items")
    op.drop_table("content_factory_items")
    op.drop_index("ix_content_factories_client_id", table_name="content_factories")
    op.drop_table("content_factories")
