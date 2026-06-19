"""Subscription & Billing v1 — plans, subscriptions, invoices."""
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON, UUID

from migrations.helpers import create_index_if_missing, create_table_if_missing

revision = "20260720_add_subscription_billing"
down_revision = "20260719_ensure_tenant_columns"
branch_labels = None
depends_on = None

_PLAN_SEED = [
    {
        "id": "00000000-0000-4000-8000-000000000001",
        "code": "free",
        "name": "Free",
        "monthly_price": 0,
        "yearly_price": 0,
        "max_users": 2,
        "max_leads": 50,
        "max_buyers": 10,
        "max_deals": 5,
        "features": '["crm", "basic_inbox"]',
    },
    {
        "id": "00000000-0000-4000-8000-000000000002",
        "code": "professional",
        "name": "Professional",
        "monthly_price": 99,
        "yearly_price": 990,
        "max_users": 10,
        "max_leads": 500,
        "max_buyers": 100,
        "max_deals": 50,
        "features": '["crm", "inbox", "intelligence", "proposals", "buyer_finder"]',
    },
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "code": "enterprise",
        "name": "Enterprise",
        "monthly_price": 299,
        "yearly_price": 2990,
        "max_users": None,
        "max_leads": None,
        "max_buyers": None,
        "max_deals": None,
        "features": '["all", "executive_copilot", "multi_agent", "priority_support"]',
    },
]


def upgrade() -> None:
    create_table_if_missing(
        "plans",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("monthly_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("yearly_price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("max_users", sa.Integer(), nullable=True),
        sa.Column("max_leads", sa.Integer(), nullable=True),
        sa.Column("max_buyers", sa.Integer(), nullable=True),
        sa.Column("max_deals", sa.Integer(), nullable=True),
        sa.Column("features", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_plans_code", "plans", ["code"], unique=True)

    create_table_if_missing(
        "subscriptions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "plan_id",
            UUID(as_uuid=True),
            sa.ForeignKey("plans.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="trial"),
        sa.Column("billing_cycle", sa.String(length=20), nullable=False, server_default="monthly"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing("ix_subscriptions_tenant_id", "subscriptions", ["tenant_id"])
    create_index_if_missing("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    create_index_if_missing("ix_subscriptions_status", "subscriptions", ["status"])

    create_table_if_missing(
        "invoices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "subscription_id",
            UUID(as_uuid=True),
            sa.ForeignKey("subscriptions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="USD"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("invoice_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=False),
    )
    create_index_if_missing("ix_invoices_tenant_id", "invoices", ["tenant_id"])
    create_index_if_missing("ix_invoices_subscription_id", "invoices", ["subscription_id"])
    create_index_if_missing("ix_invoices_status", "invoices", ["status"])

    bind = op.get_bind()
    for row in _PLAN_SEED:
        exists = bind.execute(
            sa.text("SELECT 1 FROM plans WHERE code = :code LIMIT 1"),
            {"code": row["code"]},
        ).first()
        if exists:
            continue
        bind.execute(
            sa.text(
                """
                INSERT INTO plans (
                    id, name, code, monthly_price, yearly_price,
                    max_users, max_leads, max_buyers, max_deals, features
                ) VALUES (
                    :id, :name, :code, :monthly_price, :yearly_price,
                    :max_users, :max_leads, :max_buyers, :max_deals, CAST(:features AS jsonb)
                )
                """
            ),
            row,
        )


def downgrade() -> None:
    op.drop_index("ix_invoices_status", table_name="invoices")
    op.drop_index("ix_invoices_subscription_id", table_name="invoices")
    op.drop_index("ix_invoices_tenant_id", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index("ix_subscriptions_status", table_name="subscriptions")
    op.drop_index("ix_subscriptions_plan_id", table_name="subscriptions")
    op.drop_index("ix_subscriptions_tenant_id", table_name="subscriptions")
    op.drop_table("subscriptions")
    op.drop_index("ix_plans_code", table_name="plans")
    op.drop_table("plans")
