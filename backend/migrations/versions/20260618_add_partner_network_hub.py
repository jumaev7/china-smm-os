"""Partner network hub — directory fields, interests, activities."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing, drop_column_if_exists

revision = "20260618_add_partner_network_hub"
down_revision = "20260617_add_product_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing("partners", sa.Column("company_name", sa.String(length=255), nullable=True))
    add_column_if_missing("partners", sa.Column("country", sa.String(length=100), nullable=True))
    add_column_if_missing("partners", sa.Column("city", sa.String(length=100), nullable=True))
    add_column_if_missing("partners", sa.Column("partner_type", sa.String(length=40), nullable=True))
    add_column_if_missing("partners", sa.Column("industries_json", JSONB(), nullable=True))
    add_column_if_missing("partners", sa.Column("website", sa.String(length=500), nullable=True))
    op.execute("UPDATE partners SET company_name = company WHERE company_name IS NULL AND company IS NOT NULL")
    create_index_if_missing("ix_partners_country", "partners", ["country"])
    create_index_if_missing("ix_partners_partner_type", "partners", ["partner_type"])

    create_table_if_missing(
        "partner_product_interests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("interest_score", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_partner_product_interests_partner_id", "partner_product_interests", ["partner_id"])
    create_index_if_missing("ix_partner_product_interests_product_id", "partner_product_interests", ["product_id"])

    create_table_if_missing(
        "partner_activities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("partner_id", UUID(as_uuid=True), sa.ForeignKey("partners.id", ondelete="CASCADE"), nullable=False),
        sa.Column("activity_type", sa.String(length=30), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_partner_activities_partner_id", "partner_activities", ["partner_id"])
    create_index_if_missing("ix_partner_activities_activity_type", "partner_activities", ["activity_type"])


def downgrade() -> None:
    op.drop_index("ix_partner_activities_activity_type", table_name="partner_activities")
    op.drop_index("ix_partner_activities_partner_id", table_name="partner_activities")
    op.drop_table("partner_activities")
    op.drop_index("ix_partner_product_interests_product_id", table_name="partner_product_interests")
    op.drop_index("ix_partner_product_interests_partner_id", table_name="partner_product_interests")
    op.drop_table("partner_product_interests")
    op.drop_index("ix_partners_partner_type", table_name="partners")
    op.drop_index("ix_partners_country", table_name="partners")
    drop_column_if_exists("partners", "website")
    drop_column_if_exists("partners", "industries_json")
    drop_column_if_exists("partners", "partner_type")
    drop_column_if_exists("partners", "city")
    drop_column_if_exists("partners", "country")
    drop_column_if_exists("partners", "company_name")
