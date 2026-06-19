"""Ensure tenant_id ownership columns exist (idempotent fix)."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260719_ensure_tenant_columns"
down_revision = "20260718_add_multi_tenant"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "clients",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
    )
    create_index_if_missing("ix_clients_tenant_id", "clients", ["tenant_id"])

    add_column_if_missing(
        "customer_portal_accounts",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
    )
    create_index_if_missing(
        "ix_customer_portal_accounts_tenant_id",
        "customer_portal_accounts",
        ["tenant_id"],
    )

    add_column_if_missing(
        "factory_partner_applications",
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True),
    )
    create_index_if_missing(
        "ix_factory_partner_applications_tenant_id",
        "factory_partner_applications",
        ["tenant_id"],
    )


def downgrade() -> None:
    pass
