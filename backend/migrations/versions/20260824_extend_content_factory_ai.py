"""Extend Content Factory for AI pipeline — text input, review status, quality scores."""
import sqlalchemy as sa
from alembic import op

from migrations.helpers import add_column_if_missing, create_index_if_missing, drop_column_if_exists

revision = "20260824_extend_content_factory_ai"
down_revision = "20260823_add_whatsapp_business_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "content_factories",
        sa.Column("input_type", sa.String(20), nullable=True, server_default="image"),
    )
    add_column_if_missing(
        "content_factories",
        sa.Column("input_text", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_factories",
        sa.Column("content_category", sa.String(50), nullable=True),
    )
    add_column_if_missing(
        "content_factories",
        sa.Column("target_languages_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_factories",
        sa.Column("metadata_json", sa.Text(), nullable=True),
    )

    # Allow text-only factory runs without media
    op.alter_column(
        "content_factories",
        "source_media_id",
        existing_type=sa.dialects.postgresql.UUID(as_uuid=True),
        nullable=True,
    )

    add_column_if_missing(
        "content_factory_items",
        sa.Column("review_status", sa.String(30), nullable=True, server_default="generated"),
    )
    add_column_if_missing(
        "content_factory_items",
        sa.Column("headline", sa.String(500), nullable=True),
    )
    add_column_if_missing(
        "content_factory_items",
        sa.Column("cta_suggestion", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_factory_items",
        sa.Column("quality_scores_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_factory_items",
        sa.Column("platform_variants_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_factory_items",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )

    create_index_if_missing(
        "ix_content_factory_items_review_status",
        "content_factory_items",
        ["review_status"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_factory_items_review_status", table_name="content_factory_items")
    for col in ("scheduled_for", "platform_variants_json", "quality_scores_json", "cta_suggestion", "headline", "review_status"):
        drop_column_if_exists("content_factory_items", col)
    for col in ("metadata_json", "target_languages_json", "content_category", "input_text", "input_type"):
        drop_column_if_exists("content_factories", col)
