"""Export Buyer Discovery Engine v1 — buyer registry for factory partner discovery."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260724_add_buyer_discovery"
down_revision = "20260723_add_wechat_provider"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "buyer_discovery_entries",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "crm_lead_id",
            UUID(as_uuid=True),
            sa.ForeignKey("crm_leads.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("website", sa.String(length=500), nullable=True),
        sa.Column("contact_status", sa.String(length=30), nullable=False, server_default="unknown"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="crm_sync"),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("opportunity_score", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("category", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("pipeline_stage", sa.String(length=30), nullable=False, server_default="discovered"),
        sa.Column("score_factors_json", JSONB(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        "ix_buyer_discovery_entries_client_id",
        "buyer_discovery_entries",
        ["client_id"],
    )
    create_index_if_missing(
        "ix_buyer_discovery_entries_crm_lead_id",
        "buyer_discovery_entries",
        ["crm_lead_id"],
    )
    create_index_if_missing(
        "ix_buyer_discovery_entries_country",
        "buyer_discovery_entries",
        ["country"],
    )
    create_index_if_missing(
        "ix_buyer_discovery_entries_industry",
        "buyer_discovery_entries",
        ["industry"],
    )
    create_index_if_missing(
        "ix_buyer_discovery_entries_category",
        "buyer_discovery_entries",
        ["category"],
    )
    create_index_if_missing(
        "ix_buyer_discovery_entries_pipeline_stage",
        "buyer_discovery_entries",
        ["pipeline_stage"],
    )


def downgrade() -> None:
    op.drop_table("buyer_discovery_entries")
