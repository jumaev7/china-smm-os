"""Buyer Finder — product buyer recommendations."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260626_add_buyer_finder"
down_revision = "20260625_add_landing_pages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "buyer_recommendations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("product_id", UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recommendation_type", sa.String(length=30), nullable=False),
        sa.Column("reference_id", UUID(as_uuid=True), nullable=True),
        sa.Column("score", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_buyer_recommendations_client_id", "buyer_recommendations", ["client_id"])
    create_index_if_missing("ix_buyer_recommendations_product_id", "buyer_recommendations", ["product_id"])
    create_index_if_missing("ix_buyer_recommendations_type", "buyer_recommendations", ["recommendation_type"])
    create_index_if_missing("ix_buyer_recommendations_reference_id", "buyer_recommendations", ["reference_id"])
    create_index_if_missing("ix_buyer_recommendations_country", "buyer_recommendations", ["country"])


def downgrade() -> None:
    op.drop_index("ix_buyer_recommendations_country", table_name="buyer_recommendations")
    op.drop_index("ix_buyer_recommendations_reference_id", table_name="buyer_recommendations")
    op.drop_index("ix_buyer_recommendations_type", table_name="buyer_recommendations")
    op.drop_index("ix_buyer_recommendations_product_id", table_name="buyer_recommendations")
    op.drop_index("ix_buyer_recommendations_client_id", table_name="buyer_recommendations")
    op.drop_table("buyer_recommendations")
