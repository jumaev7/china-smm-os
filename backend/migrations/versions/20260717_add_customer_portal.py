"""Customer Portal v1 — factory partner portal accounts."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260717_add_customer_portal"
down_revision = "20260716_add_factory_partner_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "customer_portal_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "company_id",
            UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("portal_status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("owner_user", sa.String(length=255), nullable=True),
        sa.Column(
            "factory_partner_application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("factory_partner_applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_customer_portal_accounts_company_id",
        "customer_portal_accounts",
        ["company_id"],
    )
    create_index_if_missing(
        "ix_customer_portal_accounts_portal_status",
        "customer_portal_accounts",
        ["portal_status"],
    )
    create_index_if_missing(
        "ix_customer_portal_accounts_factory_partner_application_id",
        "customer_portal_accounts",
        ["factory_partner_application_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_portal_accounts_factory_partner_application_id",
        table_name="customer_portal_accounts",
    )
    op.drop_index(
        "ix_customer_portal_accounts_portal_status",
        table_name="customer_portal_accounts",
    )
    op.drop_index(
        "ix_customer_portal_accounts_company_id",
        table_name="customer_portal_accounts",
    )
    op.drop_table("customer_portal_accounts")
