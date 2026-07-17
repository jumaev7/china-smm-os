"""Content Optimizer — deterministic platform content variants (Phase 2A)."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    create_index_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
    table_exists,
)

revision = "20260908_content_optimizer"
down_revision = "20260907_publishing_intelligence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if not table_exists("tenants") or not table_exists("content_items"):
        return

    if not table_exists("tenant_content_optimization_runs"):
        op.create_table(
            "tenant_content_optimization_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "content_id",
                UUID(as_uuid=True),
                sa.ForeignKey("content_items.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source_fingerprint", sa.String(64), nullable=False),
            sa.Column(
                "optimizer_version",
                sa.String(20),
                nullable=False,
                server_default="1.0.0",
            ),
            sa.Column(
                "policy_version",
                sa.String(20),
                nullable=False,
                server_default="1.0.0",
            ),
            sa.Column("requested_platforms", JSONB(), nullable=True),
            sa.Column("requested_locales", JSONB(), nullable=True),
            sa.Column("configuration", JSONB(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="generated"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_code", sa.String(80), nullable=True),
            sa.Column("failure_metadata", JSONB(), nullable=True),
        )

    create_index_if_missing(
        "ix_tenant_content_optimization_runs_tenant_id",
        "tenant_content_optimization_runs",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_optimization_runs_content_id",
        "tenant_content_optimization_runs",
        ["content_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_opt_runs_tenant_content_created",
        "tenant_content_optimization_runs",
        ["tenant_id", "content_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_content_opt_runs_tenant_status_created",
        "tenant_content_optimization_runs",
        ["tenant_id", "status", "created_at"],
    )

    if not table_exists("tenant_content_templates"):
        op.create_table(
            "tenant_content_templates",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("template_type", sa.String(40), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("locale", sa.String(10), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("allowed_platforms", JSONB(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )

    create_index_if_missing(
        "ix_tenant_content_templates_tenant_id",
        "tenant_content_templates",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_templates_tenant_type_locale",
        "tenant_content_templates",
        ["tenant_id", "template_type", "locale"],
    )
    create_index_if_missing(
        "ix_tenant_content_templates_tenant_active",
        "tenant_content_templates",
        ["tenant_id", "is_active"],
    )

    if not table_exists("tenant_content_variants"):
        op.create_table(
            "tenant_content_variants",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "optimization_run_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_content_optimization_runs.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "content_id",
                UUID(as_uuid=True),
                sa.ForeignKey("content_items.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("platform", sa.String(40), nullable=False),
            sa.Column("locale", sa.String(10), nullable=False),
            sa.Column("length_profile", sa.String(20), nullable=False),
            sa.Column("variant_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("caption", sa.Text(), nullable=False, server_default=""),
            sa.Column("hashtags", JSONB(), nullable=True),
            sa.Column("cta", sa.Text(), nullable=True),
            sa.Column("link", sa.Text(), nullable=True),
            sa.Column("source_fingerprint", sa.String(64), nullable=False),
            sa.Column("variant_fingerprint", sa.String(64), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="generated"),
            sa.Column("publish_readiness", sa.String(40), nullable=True),
            sa.Column(
                "publishing_review_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_publishing_reviews.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("source_score", sa.Integer(), nullable=True),
            sa.Column("variant_score", sa.Integer(), nullable=True),
            sa.Column("score_delta", sa.Integer(), nullable=True),
            sa.Column("category_deltas", JSONB(), nullable=True),
            sa.Column("unsupported_reason", sa.String(120), nullable=True),
            sa.Column("accepted_by", UUID(as_uuid=True), nullable=True),
            sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejected_by", UUID(as_uuid=True), nullable=True),
            sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("applied_by", UUID(as_uuid=True), nullable=True),
            sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "optimization_run_id",
                "platform",
                "locale",
                "length_profile",
                name="uq_tenant_content_variants_run_platform_locale_profile",
            ),
        )

    create_index_if_missing(
        "ix_tenant_content_variants_tenant_id",
        "tenant_content_variants",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_variants_content_id",
        "tenant_content_variants",
        ["content_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_variants_optimization_run_id",
        "tenant_content_variants",
        ["optimization_run_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_variants_publishing_review_id",
        "tenant_content_variants",
        ["publishing_review_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_variants_tenant_content_created",
        "tenant_content_variants",
        ["tenant_id", "content_id", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_content_variants_tenant_platform_locale_created",
        "tenant_content_variants",
        ["tenant_id", "platform", "locale", "created_at"],
    )
    create_index_if_missing(
        "ix_tenant_content_variants_run_platform_locale_profile",
        "tenant_content_variants",
        ["optimization_run_id", "platform", "locale", "length_profile"],
    )

    if not table_exists("tenant_content_variant_transformations"):
        op.create_table(
            "tenant_content_variant_transformations",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "content_variant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_content_variants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column("operation_key", sa.String(80), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("source_excerpt_hash", sa.String(64), nullable=True),
            sa.Column("source_position", JSONB(), nullable=True),
            sa.Column("result_excerpt_hash", sa.String(64), nullable=True),
            sa.Column("reason_key", sa.String(80), nullable=False),
            sa.Column("reason_params", JSONB(), nullable=True),
            sa.Column("policy_key", sa.String(80), nullable=True),
            sa.Column("policy_version", sa.String(20), nullable=True),
            sa.Column("result_summary", sa.String(240), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "content_variant_id",
                "sequence",
                name="uq_tenant_content_variant_transformations_variant_seq",
            ),
        )

    create_index_if_missing(
        "ix_tenant_content_variant_transformations_tenant_id",
        "tenant_content_variant_transformations",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_variant_transformations_content_variant_id",
        "tenant_content_variant_transformations",
        ["content_variant_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_variant_xf_tenant_variant",
        "tenant_content_variant_transformations",
        ["tenant_id", "content_variant_id"],
    )


def downgrade() -> None:
    drop_index_if_exists(
        "ix_tenant_content_variant_xf_tenant_variant",
        "tenant_content_variant_transformations",
    )
    drop_index_if_exists(
        "ix_tenant_content_variant_transformations_content_variant_id",
        "tenant_content_variant_transformations",
    )
    drop_index_if_exists(
        "ix_tenant_content_variant_transformations_tenant_id",
        "tenant_content_variant_transformations",
    )
    drop_table_if_exists("tenant_content_variant_transformations")

    drop_index_if_exists(
        "ix_tenant_content_variants_run_platform_locale_profile",
        "tenant_content_variants",
    )
    drop_index_if_exists(
        "ix_tenant_content_variants_tenant_platform_locale_created",
        "tenant_content_variants",
    )
    drop_index_if_exists(
        "ix_tenant_content_variants_tenant_content_created",
        "tenant_content_variants",
    )
    drop_index_if_exists(
        "ix_tenant_content_variants_publishing_review_id",
        "tenant_content_variants",
    )
    drop_index_if_exists(
        "ix_tenant_content_variants_optimization_run_id",
        "tenant_content_variants",
    )
    drop_index_if_exists(
        "ix_tenant_content_variants_content_id",
        "tenant_content_variants",
    )
    drop_index_if_exists(
        "ix_tenant_content_variants_tenant_id",
        "tenant_content_variants",
    )
    drop_table_if_exists("tenant_content_variants")

    drop_index_if_exists(
        "ix_tenant_content_templates_tenant_active",
        "tenant_content_templates",
    )
    drop_index_if_exists(
        "ix_tenant_content_templates_tenant_type_locale",
        "tenant_content_templates",
    )
    drop_index_if_exists(
        "ix_tenant_content_templates_tenant_id",
        "tenant_content_templates",
    )
    drop_table_if_exists("tenant_content_templates")

    drop_index_if_exists(
        "ix_tenant_content_opt_runs_tenant_status_created",
        "tenant_content_optimization_runs",
    )
    drop_index_if_exists(
        "ix_tenant_content_opt_runs_tenant_content_created",
        "tenant_content_optimization_runs",
    )
    drop_index_if_exists(
        "ix_tenant_content_optimization_runs_content_id",
        "tenant_content_optimization_runs",
    )
    drop_index_if_exists(
        "ix_tenant_content_optimization_runs_tenant_id",
        "tenant_content_optimization_runs",
    )
    drop_table_if_exists("tenant_content_optimization_runs")
