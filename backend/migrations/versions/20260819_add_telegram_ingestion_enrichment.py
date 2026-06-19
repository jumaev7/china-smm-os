"""Telegram ingestion enrichment: content fields, album buffer, settings."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    add_column_if_missing,
    create_index_if_missing,
    create_table_if_missing,
    drop_table_if_exists,
    table_exists,
)

revision = "20260819_add_telegram_ingestion_enrichment"
down_revision = "20260818_add_business_matching"
branch_labels = None
depends_on = None

DEFAULT_SETTINGS_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    add_column_if_missing(
        "content_items",
        sa.Column("telegram_original_caption", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("content_classification", sa.String(50), nullable=True),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("suggestions_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("quality_warnings_json", sa.Text(), nullable=True),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("telegram_media_group_id", sa.String(50), nullable=True),
    )
    add_column_if_missing(
        "content_items",
        sa.Column("telegram_forward_from", sa.String(255), nullable=True),
    )

    create_table_if_missing(
        "telegram_album_pending",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.String(50), nullable=False),
        sa.Column("media_group_id", sa.String(50), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("media_file_id", UUID(as_uuid=True), sa.ForeignKey("media_files.id", ondelete="SET NULL"), nullable=True),
        sa.Column("caption", sa.Text(), nullable=True),
        sa.Column("message_type", sa.String(20), nullable=False),
        sa.Column("refs_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("group_id", "message_id", name="uq_tg_album_group_message"),
    )
    create_index_if_missing(
        "ix_tg_album_pending_group_media",
        "telegram_album_pending",
        ["group_id", "media_group_id"],
    )

    create_table_if_missing(
        "telegram_ingestion_settings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("allowed_group_ids", JSONB(), nullable=True),
        sa.Column("default_tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("default_status", sa.String(30), server_default="needs_review", nullable=False),
        sa.Column("default_target_languages", JSONB(), nullable=True),
        sa.Column("auto_classification", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("auto_enrichment", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("quality_checks_enabled", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    if table_exists("telegram_ingestion_settings"):
        op.execute(
            sa.text(
                f"INSERT INTO telegram_ingestion_settings (id, enabled, default_status, default_target_languages) "
                f"VALUES ('{DEFAULT_SETTINGS_ID}', true, 'needs_review', '[\"ru\",\"uz\",\"en\",\"zh\"]'::jsonb) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )


def downgrade() -> None:
    drop_table_if_exists("telegram_ingestion_settings")
    drop_table_if_exists("telegram_album_pending")
    for col in (
        "telegram_forward_from",
        "telegram_media_group_id",
        "quality_warnings_json",
        "suggestions_json",
        "content_classification",
        "telegram_original_caption",
    ):
        from migrations.helpers import drop_column_if_exists
        drop_column_if_exists("content_items", col)
