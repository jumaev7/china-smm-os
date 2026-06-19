"""Tenant factory onboarding progress and analytics."""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import add_column_if_missing, create_index_if_missing, create_table_if_missing

revision = "20260821_add_tenant_onboarding"
down_revision = "20260820_add_platform_integrations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    create_table_if_missing(
        "tenant_onboarding_progress",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            UUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="not_started"),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps_completed", JSONB(), nullable=True),
        sa.Column("milestone_messages", JSONB(), nullable=True),
        sa.Column("company_profile", JSONB(), nullable=True),
        sa.Column("demo_data_generated", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("demo_data_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("manually_completed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("manually_reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_content_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_lead_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_buyer_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_deal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_proposal_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("growth_center_viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    create_index_if_missing(
        "ix_tenant_onboarding_progress_tenant_id",
        "tenant_onboarding_progress",
        ["tenant_id"],
        unique=True,
    )
    create_index_if_missing(
        "ix_tenant_onboarding_progress_status",
        "tenant_onboarding_progress",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("tenant_onboarding_progress")
