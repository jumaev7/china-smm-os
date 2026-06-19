"""WhatsApp Business Integration Foundation — tenant-scoped accounts, contact city field."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260823_add_whatsapp_business_foundation"
down_revision = "20260822_add_wechat_business_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "whatsapp_sync_accounts",
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    create_index_if_missing(
        "ix_whatsapp_sync_accounts_tenant_id",
        "whatsapp_sync_accounts",
        ["tenant_id"],
    )
    add_column_if_missing(
        "whatsapp_sync_accounts",
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "whatsapp_sync_accounts",
        sa.Column("business_display_name", sa.String(length=255), nullable=True),
    )
    add_column_if_missing(
        "communication_contacts",
        sa.Column("city", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("communication_contacts", "city")
    op.drop_column("whatsapp_sync_accounts", "business_display_name")
    op.drop_column("whatsapp_sync_accounts", "connected_at")
    op.drop_column("whatsapp_sync_accounts", "tenant_id")
