"""Extend tenant onboarding progress — platform/business readiness v2."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

from migrations.helpers import add_column_if_missing

revision = "20260829_extend_tenant_onboarding_v2"
down_revision = "20260828_executive_crm_pipeline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("platform_readiness_percent", sa.Integer(), nullable=False, server_default="0"),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("business_readiness_percent", sa.Integer(), nullable=False, server_default="0"),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("executive_walkthrough_progress", JSONB(), nullable=True),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("first_success_state", JSONB(), nullable=True),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("auto_config_applied", sa.Boolean(), nullable=False, server_default="false"),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("auto_config_applied_at", sa.DateTime(timezone=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_onboarding_progress",
        sa.Column("onboarding_version", sa.Integer(), nullable=False, server_default="2"),
    )


def downgrade() -> None:
    for col in (
        "onboarding_version",
        "auto_config_applied_at",
        "auto_config_applied",
        "first_success_state",
        "executive_walkthrough_progress",
        "last_activity_at",
        "business_readiness_percent",
        "platform_readiness_percent",
    ):
        op.drop_column("tenant_onboarding_progress", col)
