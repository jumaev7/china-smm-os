"""Factory Partner Platform v1 — tenant company workspace profiles."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260721_add_factory_platform"
down_revision = "20260720_add_subscription_billing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "factory_platform_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("company_description", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=100), nullable=True),
        sa.Column("markets", JSONB(), nullable=True),
        sa.Column("industries", JSONB(), nullable=True),
        sa.Column("export_regions", JSONB(), nullable=True),
        sa.Column("product_categories", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_factory_platform_profiles_tenant_id",
        "factory_platform_profiles",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_factory_platform_profiles_company_id",
        "factory_platform_profiles",
        ["company_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_factory_platform_profiles_company_id", table_name="factory_platform_profiles")
    op.drop_index("ix_factory_platform_profiles_tenant_id", table_name="factory_platform_profiles")
    op.drop_table("factory_platform_profiles")
