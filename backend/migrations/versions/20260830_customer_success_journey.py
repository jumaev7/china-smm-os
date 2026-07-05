"""Customer Success Journey — post-platform-ready adoption engine."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260830_customer_success_journey"
down_revision = "20260829_extend_tenant_onboarding_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("north_star_goal", sa.String(40), nullable=True),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("platform_ready_at", sa.DateTime(timezone=True), nullable=True),
    )

    create_table_if_missing(
        "tenant_customer_success_journey",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_checkpoint", sa.String(20), nullable=True),
        sa.Column("milestones_achieved", JSONB(), nullable=True),
        sa.Column("timeline_entries", JSONB(), nullable=True),
        sa.Column("weekly_wins", JSONB(), nullable=True),
        sa.Column("dismissed_recommendations", JSONB(), nullable=True),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_tenant_customer_success_journey_tenant_id",
        "tenant_customer_success_journey",
        ["tenant_id"],
        unique=True,
    )
    create_index_if_missing(
        "ix_tenant_customer_success_journey_status",
        "tenant_customer_success_journey",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("tenant_customer_success_journey")
    op.drop_column("tenant_onboarding_progress", "platform_ready_at")
    op.drop_column("tenant_onboarding_progress", "north_star_goal")
