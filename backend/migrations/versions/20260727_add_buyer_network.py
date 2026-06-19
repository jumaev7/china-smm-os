"""Export Buyer Network v1 — global buyer profiles and tenant relationships."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260727_add_buyer_network"
down_revision = "20260726_add_marketplace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "buyer_network_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("classification", sa.String(length=30), nullable=False, server_default="discovered"),
        sa.Column("opportunity_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("network_strength", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buyer_status", sa.String(length=30), nullable=False, server_default="watchlist"),
        sa.Column("score_factors_json", JSONB(), nullable=True),
        sa.Column("source_key", sa.String(length=255), nullable=True),
        sa.Column("recalculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_buyer_network_profiles_company_name",
        "buyer_network_profiles",
        ["company_name"],
    )
    create_index_if_missing(
        "ix_buyer_network_profiles_country",
        "buyer_network_profiles",
        ["country"],
    )
    create_index_if_missing(
        "ix_buyer_network_profiles_industry",
        "buyer_network_profiles",
        ["industry"],
    )
    create_index_if_missing(
        "ix_buyer_network_profiles_classification",
        "buyer_network_profiles",
        ["classification"],
    )
    create_index_if_missing(
        "ix_buyer_network_profiles_buyer_status",
        "buyer_network_profiles",
        ["buyer_status"],
    )
    create_index_if_missing(
        "ix_buyer_network_profiles_source_key",
        "buyer_network_profiles",
        ["source_key"],
    )

    create_table_if_missing(
        "buyer_relationships",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "buyer_id",
            UUID(as_uuid=True),
            sa.ForeignKey("buyer_network_profiles.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(length=30), nullable=False),
        sa.Column("relationship_strength", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_buyer_relationships_buyer_id",
        "buyer_relationships",
        ["buyer_id"],
    )
    create_index_if_missing(
        "ix_buyer_relationships_tenant_id",
        "buyer_relationships",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_buyer_relationships_relationship_type",
        "buyer_relationships",
        ["relationship_type"],
    )


def downgrade() -> None:
    op.drop_table("buyer_relationships")
    op.drop_table("buyer_network_profiles")
