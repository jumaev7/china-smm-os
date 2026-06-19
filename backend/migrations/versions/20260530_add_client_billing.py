"""Add client billing / subscription package fields."""
from alembic import op
import sqlalchemy as sa
from migrations.helpers import add_column_if_missing, drop_column_if_exists

revision = "20260530_add_client_billing"
down_revision = "20260529_add_operator_auto_draft"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing("clients", sa.Column("plan_name", sa.String(length=100), nullable=True))
    add_column_if_missing("clients", sa.Column("monthly_fee", sa.Numeric(10, 2), nullable=True))
    add_column_if_missing("clients", sa.Column("monthly_post_limit", sa.Integer(), nullable=True))
    add_column_if_missing(
        "clients",
        sa.Column(
            "billing_status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
    )
    add_column_if_missing(
        "clients",
        sa.Column("billing_cycle_start", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "clients",
        sa.Column("billing_cycle_end", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    drop_column_if_exists("clients", "billing_cycle_end")
    drop_column_if_exists("clients", "billing_cycle_start")
    drop_column_if_exists("clients", "billing_status")
    drop_column_if_exists("clients", "monthly_post_limit")
    drop_column_if_exists("clients", "monthly_fee")
    drop_column_if_exists("clients", "plan_name")
