"""Social Listening Phase 1 — Observed Mentions Foundation (tenant-scoped).

Read-only observation of external market mentions. Does not publish, reply,
DM, react, or mutate provider content. Coverage is limited to configured
supported sources (manual import / fixture in Phase 1).

Design notes:
- Mentions are normalized observations with explicit provenance and origin.
- Deduplication is deterministic (provider identity → URL → fingerprint).
- Matching is explainable phrase/alias matching with retained evidence.
- Review state is an internal workflow only — never triggers provider actions.
- Sentiment and Business Health scoring are intentionally deferred.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

LISTENING_SCHEMA_VERSION = "1.3.0"
DEDUPE_VERSION = "listening_dedupe_v1"
MATCHER_VERSION = "listening_matcher_v1"
NORMALIZATION_VERSION = "listening_norm_v1"
INSIGHT_REVIEW_STATES = frozenset({
    "unreviewed",
    "acknowledged",
    "dismissed",
    "monitoring",
    "resolved",
})

PROJECT_STATUSES = frozenset({"active", "paused", "archived"})
SUBJECT_TYPES = frozenset({"own_brand", "competitor", "product", "topic", "other"})
SOURCE_TYPES = frozenset({
    "manual_import",
    "fixture",
    "facebook_page_comments",
    "facebook_page_mentions",
})
LIVE_SOURCE_TYPES = frozenset({"facebook_page_comments", "facebook_page_mentions"})
OBSERVATION_ORIGINS = frozenset({"manual_import", "fixture", "live_provider", "webhook"})
SOURCE_HEALTH_STATUSES = frozenset({
    "unknown",
    "healthy",
    "healthy_zero",
    # Sanitized live validation states (never Meta payloads / tokens).
    "missing_scope",
    "insufficient_app_access",
    "page_not_authorized",
    "token_expired_or_revoked",
    "rate_limited",
    "provider_unavailable",
    "unsupported_capability",
    # Operational / config states
    "malformed_provider_response",
    "invalid_configuration",
    "missing_credentials",
    "paused",
    "disabled",
    "internal_processing_failure",
    # Legacy alias retained for rows written before Phase 3 rename.
    "revoked_authorization",
})
CONTENT_TYPES = frozenset({"post", "comment", "article", "other"})
REVIEW_STATES = frozenset({
    "unreviewed",
    "relevant",
    "irrelevant",
    "needs_follow_up",
    "resolved",
})
MATCH_TYPES = frozenset({
    "phrase",
    "alias",
    "keyword",
    "handle",
    "domain",
    "url",
})
INGESTION_RUN_STATUSES = frozenset({
    "pending",
    "running",
    "succeeded",
    "partial",
    "failed",
    "cancelled",
})
INGESTION_TRIGGER_TYPES = frozenset({
    "manual",
    "scheduled",
    "import",
    "fixture",
    "sync",
    "webhook",
})
WEBHOOK_EVENT_STATUSES = frozenset({
    "pending", "processing", "succeeded", "retry", "dead_letter",
})
FRESHNESS_STATUSES = frozenset({
    "fresh",
    "aging",
    "stale",
    "unavailable",
    "unsupported",
})


class TenantListeningProject(Base):
    """Tenant-scoped listening initiative."""

    __tablename__ = "tenant_listening_projects"
    __table_args__ = (
        Index("ix_tenant_listening_projects_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_listening_projects_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="active")
    default_locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantListeningSubject(Base):
    """What is being monitored (brand, competitor, product, topic, other)."""

    __tablename__ = "tenant_listening_subjects"
    __table_args__ = (
        Index("ix_tenant_listening_subjects_project", "tenant_id", "project_id"),
        Index("ix_tenant_listening_subjects_type", "tenant_id", "subject_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(String(40), nullable=False)
    canonical_name: Mapped[str] = mapped_column(String(200), nullable=False)
    aliases_json: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    handle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    metadata_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantListeningQuery(Base):
    """Explicit, inspectable monitoring rule."""

    __tablename__ = "tenant_listening_queries"
    __table_args__ = (
        Index("ix_tenant_listening_queries_project", "tenant_id", "project_id"),
        Index("ix_tenant_listening_queries_enabled", "tenant_id", "is_enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_subjects.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    include_terms_json: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    exclude_terms_json: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    source_filters_json: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    language_filters_json: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantListeningSource(Base):
    """Configured source for a listening project (capability-honest)."""

    __tablename__ = "tenant_listening_sources"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "project_id", "source_type", "source_key",
            name="uq_tenant_listening_sources_identity",
        ),
        Index("ix_tenant_listening_sources_project", "tenant_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_key: Mapped[str] = mapped_column(String(80), nullable=False, server_default="default")
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    capability_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="import_only",
    )
    config_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    # Phase 3 live-source binding (tokens remain on publishing_accounts only).
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider_resource_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    health_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unknown",
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_failure_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    last_checkpoint: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    poll_interval_seconds: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    provider_capability_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    enabled_capabilities_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    lock_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lock_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    freshness_status: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unavailable",
    )
    freshness_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantObservedMention(Base):
    """Normalized external content observation."""

    __tablename__ = "tenant_observed_mentions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "source_type",
            "provider_account_ref",
            "provider_external_id",
            name="uq_tenant_observed_mentions_provider_identity",
        ),
        UniqueConstraint(
            "tenant_id",
            "dedupe_key",
            name="uq_tenant_observed_mentions_dedupe_key",
        ),
        Index("ix_tenant_observed_mentions_tenant_published", "tenant_id", "published_at"),
        Index("ix_tenant_observed_mentions_tenant_observed", "tenant_id", "observed_at"),
        Index("ix_tenant_observed_mentions_tenant_review", "tenant_id", "review_state"),
        Index("ix_tenant_observed_mentions_tenant_project", "tenant_id", "project_id"),
        Index("ix_tenant_observed_mentions_tenant_source", "tenant_id", "source_type"),
        Index("ix_tenant_observed_mentions_fingerprint", "tenant_id", "content_fingerprint"),
        Index("ix_tenant_observed_mentions_canonical_url", "tenant_id", "canonical_url"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    observation_origin: Mapped[str] = mapped_column(String(40), nullable=False)
    provider_account_ref: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="",
    )
    provider_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    canonical_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    author_display: Mapped[str | None] = mapped_column(String(255), nullable=True)
    author_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text(), nullable=True)
    content_excerpt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="post")
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    engagement_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    content_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False)
    dedupe_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=DEDUPE_VERSION,
    )
    normalization_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=NORMALIZATION_VERSION,
    )
    review_state: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="unreviewed",
    )
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_ingestion_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    provenance_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantMentionMatch(Base):
    """Why a mention matched a query/subject — evidence retained for humans."""

    __tablename__ = "tenant_mention_matches"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "mention_id",
            "query_id",
            "matched_term",
            "match_type",
            name="uq_tenant_mention_matches_identity",
        ),
        Index("ix_tenant_mention_matches_mention", "tenant_id", "mention_id"),
        Index("ix_tenant_mention_matches_query", "tenant_id", "query_id"),
        Index("ix_tenant_mention_matches_subject", "tenant_id", "subject_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    mention_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_observed_mentions.id", ondelete="CASCADE"),
        nullable=False,
    )
    query_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_queries.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_subjects.id", ondelete="SET NULL"),
        nullable=True,
    )
    match_type: Mapped[str] = mapped_column(String(40), nullable=False)
    matched_term: Mapped[str] = mapped_column(String(255), nullable=False)
    evidence_excerpt: Mapped[str | None] = mapped_column(String(500), nullable=True)
    evidence_start: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    evidence_end: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    matcher_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default=MATCHER_VERSION,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantMentionReview(Base):
    """Audited internal review-state transition. Never calls providers."""

    __tablename__ = "tenant_mention_reviews"
    __table_args__ = (
        Index("ix_tenant_mention_reviews_mention", "tenant_id", "mention_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    mention_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_observed_mentions.id", ondelete="CASCADE"),
        nullable=False,
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    previous_state: Mapped[str] = mapped_column(String(40), nullable=False)
    new_state: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantListeningInsightReview(Base):
    """Append-only analyst review of a deterministic MarketInsight identity.

    Does not modify source mentions, trigger providers, CRM, or outreach.
    Insight facts remain computed; only review state is persisted.
    """

    __tablename__ = "tenant_listening_insight_reviews"
    __table_args__ = (
        Index(
            "ix_tenant_listening_insight_reviews_tenant_key_created",
            "tenant_id",
            "insight_key",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    insight_key: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    previous_state: Mapped[str] = mapped_column(String(40), nullable=False)
    new_state: Mapped[str] = mapped_column(String(40), nullable=False)
    note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    window_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    methodology_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantListeningIngestionRun(Base):
    """Observability for a single read-only ingestion/import run."""

    __tablename__ = "tenant_listening_ingestion_runs"
    __table_args__ = (
        Index("ix_tenant_listening_ingestion_runs_tenant_created", "tenant_id", "created_at"),
        Index("ix_tenant_listening_ingestion_runs_tenant_status", "tenant_id", "status"),
        Index("ix_tenant_listening_ingestion_runs_project", "tenant_id", "project_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_sources.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    trigger_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="manual")
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    duplicate_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    rejected_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    match_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    error_summary: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cursor_before: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    checkpoint_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    freshness_watermark: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantListeningWebhookEvent(Base):
    """Signed notification routed to one tenant-owned listening source."""

    __tablename__ = "tenant_listening_webhook_events"
    __table_args__ = (
        UniqueConstraint("source_id", "event_key", name="uq_listening_webhook_source_event"),
        Index("ix_listening_webhook_events_status_due", "status", "next_attempt_at"),
        Index("ix_listening_webhook_events_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_projects.id", ondelete="CASCADE"), nullable=False,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_listening_sources.id", ondelete="CASCADE"), nullable=False,
    )
    event_key: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_object_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_field: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    payload_summary_json: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


__all__ = [
    "LISTENING_SCHEMA_VERSION",
    "DEDUPE_VERSION",
    "MATCHER_VERSION",
    "NORMALIZATION_VERSION",
    "PROJECT_STATUSES",
    "SUBJECT_TYPES",
    "SOURCE_TYPES",
    "LIVE_SOURCE_TYPES",
    "SOURCE_HEALTH_STATUSES",
    "OBSERVATION_ORIGINS",
    "CONTENT_TYPES",
    "REVIEW_STATES",
    "MATCH_TYPES",
    "INGESTION_RUN_STATUSES",
    "INGESTION_TRIGGER_TYPES",
    "WEBHOOK_EVENT_STATUSES",
    "FRESHNESS_STATUSES",
    "TenantListeningProject",
    "TenantListeningSubject",
    "TenantListeningQuery",
    "TenantListeningSource",
    "TenantObservedMention",
    "TenantMentionMatch",
    "TenantMentionReview",
    "TenantListeningInsightReview",
    "TenantListeningIngestionRun",
    "TenantListeningWebhookEvent",
    "INSIGHT_REVIEW_STATES",
]
