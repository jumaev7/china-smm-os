"""Add Business Matching Center opportunity table."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260818_add_business_matching"
down_revision = "20260817_add_communication_hub_mvp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "business_matching_opportunities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("opportunity_type", sa.String(30), nullable=False),
        sa.Column("buyer_id", UUID(as_uuid=True), sa.ForeignKey("buyers.id", ondelete="SET NULL"), nullable=True),
        sa.Column("supplier_tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("confidence_score", sa.Integer(), server_default="0", nullable=False),
        sa.Column("estimated_value", sa.Numeric(18, 2), nullable=True),
        sa.Column("status", sa.String(20), server_default="new", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("match_factors", JSONB(), nullable=True),
        sa.Column("match_reasoning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    create_index_if_missing("ix_bmo_tenant_id", "business_matching_opportunities", ["tenant_id"])
    create_index_if_missing("ix_bmo_opportunity_type", "business_matching_opportunities", ["opportunity_type"])
    create_index_if_missing("ix_bmo_buyer_id", "business_matching_opportunities", ["buyer_id"])
    create_index_if_missing("ix_bmo_supplier_tenant_id", "business_matching_opportunities", ["supplier_tenant_id"])
    create_index_if_missing("ix_bmo_status", "business_matching_opportunities", ["status"])


def downgrade() -> None:
    op.drop_table("business_matching_opportunities")
