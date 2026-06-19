"""Export Agent — opportunities and insights."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260619_add_export_agent"
down_revision = "20260618_add_partner_network_hub"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "export_opportunities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"),
        sa.Column("market_summary", sa.Text(), nullable=True),
        sa.Column("demand_level", sa.String(length=20), nullable=True),
        sa.Column("recommended_partner_types_json", JSONB(), nullable=True),
        sa.Column("recommended_channels_json", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_export_opportunities_client_id", "export_opportunities", ["client_id"])
    create_index_if_missing("ix_export_opportunities_product_id", "export_opportunities", ["product_id"])
    create_index_if_missing("ix_export_opportunities_country", "export_opportunities", ["country"])
    create_index_if_missing("ix_export_opportunities_score", "export_opportunities", ["score"])

    create_table_if_missing(
        "export_insights",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("insight_type", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_export_insights_product_id", "export_insights", ["product_id"])
    create_index_if_missing("ix_export_insights_insight_type", "export_insights", ["insight_type"])


def downgrade() -> None:
    op.drop_index("ix_export_insights_insight_type", table_name="export_insights")
    op.drop_index("ix_export_insights_product_id", table_name="export_insights")
    op.drop_table("export_insights")
    op.drop_index("ix_export_opportunities_score", table_name="export_opportunities")
    op.drop_index("ix_export_opportunities_country", table_name="export_opportunities")
    op.drop_index("ix_export_opportunities_product_id", table_name="export_opportunities")
    op.drop_index("ix_export_opportunities_client_id", table_name="export_opportunities")
    op.drop_table("export_opportunities")
