"""WeChat Business Integration Foundation — tenant-scoped accounts, contact CRM fields."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260822_add_wechat_business_foundation"
down_revision = "20260821_add_tenant_onboarding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "wechat_sync_accounts",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    create_index_if_missing(
        "ix_wechat_sync_accounts_tenant_id",
        "wechat_sync_accounts",
        ["tenant_id"],
    )
    add_column_if_missing(
        "wechat_sync_accounts",
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
    )

    for col_name, fk_table in (
        ("buyer_id", "buyers"),
        ("customer_id", "sales_customers"),
    ):
        add_column_if_missing(
            "communication_contacts",
            sa.Column(
                col_name,
                UUID(as_uuid=True),
                sa.ForeignKey(f"{fk_table}.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        create_index_if_missing(
            f"ix_communication_contacts_{col_name}",
            "communication_contacts",
            [col_name],
        )

    add_column_if_missing(
        "communication_contacts",
        sa.Column("industry", sa.String(length=100), nullable=True),
    )
    add_column_if_missing(
        "communication_contacts",
        sa.Column("tags_json", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("communication_contacts", "tags_json")
    op.drop_column("communication_contacts", "industry")
    op.drop_column("communication_contacts", "customer_id")
    op.drop_column("communication_contacts", "buyer_id")
    op.drop_column("wechat_sync_accounts", "connected_at")
    op.drop_column("wechat_sync_accounts", "tenant_id")
