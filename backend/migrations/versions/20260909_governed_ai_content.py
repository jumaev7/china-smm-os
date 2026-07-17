"""Governed AI Content Adaptation — policies, generations, usage, and brand profiles."""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

from migrations.helpers import (
    add_column_if_missing,
    create_index_if_missing,
    drop_column_if_exists,
    drop_index_if_exists,
    drop_table_if_exists,
    table_exists,
)

revision = "20260909_governed_ai_content"
down_revision = "20260908_content_optimizer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if (
        not table_exists("tenants")
        or not table_exists("tenant_content_optimization_runs")
        or not table_exists("tenant_content_variants")
    ):
        return

    if not table_exists("tenant_ai_policies"):
        op.create_table(
            "tenant_ai_policies",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("allowed_task_types", JSONB(), nullable=True),
            sa.Column("allowed_locales", JSONB(), nullable=True),
            sa.Column("allowed_platforms", JSONB(), nullable=True),
            sa.Column(
                "allow_provider_processing",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column(
                "allow_fallback_provider",
                sa.Boolean(),
                nullable=False,
                server_default="false",
            ),
            sa.Column(
                "store_redacted_inputs",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column(
                "store_redacted_outputs",
                sa.Boolean(),
                nullable=False,
                server_default="true",
            ),
            sa.Column("hourly_request_limit", sa.Integer(), nullable=True),
            sa.Column("daily_token_limit", sa.Integer(), nullable=True),
            sa.Column("monthly_cost_limit_minor", sa.Integer(), nullable=True),
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
            sa.UniqueConstraint(
                "tenant_id",
                name="uq_tenant_ai_policies_tenant",
            ),
        )

    create_index_if_missing(
        "ix_tenant_ai_policies_tenant_id",
        "tenant_ai_policies",
        ["tenant_id"],
    )

    if not table_exists("tenant_ai_requests"):
        op.create_table(
            "tenant_ai_requests",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("task_type", sa.String(80), nullable=False),
            sa.Column(
                "entity_type",
                sa.String(40),
                nullable=False,
                server_default="content",
            ),
            sa.Column("entity_id", UUID(as_uuid=True), nullable=False),
            sa.Column(
                "request_status",
                sa.String(40),
                nullable=False,
                server_default="queued",
            ),
            sa.Column("model_alias", sa.String(40), nullable=False),
            sa.Column("resolved_provider", sa.String(40), nullable=True),
            sa.Column("resolved_model", sa.String(80), nullable=True),
            sa.Column("routing_version", sa.String(20), nullable=True),
            sa.Column("prompt_key", sa.String(120), nullable=False),
            sa.Column("prompt_version", sa.String(20), nullable=False),
            sa.Column("input_fingerprint", sa.String(64), nullable=False),
            sa.Column("idempotency_key", sa.String(128), nullable=False),
            sa.Column("brand_profile_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "optimization_run_id",
                UUID(as_uuid=True),
                sa.ForeignKey(
                    "tenant_content_optimization_runs.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column("configuration", JSONB(), nullable=True),
            sa.Column("requested_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "requested_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("failure_code", sa.String(80), nullable=True),
            sa.Column("failure_metadata", JSONB(), nullable=True),
            sa.UniqueConstraint(
                "tenant_id",
                "idempotency_key",
                name="uq_tenant_ai_requests_tenant_idempotency",
            ),
        )

    create_index_if_missing(
        "ix_tenant_ai_requests_tenant_id",
        "tenant_ai_requests",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ai_requests_entity_id",
        "tenant_ai_requests",
        ["entity_id"],
    )
    create_index_if_missing(
        "ix_tenant_ai_requests_tenant_content_created",
        "tenant_ai_requests",
        ["tenant_id", "entity_id", "requested_at"],
    )
    create_index_if_missing(
        "ix_tenant_ai_requests_tenant_status_requested",
        "tenant_ai_requests",
        ["tenant_id", "request_status", "requested_at"],
    )

    if not table_exists("tenant_ai_generations"):
        op.create_table(
            "tenant_ai_generations",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "ai_request_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_ai_requests.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "generation_version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("platform", sa.String(40), nullable=True),
            sa.Column("locale", sa.String(10), nullable=True),
            sa.Column("length_profile", sa.String(20), nullable=True),
            sa.Column("structured_output", JSONB(), nullable=True),
            sa.Column("redacted_input_snapshot", JSONB(), nullable=True),
            sa.Column("redacted_output_snapshot", JSONB(), nullable=True),
            sa.Column("output_fingerprint", sa.String(64), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "estimated_cost_minor",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("finish_reason", sa.String(40), nullable=True),
            sa.Column(
                "validation_status",
                sa.String(40),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "safety_status",
                sa.String(40),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("factual_validation", JSONB(), nullable=True),
            sa.Column("protected_fact_summary", JSONB(), nullable=True),
            sa.Column(
                "content_variant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_content_variants.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "ai_request_id",
                "generation_version",
                name="uq_tenant_ai_generations_request_version",
            ),
        )

    create_index_if_missing(
        "ix_tenant_ai_generations_tenant_id",
        "tenant_ai_generations",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ai_generations_ai_request_id",
        "tenant_ai_generations",
        ["ai_request_id"],
    )
    create_index_if_missing(
        "ix_tenant_ai_generations_tenant_request",
        "tenant_ai_generations",
        ["tenant_id", "ai_request_id"],
    )

    if not table_exists("tenant_ai_usage_daily"):
        op.create_table(
            "tenant_ai_usage_daily",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("usage_date", sa.Date(), nullable=False),
            sa.Column("provider", sa.String(40), nullable=False),
            sa.Column("model", sa.String(80), nullable=False),
            sa.Column("task_type", sa.String(80), nullable=False),
            sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "successful_request_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "failed_request_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "estimated_cost_minor",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(8), nullable=False, server_default="USD"),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "tenant_id",
                "usage_date",
                "provider",
                "model",
                "task_type",
                name="uq_tenant_ai_usage_daily_dims",
            ),
        )

    create_index_if_missing(
        "ix_tenant_ai_usage_daily_tenant_id",
        "tenant_ai_usage_daily",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_ai_usage_daily_tenant_date",
        "tenant_ai_usage_daily",
        ["tenant_id", "usage_date"],
    )

    if not table_exists("tenant_brand_profiles"):
        op.create_table(
            "tenant_brand_profiles",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("current_version_id", UUID(as_uuid=True), nullable=True),
            sa.Column("draft_payload", JSONB(), nullable=True),
            sa.Column("draft_version", sa.Integer(), nullable=False, server_default="0"),
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
        "ix_tenant_brand_profiles_tenant_id",
        "tenant_brand_profiles",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_brand_profiles_tenant_status",
        "tenant_brand_profiles",
        ["tenant_id", "status"],
    )

    if not table_exists("tenant_brand_profile_versions"):
        op.create_table(
            "tenant_brand_profile_versions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "tenant_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenants.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "brand_profile_id",
                UUID(as_uuid=True),
                sa.ForeignKey("tenant_brand_profiles.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("locale", sa.String(10), nullable=False, server_default="en"),
            sa.Column(
                "company_name",
                sa.String(200),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "company_description",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "audience_description",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("tone_traits", JSONB(), nullable=True),
            sa.Column("preferred_terms", JSONB(), nullable=True),
            sa.Column("forbidden_terms", JSONB(), nullable=True),
            sa.Column("approved_claims", JSONB(), nullable=True),
            sa.Column("prohibited_claims", JSONB(), nullable=True),
            sa.Column("cta_preferences", JSONB(), nullable=True),
            sa.Column("emoji_policy", JSONB(), nullable=True),
            sa.Column("formatting_preferences", JSONB(), nullable=True),
            sa.Column("platform_guidance", JSONB(), nullable=True),
            sa.Column("source_references", JSONB(), nullable=True),
            sa.Column("created_by", UUID(as_uuid=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "published_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.UniqueConstraint(
                "brand_profile_id",
                "version",
                name="uq_tenant_brand_profile_versions_profile_version",
            ),
        )

    create_index_if_missing(
        "ix_tenant_brand_profile_versions_tenant_id",
        "tenant_brand_profile_versions",
        ["tenant_id"],
    )
    create_index_if_missing(
        "ix_tenant_brand_profile_versions_brand_profile_id",
        "tenant_brand_profile_versions",
        ["brand_profile_id"],
    )
    create_index_if_missing(
        "ix_tenant_brand_profile_versions_tenant_profile",
        "tenant_brand_profile_versions",
        ["tenant_id", "brand_profile_id"],
    )

    add_column_if_missing(
        "tenant_content_variants",
        sa.Column(
            "generation_method",
            sa.String(40),
            nullable=False,
            server_default="deterministic",
        ),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("ai_request_id", UUID(as_uuid=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("ai_generation_id", UUID(as_uuid=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("brand_profile_version_id", UUID(as_uuid=True), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("prompt_key", sa.String(120), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("prompt_version", sa.String(20), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("model_alias", sa.String(40), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("resolved_provider", sa.String(40), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("resolved_model", sa.String(80), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("factual_validation_status", sa.String(40), nullable=True),
    )
    add_column_if_missing(
        "tenant_content_variants",
        sa.Column("safety_validation_status", sa.String(40), nullable=True),
    )

    create_index_if_missing(
        "ix_tenant_content_variants_ai_request_id",
        "tenant_content_variants",
        ["ai_request_id"],
    )
    create_index_if_missing(
        "ix_tenant_content_variants_ai_generation_id",
        "tenant_content_variants",
        ["ai_generation_id"],
    )


def downgrade() -> None:
    drop_index_if_exists(
        "ix_tenant_content_variants_ai_generation_id",
        "tenant_content_variants",
    )
    drop_index_if_exists(
        "ix_tenant_content_variants_ai_request_id",
        "tenant_content_variants",
    )

    drop_column_if_exists("tenant_content_variants", "safety_validation_status")
    drop_column_if_exists("tenant_content_variants", "factual_validation_status")
    drop_column_if_exists("tenant_content_variants", "resolved_model")
    drop_column_if_exists("tenant_content_variants", "resolved_provider")
    drop_column_if_exists("tenant_content_variants", "model_alias")
    drop_column_if_exists("tenant_content_variants", "prompt_version")
    drop_column_if_exists("tenant_content_variants", "prompt_key")
    drop_column_if_exists("tenant_content_variants", "brand_profile_version_id")
    drop_column_if_exists("tenant_content_variants", "ai_generation_id")
    drop_column_if_exists("tenant_content_variants", "ai_request_id")
    drop_column_if_exists("tenant_content_variants", "generation_method")

    drop_index_if_exists(
        "ix_tenant_brand_profile_versions_tenant_profile",
        "tenant_brand_profile_versions",
    )
    drop_index_if_exists(
        "ix_tenant_brand_profile_versions_brand_profile_id",
        "tenant_brand_profile_versions",
    )
    drop_index_if_exists(
        "ix_tenant_brand_profile_versions_tenant_id",
        "tenant_brand_profile_versions",
    )
    drop_table_if_exists("tenant_brand_profile_versions")

    drop_index_if_exists(
        "ix_tenant_brand_profiles_tenant_status",
        "tenant_brand_profiles",
    )
    drop_index_if_exists(
        "ix_tenant_brand_profiles_tenant_id",
        "tenant_brand_profiles",
    )
    drop_table_if_exists("tenant_brand_profiles")

    drop_index_if_exists(
        "ix_tenant_ai_usage_daily_tenant_date",
        "tenant_ai_usage_daily",
    )
    drop_index_if_exists(
        "ix_tenant_ai_usage_daily_tenant_id",
        "tenant_ai_usage_daily",
    )
    drop_table_if_exists("tenant_ai_usage_daily")

    drop_index_if_exists(
        "ix_tenant_ai_generations_tenant_request",
        "tenant_ai_generations",
    )
    drop_index_if_exists(
        "ix_tenant_ai_generations_ai_request_id",
        "tenant_ai_generations",
    )
    drop_index_if_exists(
        "ix_tenant_ai_generations_tenant_id",
        "tenant_ai_generations",
    )
    drop_table_if_exists("tenant_ai_generations")

    drop_index_if_exists(
        "ix_tenant_ai_requests_tenant_status_requested",
        "tenant_ai_requests",
    )
    drop_index_if_exists(
        "ix_tenant_ai_requests_tenant_content_created",
        "tenant_ai_requests",
    )
    drop_index_if_exists(
        "ix_tenant_ai_requests_entity_id",
        "tenant_ai_requests",
    )
    drop_index_if_exists(
        "ix_tenant_ai_requests_tenant_id",
        "tenant_ai_requests",
    )
    drop_table_if_exists("tenant_ai_requests")

    drop_index_if_exists(
        "ix_tenant_ai_policies_tenant_id",
        "tenant_ai_policies",
    )
    drop_table_if_exists("tenant_ai_policies")
