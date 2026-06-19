"""Marketplace & Lead Exchange v1 — opportunities and tenant participation."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260726_add_marketplace"
down_revision = "20260725_add_whatsapp_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "marketplace_opportunities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("buyer_company", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("opportunity_type", sa.String(length=30), nullable=False),
        sa.Column("estimated_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        sa.Column("visibility", sa.String(length=20), nullable=False, server_default="public"),
        sa.Column(
            "created_by_tenant",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("rank_score", sa.Integer(), nullable=False, server_default="0"),
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
    for col in ("country", "industry", "opportunity_type", "status", "visibility", "created_by_tenant"):
        create_index_if_missing(
            f"ix_marketplace_opportunities_{col}",
            "marketplace_opportunities",
            [col],
        )

    create_table_if_missing(
        "marketplace_opportunity_views",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("marketplace_opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "viewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_marketplace_opportunity_views_opportunity_id",
        "marketplace_opportunity_views",
        ["opportunity_id"],
    )
    create_index_if_missing(
        "ix_marketplace_opportunity_views_tenant_id",
        "marketplace_opportunity_views",
        ["tenant_id"],
    )

    create_table_if_missing(
        "marketplace_opportunity_interests",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("marketplace_opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "expressed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_marketplace_opportunity_interests_opportunity_id",
        "marketplace_opportunity_interests",
        ["opportunity_id"],
    )
    create_index_if_missing(
        "ix_marketplace_opportunity_interests_tenant_id",
        "marketplace_opportunity_interests",
        ["tenant_id"],
    )

    create_table_if_missing(
        "marketplace_opportunity_claims",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=True),
            sa.ForeignKey("marketplace_opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    create_index_if_missing(
        "ix_marketplace_opportunity_claims_opportunity_id",
        "marketplace_opportunity_claims",
        ["opportunity_id"],
    )
    create_index_if_missing(
        "ix_marketplace_opportunity_claims_tenant_id",
        "marketplace_opportunity_claims",
        ["tenant_id"],
    )


def downgrade() -> None:
    op.drop_table("marketplace_opportunity_claims")
    op.drop_table("marketplace_opportunity_interests")
    op.drop_table("marketplace_opportunity_views")
    op.drop_table("marketplace_opportunities")
