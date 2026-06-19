"""Factory Platform v2 management — catalog fields, certificates, media center."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260731_factory_platform_v2_management"
down_revision = "20260730_add_factory_platform_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "factory_platform_profiles",
        sa.Column("logo_url", sa.String(length=500), nullable=True),
    )
    add_column_if_missing(
        "factory_platform_profiles",
        sa.Column("factory_video_url", sa.String(length=500), nullable=True),
    )

    add_column_if_missing(
        "factory_catalog_products",
        sa.Column("image_url", sa.String(length=500), nullable=True),
    )
    add_column_if_missing(
        "factory_catalog_products",
        sa.Column("moq", sa.Integer(), nullable=True),
    )
    add_column_if_missing(
        "factory_catalog_products",
        sa.Column("price_min", sa.Numeric(12, 2), nullable=True),
    )
    add_column_if_missing(
        "factory_catalog_products",
        sa.Column("price_max", sa.Numeric(12, 2), nullable=True),
    )
    add_column_if_missing(
        "factory_catalog_products",
        sa.Column("currency", sa.String(length=10), nullable=True, server_default="USD"),
    )
    add_column_if_missing(
        "factory_catalog_products",
        sa.Column("export_available", sa.Boolean(), nullable=False, server_default="true"),
    )

    add_column_if_missing(
        "factory_certificates",
        sa.Column("certificate_number", sa.String(length=100), nullable=True),
    )
    add_column_if_missing(
        "factory_certificates",
        sa.Column("issue_date", sa.Date(), nullable=True),
    )
    add_column_if_missing(
        "factory_certificates",
        sa.Column("document_url", sa.String(length=500), nullable=True),
    )

    create_table_if_missing(
        "factory_media_assets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "media_file_id",
            UUID(as_uuid=True),
            sa.ForeignKey("media_files.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("storage_path", sa.String(length=500), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("reusable_modules", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_factory_media_assets_tenant_id",
        "factory_media_assets",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_factory_media_assets_tenant_id", table_name="factory_media_assets")
    op.drop_table("factory_media_assets")
    op.drop_column("factory_certificates", "document_url")
    op.drop_column("factory_certificates", "issue_date")
    op.drop_column("factory_certificates", "certificate_number")
    op.drop_column("factory_catalog_products", "export_available")
    op.drop_column("factory_catalog_products", "currency")
    op.drop_column("factory_catalog_products", "price_max")
    op.drop_column("factory_catalog_products", "price_min")
    op.drop_column("factory_catalog_products", "moq")
    op.drop_column("factory_catalog_products", "image_url")
    op.drop_column("factory_platform_profiles", "factory_video_url")
    op.drop_column("factory_platform_profiles", "logo_url")
