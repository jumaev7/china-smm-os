"""Tenant-scoped publishing accounts — tenant_id ownership column."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing

revision = "20260827_add_publishing_accounts_tenant_id"
down_revision = "20260826_add_meta_publishing_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "publishing_accounts",
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=True),
    )
    create_index_if_missing(
        "ix_publishing_accounts_tenant_id",
        "publishing_accounts",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_publishing_accounts_tenant_platform",
        "publishing_accounts",
        ["tenant_id", "platform"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                """
                UPDATE publishing_accounts
                SET tenant_id = (
                    SELECT tu.tenant_id
                    FROM tenant_users tu
                    WHERE lower(tu.email) = 'demo@factory.local'
                    LIMIT 1
                )
                WHERE tenant_id IS NULL
                """
            )
        )
        bind.execute(
            sa.text(
                """
                UPDATE publishing_accounts
                SET tenant_id = (
                    SELECT t.id FROM tenants t ORDER BY t.created_at ASC LIMIT 1
                )
                WHERE tenant_id IS NULL
                """
            )
        )

    op.alter_column("publishing_accounts", "tenant_id", nullable=False)
    op.create_foreign_key(
        "fk_publishing_accounts_tenant_id",
        "publishing_accounts",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_publishing_accounts_tenant_id", "publishing_accounts", type_="foreignkey")
    op.drop_index("ix_publishing_accounts_tenant_platform", table_name="publishing_accounts")
    op.drop_index("ix_publishing_accounts_tenant_id", table_name="publishing_accounts")
    op.drop_column("publishing_accounts", "tenant_id")
