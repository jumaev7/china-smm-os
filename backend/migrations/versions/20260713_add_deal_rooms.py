"""AI Deal Room v1 — deal_rooms table."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260713_add_deal_rooms"
down_revision = "20260712_add_sales_workflow"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "deal_rooms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "crm_client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("deal_name", sa.String(length=255), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False, server_default="new"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("probability", sa.Integer(), nullable=False, server_default="10"),
        sa.Column("expected_value", sa.Numeric(12, 2), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_deal_rooms_crm_client_id", "deal_rooms", ["crm_client_id"])
    create_index_if_missing("ix_deal_rooms_stage", "deal_rooms", ["stage"])
    create_index_if_missing("ix_deal_rooms_status", "deal_rooms", ["status"])


def downgrade() -> None:
    op.drop_index("ix_deal_rooms_status", table_name="deal_rooms")
    op.drop_index("ix_deal_rooms_stage", table_name="deal_rooms")
    op.drop_index("ix_deal_rooms_crm_client_id", table_name="deal_rooms")
    op.drop_table("deal_rooms")
