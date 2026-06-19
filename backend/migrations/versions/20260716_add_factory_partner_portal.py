"""Factory Partner Portal v1 — onboarding applications."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260716_add_factory_partner_portal"
down_revision = "20260715_add_whatsapp_sync"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "factory_partner_applications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("contact_name", sa.String(length=255), nullable=True),
        sa.Column("contact_phone", sa.String(length=100), nullable=True),
        sa.Column("contact_wechat", sa.String(length=100), nullable=True),
        sa.Column("contact_whatsapp", sa.String(length=100), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("product_categories", JSONB(), nullable=True),
        sa.Column("company_description", sa.Text(), nullable=True),
        sa.Column(
            "cooperation_terms_accepted",
            sa.Boolean(),
            nullable=False,
            server_default="false",
        ),
        sa.Column("commission_model", sa.String(length=80), nullable=True),
        sa.Column("target_markets", JSONB(), nullable=True),
        sa.Column("documents", JSONB(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_factory_partner_applications_company_name",
        "factory_partner_applications",
        ["company_name"],
    )
    create_index_if_missing(
        "ix_factory_partner_applications_country",
        "factory_partner_applications",
        ["country"],
    )
    create_index_if_missing(
        "ix_factory_partner_applications_status",
        "factory_partner_applications",
        ["status"],
    )
    create_index_if_missing(
        "ix_factory_partner_applications_created_client_id",
        "factory_partner_applications",
        ["created_client_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_factory_partner_applications_created_client_id",
        table_name="factory_partner_applications",
    )
    op.drop_index(
        "ix_factory_partner_applications_status",
        table_name="factory_partner_applications",
    )
    op.drop_index(
        "ix_factory_partner_applications_country",
        table_name="factory_partner_applications",
    )
    op.drop_index(
        "ix_factory_partner_applications_company_name",
        table_name="factory_partner_applications",
    )
    op.drop_table("factory_partner_applications")
