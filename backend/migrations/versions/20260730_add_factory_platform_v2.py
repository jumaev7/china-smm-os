"""Factory Platform v2 — profile extensions, catalog, certificates, export markets."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260730_add_factory_platform_v2"
down_revision = "20260729_admin_security_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "factory_platform_profiles",
        sa.Column("brand_name", sa.String(length=255), nullable=True),
    )
    add_column_if_missing(
        "factory_platform_profiles",
        sa.Column("address", sa.String(length=500), nullable=True),
    )
    add_column_if_missing(
        "factory_platform_profiles",
        sa.Column("founded_year", sa.Integer(), nullable=True),
    )
    add_column_if_missing(
        "factory_platform_profiles",
        sa.Column("employee_count", sa.Integer(), nullable=True),
    )
    add_column_if_missing(
        "factory_platform_profiles",
        sa.Column(
            "verification_status",
            sa.String(length=20),
            nullable=False,
            server_default="unverified",
        ),
    )

    create_table_if_missing(
        "factory_catalog_products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("product_name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("target_markets", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_factory_catalog_products_tenant_id",
        "factory_catalog_products",
        ["tenant_id"],
    )

    create_table_if_missing(
        "factory_certificates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("certificate_name", sa.String(length=255), nullable=False),
        sa.Column("certificate_type", sa.String(length=50), nullable=False),
        sa.Column("issuing_authority", sa.String(length=255), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_factory_certificates_tenant_id",
        "factory_certificates",
        ["tenant_id"],
    )

    create_table_if_missing(
        "factory_export_markets",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("market_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_buyers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("opportunities", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_factory_export_markets_tenant_id",
        "factory_export_markets",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_factory_export_markets_tenant_id", table_name="factory_export_markets")
    op.drop_table("factory_export_markets")
    op.drop_index("ix_factory_certificates_tenant_id", table_name="factory_certificates")
    op.drop_table("factory_certificates")
    op.drop_index("ix_factory_catalog_products_tenant_id", table_name="factory_catalog_products")
    op.drop_table("factory_catalog_products")
    op.drop_column("factory_platform_profiles", "verification_status")
    op.drop_column("factory_platform_profiles", "employee_count")
    op.drop_column("factory_platform_profiles", "founded_year")
    op.drop_column("factory_platform_profiles", "address")
    op.drop_column("factory_platform_profiles", "brand_name")
