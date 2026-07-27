"""Social Listening Phase 1 — Observed Mentions Foundation tables.

Creates tenant-scoped listening projects, subjects, queries, sources,
observed mentions, matches, reviews, and ingestion runs.

READ-ONLY toward providers: no table stores executable provider payloads,
credentials, or mutation commands. Phase 1 sources are manual_import and
fixture only.

down_revision = "20260913_advertising_decision_support"
"""
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

revision = "20260914_social_listening_foundation"
down_revision = "20260913_advertising_decision_support"
branch_labels = None
depends_on = None


def _ts(name: str, *, default: bool = True, nullable: bool = False) -> sa.Column:
    kwargs = {"nullable": nullable}
    if default:
        kwargs["server_default"] = sa.text("now()")
    return sa.Column(name, sa.DateTime(timezone=True), **kwargs)


def upgrade() -> None:
    if not table_exists("tenants"):
        return

    if not table_exists("tenant_listening_projects"):
        op.create_table(
            "tenant_listening_projects",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("client_id", UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("status", sa.String(40), nullable=False, server_default="active"),
            sa.Column("default_locale", sa.String(10), nullable=True),
            sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )
    create_index_if_missing("ix_tenant_listening_projects_tenant_id", "tenant_listening_projects", ["tenant_id"])
    create_index_if_missing("ix_tenant_listening_projects_tenant_status", "tenant_listening_projects", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_listening_projects_tenant_created", "tenant_listening_projects", ["tenant_id", "created_at"])

    if not table_exists("tenant_listening_subjects"):
        op.create_table(
            "tenant_listening_subjects",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("subject_type", sa.String(40), nullable=False),
            sa.Column("canonical_name", sa.String(200), nullable=False),
            sa.Column("aliases_json", JSONB(), nullable=True),
            sa.Column("handle", sa.String(200), nullable=True),
            sa.Column("domain", sa.String(255), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("metadata_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
        )
    create_index_if_missing("ix_tenant_listening_subjects_tenant_id", "tenant_listening_subjects", ["tenant_id"])
    create_index_if_missing("ix_tenant_listening_subjects_project", "tenant_listening_subjects", ["tenant_id", "project_id"])
    create_index_if_missing("ix_tenant_listening_subjects_type", "tenant_listening_subjects", ["tenant_id", "subject_type"])

    if not table_exists("tenant_listening_queries"):
        op.create_table(
            "tenant_listening_queries",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("subject_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_subjects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("include_terms_json", JSONB(), nullable=True),
            sa.Column("exclude_terms_json", JSONB(), nullable=True),
            sa.Column("source_filters_json", JSONB(), nullable=True),
            sa.Column("language_filters_json", JSONB(), nullable=True),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
        )
    create_index_if_missing("ix_tenant_listening_queries_tenant_id", "tenant_listening_queries", ["tenant_id"])
    create_index_if_missing("ix_tenant_listening_queries_project", "tenant_listening_queries", ["tenant_id", "project_id"])
    create_index_if_missing("ix_tenant_listening_queries_enabled", "tenant_listening_queries", ["tenant_id", "is_enabled"])

    if not table_exists("tenant_listening_sources"):
        op.create_table(
            "tenant_listening_sources",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"), nullable=False),
            sa.Column("source_type", sa.String(40), nullable=False),
            sa.Column("source_key", sa.String(80), nullable=False, server_default="default"),
            sa.Column("display_name", sa.String(200), nullable=False),
            sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("capability_status", sa.String(40), nullable=False, server_default="import_only"),
            sa.Column("config_json", JSONB(), nullable=True),
            sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("freshness_status", sa.String(40), nullable=False, server_default="unavailable"),
            sa.Column("freshness_watermark", sa.DateTime(timezone=True), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint("tenant_id", "project_id", "source_type", "source_key", name="uq_tenant_listening_sources_identity"),
        )
    create_index_if_missing("ix_tenant_listening_sources_tenant_id", "tenant_listening_sources", ["tenant_id"])
    create_index_if_missing("ix_tenant_listening_sources_project", "tenant_listening_sources", ["tenant_id", "project_id"])

    if not table_exists("tenant_listening_ingestion_runs"):
        op.create_table(
            "tenant_listening_ingestion_runs",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_sources.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_type", sa.String(40), nullable=False),
            sa.Column("trigger_type", sa.String(40), nullable=False, server_default="manual"),
            sa.Column("status", sa.String(40), nullable=False, server_default="pending"),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rejected_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_summary", sa.String(1000), nullable=True),
            sa.Column("cursor_before", sa.String(255), nullable=True),
            sa.Column("cursor_after", sa.String(255), nullable=True),
            sa.Column("checkpoint_json", JSONB(), nullable=True),
            sa.Column("provider_request_id", sa.String(255), nullable=True),
            sa.Column("freshness_watermark", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by_user_id", UUID(as_uuid=True), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_listening_ingestion_runs_tenant_id", "tenant_listening_ingestion_runs", ["tenant_id"])
    create_index_if_missing("ix_tenant_listening_ingestion_runs_tenant_created", "tenant_listening_ingestion_runs", ["tenant_id", "created_at"])
    create_index_if_missing("ix_tenant_listening_ingestion_runs_tenant_status", "tenant_listening_ingestion_runs", ["tenant_id", "status"])
    create_index_if_missing("ix_tenant_listening_ingestion_runs_project", "tenant_listening_ingestion_runs", ["tenant_id", "project_id"])

    if not table_exists("tenant_observed_mentions"):
        op.create_table(
            "tenant_observed_mentions",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_projects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_sources.id", ondelete="SET NULL"), nullable=True),
            sa.Column("source_type", sa.String(40), nullable=False),
            sa.Column("observation_origin", sa.String(40), nullable=False),
            sa.Column("provider_account_ref", sa.String(255), nullable=False, server_default=""),
            sa.Column("provider_external_id", sa.String(255), nullable=True),
            sa.Column("canonical_url", sa.String(2000), nullable=True),
            sa.Column("author_display", sa.String(255), nullable=True),
            sa.Column("author_external_id", sa.String(255), nullable=True),
            sa.Column("content_text", sa.Text(), nullable=True),
            sa.Column("content_excerpt", sa.String(1000), nullable=True),
            sa.Column("content_type", sa.String(40), nullable=False, server_default="post"),
            sa.Column("language", sa.String(16), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("engagement_json", JSONB(), nullable=True),
            sa.Column("content_fingerprint", sa.String(128), nullable=False),
            sa.Column("dedupe_key", sa.String(255), nullable=False),
            sa.Column("dedupe_version", sa.String(40), nullable=False, server_default="listening_dedupe_v1"),
            sa.Column("normalization_version", sa.String(40), nullable=False, server_default="listening_norm_v1"),
            sa.Column("review_state", sa.String(40), nullable=False, server_default="unreviewed"),
            sa.Column("ingestion_run_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_ingestion_runs.id", ondelete="SET NULL"), nullable=True),
            sa.Column("provenance_json", JSONB(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "tenant_id", "source_type", "provider_account_ref", "provider_external_id",
                name="uq_tenant_observed_mentions_provider_identity",
            ),
            sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_tenant_observed_mentions_dedupe_key"),
        )
    create_index_if_missing("ix_tenant_observed_mentions_tenant_id", "tenant_observed_mentions", ["tenant_id"])
    create_index_if_missing("ix_tenant_observed_mentions_tenant_published", "tenant_observed_mentions", ["tenant_id", "published_at"])
    create_index_if_missing("ix_tenant_observed_mentions_tenant_observed", "tenant_observed_mentions", ["tenant_id", "observed_at"])
    create_index_if_missing("ix_tenant_observed_mentions_tenant_review", "tenant_observed_mentions", ["tenant_id", "review_state"])
    create_index_if_missing("ix_tenant_observed_mentions_tenant_project", "tenant_observed_mentions", ["tenant_id", "project_id"])
    create_index_if_missing("ix_tenant_observed_mentions_tenant_source", "tenant_observed_mentions", ["tenant_id", "source_type"])
    create_index_if_missing("ix_tenant_observed_mentions_fingerprint", "tenant_observed_mentions", ["tenant_id", "content_fingerprint"])
    create_index_if_missing("ix_tenant_observed_mentions_canonical_url", "tenant_observed_mentions", ["tenant_id", "canonical_url"])

    if not table_exists("tenant_mention_matches"):
        op.create_table(
            "tenant_mention_matches",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mention_id", UUID(as_uuid=True), sa.ForeignKey("tenant_observed_mentions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("query_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_queries.id", ondelete="SET NULL"), nullable=True),
            sa.Column("subject_id", UUID(as_uuid=True), sa.ForeignKey("tenant_listening_subjects.id", ondelete="SET NULL"), nullable=True),
            sa.Column("match_type", sa.String(40), nullable=False),
            sa.Column("matched_term", sa.String(255), nullable=False),
            sa.Column("evidence_excerpt", sa.String(500), nullable=True),
            sa.Column("evidence_start", sa.Integer(), nullable=True),
            sa.Column("evidence_end", sa.Integer(), nullable=True),
            sa.Column("matcher_version", sa.String(40), nullable=False, server_default="listening_matcher_v1"),
            _ts("created_at"),
            sa.UniqueConstraint(
                "tenant_id", "mention_id", "query_id", "matched_term", "match_type",
                name="uq_tenant_mention_matches_identity",
            ),
        )
    create_index_if_missing("ix_tenant_mention_matches_tenant_id", "tenant_mention_matches", ["tenant_id"])
    create_index_if_missing("ix_tenant_mention_matches_mention", "tenant_mention_matches", ["tenant_id", "mention_id"])
    create_index_if_missing("ix_tenant_mention_matches_query", "tenant_mention_matches", ["tenant_id", "query_id"])
    create_index_if_missing("ix_tenant_mention_matches_subject", "tenant_mention_matches", ["tenant_id", "subject_id"])

    if not table_exists("tenant_mention_reviews"):
        op.create_table(
            "tenant_mention_reviews",
            sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
            sa.Column("mention_id", UUID(as_uuid=True), sa.ForeignKey("tenant_observed_mentions.id", ondelete="CASCADE"), nullable=False),
            sa.Column("actor_user_id", UUID(as_uuid=True), nullable=True),
            sa.Column("previous_state", sa.String(40), nullable=False),
            sa.Column("new_state", sa.String(40), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            _ts("created_at"),
        )
    create_index_if_missing("ix_tenant_mention_reviews_tenant_id", "tenant_mention_reviews", ["tenant_id"])
    create_index_if_missing("ix_tenant_mention_reviews_mention", "tenant_mention_reviews", ["tenant_id", "mention_id", "created_at"])


def downgrade() -> None:
    for index_name, table_name in (
        ("ix_tenant_mention_reviews_mention", "tenant_mention_reviews"),
        ("ix_tenant_mention_reviews_tenant_id", "tenant_mention_reviews"),
        ("ix_tenant_mention_matches_subject", "tenant_mention_matches"),
        ("ix_tenant_mention_matches_query", "tenant_mention_matches"),
        ("ix_tenant_mention_matches_mention", "tenant_mention_matches"),
        ("ix_tenant_mention_matches_tenant_id", "tenant_mention_matches"),
        ("ix_tenant_observed_mentions_canonical_url", "tenant_observed_mentions"),
        ("ix_tenant_observed_mentions_fingerprint", "tenant_observed_mentions"),
        ("ix_tenant_observed_mentions_tenant_source", "tenant_observed_mentions"),
        ("ix_tenant_observed_mentions_tenant_project", "tenant_observed_mentions"),
        ("ix_tenant_observed_mentions_tenant_review", "tenant_observed_mentions"),
        ("ix_tenant_observed_mentions_tenant_observed", "tenant_observed_mentions"),
        ("ix_tenant_observed_mentions_tenant_published", "tenant_observed_mentions"),
        ("ix_tenant_observed_mentions_tenant_id", "tenant_observed_mentions"),
        ("ix_tenant_listening_ingestion_runs_project", "tenant_listening_ingestion_runs"),
        ("ix_tenant_listening_ingestion_runs_tenant_status", "tenant_listening_ingestion_runs"),
        ("ix_tenant_listening_ingestion_runs_tenant_created", "tenant_listening_ingestion_runs"),
        ("ix_tenant_listening_ingestion_runs_tenant_id", "tenant_listening_ingestion_runs"),
        ("ix_tenant_listening_sources_project", "tenant_listening_sources"),
        ("ix_tenant_listening_sources_tenant_id", "tenant_listening_sources"),
        ("ix_tenant_listening_queries_enabled", "tenant_listening_queries"),
        ("ix_tenant_listening_queries_project", "tenant_listening_queries"),
        ("ix_tenant_listening_queries_tenant_id", "tenant_listening_queries"),
        ("ix_tenant_listening_subjects_type", "tenant_listening_subjects"),
        ("ix_tenant_listening_subjects_project", "tenant_listening_subjects"),
        ("ix_tenant_listening_subjects_tenant_id", "tenant_listening_subjects"),
        ("ix_tenant_listening_projects_tenant_created", "tenant_listening_projects"),
        ("ix_tenant_listening_projects_tenant_status", "tenant_listening_projects"),
        ("ix_tenant_listening_projects_tenant_id", "tenant_listening_projects"),
    ):
        drop_index_if_exists(index_name, table_name)

    for table in (
        "tenant_mention_reviews",
        "tenant_mention_matches",
        "tenant_observed_mentions",
        "tenant_listening_ingestion_runs",
        "tenant_listening_sources",
        "tenant_listening_queries",
        "tenant_listening_subjects",
        "tenant_listening_projects",
    ):
        drop_table_if_exists(table)
