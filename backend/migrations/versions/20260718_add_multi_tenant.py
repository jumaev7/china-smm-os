"""Multi-Tenant SaaS Foundation v1 — tenants, tenant_users, ownership columns."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260718_add_multi_tenant"
down_revision = "20260717_add_customer_portal"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("plan", sa.String(length=30), nullable=False, server_default="starter"),
        sa.Column(
            "factory_partner_application_id",
            UUID(as_uuid=True),
            sa.ForeignKey("factory_partner_applications.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_tenants_company_name", "tenants", ["company_name"])
    create_index_if_missing("ix_tenants_status", "tenants", ["status"])
    create_index_if_missing(
        "ix_tenants_factory_partner_application_id",
        "tenants",
        ["factory_partner_application_id"],
    )

    create_table_if_missing(
        "tenant_users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_tenant_users_tenant_id", "tenant_users", ["tenant_id"])
    create_index_if_missing("ix_tenant_users_email", "tenant_users", ["email"])
    create_index_if_missing("ix_tenant_users_role", "tenant_users", ["role"])

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
    op.drop_index("ix_factory_partner_applications_tenant_id", table_name="factory_partner_applications")
    op.drop_column("factory_partner_applications", "tenant_id")
    op.drop_index("ix_customer_portal_accounts_tenant_id", table_name="customer_portal_accounts")
    op.drop_column("customer_portal_accounts", "tenant_id")
    op.drop_index("ix_clients_tenant_id", table_name="clients")
    op.drop_column("clients", "tenant_id")
    op.drop_index("ix_tenant_users_role", table_name="tenant_users")
    op.drop_index("ix_tenant_users_email", table_name="tenant_users")
    op.drop_index("ix_tenant_users_tenant_id", table_name="tenant_users")
    op.drop_table("tenant_users")
    op.drop_index("ix_tenants_factory_partner_application_id", table_name="tenants")
    op.drop_index("ix_tenants_status", table_name="tenants")
    op.drop_index("ix_tenants_company_name", table_name="tenants")
    op.drop_table("tenants")
