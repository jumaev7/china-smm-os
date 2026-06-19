"""Product catalog and import jobs."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260617_add_product_catalog"
down_revision = "20260616_fix_crm_lead_attribution_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "products",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("sku", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("moq", sa.Integer(), nullable=True),
        sa.Column("unit_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
        sa.Column("attributes_json", JSONB(), nullable=True),
        sa.Column("images_json", JSONB(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_products_client_id", "products", ["client_id"])
    create_index_if_missing("ix_products_name", "products", ["name"])
    create_index_if_missing("ix_products_sku", "products", ["sku"])
    create_index_if_missing("ix_products_category", "products", ["category"])
    create_index_if_missing("ix_products_active", "products", ["active"])

    create_table_if_missing(
        "product_import_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(length=20), nullable=False),
        sa.Column("source_file", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("result_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_product_import_jobs_client_id", "product_import_jobs", ["client_id"])
    create_index_if_missing("ix_product_import_jobs_status", "product_import_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_product_import_jobs_status", table_name="product_import_jobs")
    op.drop_index("ix_product_import_jobs_client_id", table_name="product_import_jobs")
    op.drop_table("product_import_jobs")
    op.drop_index("ix_products_active", table_name="products")
    op.drop_index("ix_products_category", table_name="products")
    op.drop_index("ix_products_sku", table_name="products")
    op.drop_index("ix_products_name", table_name="products")
    op.drop_index("ix_products_client_id", table_name="products")
    op.drop_table("products")
