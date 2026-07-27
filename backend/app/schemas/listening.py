"""Pydantic schemas for Social Listening Phase 1 APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

ProjectStatus = Literal["active", "paused", "archived"]
SubjectType = Literal["own_brand", "competitor", "product", "topic", "other"]
ReviewState = Literal["unreviewed", "relevant", "irrelevant", "needs_follow_up", "resolved"]
SourceType = Literal[
    "manual_import",
    "fixture",
    "facebook_page_comments",
    "facebook_page_mentions",
]


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    client_id: UUID | None = None
    default_locale: str | None = Field(None, max_length=10)


class ProjectUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    status: ProjectStatus | None = None
    default_locale: str | None = Field(None, max_length=10)


class SubjectCreateRequest(BaseModel):
    subject_type: SubjectType
    canonical_name: str = Field(..., min_length=1, max_length=200)
    aliases: list[str] = Field(default_factory=list, max_length=40)
    handle: str | None = Field(None, max_length=200)
    domain: str | None = Field(None, max_length=255)
    metadata: dict[str, Any] | None = None


class SubjectUpdateRequest(BaseModel):
    canonical_name: str | None = Field(None, min_length=1, max_length=200)
    aliases: list[str] | None = Field(None, max_length=40)
    handle: str | None = Field(None, max_length=200)
    domain: str | None = Field(None, max_length=255)
    is_active: bool | None = None


class QueryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    include_terms: list[str] = Field(default_factory=list, max_length=40)
    exclude_terms: list[str] = Field(default_factory=list, max_length=40)
    source_filters: list[str] = Field(default_factory=list, max_length=20)
    language_filters: list[str] = Field(default_factory=list, max_length=20)
    subject_id: UUID | None = None


class QueryUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    include_terms: list[str] | None = Field(None, max_length=40)
    exclude_terms: list[str] | None = Field(None, max_length=40)
    source_filters: list[str] | None = Field(None, max_length=20)
    language_filters: list[str] | None = Field(None, max_length=20)
    is_enabled: bool | None = None
    subject_id: UUID | None = None


class LiveSourceCreateRequest(BaseModel):
    source_type: Literal["facebook_page_comments", "facebook_page_mentions"]
    publishing_account_id: UUID
    display_name: str | None = Field(None, min_length=1, max_length=200)
    poll_interval_seconds: int | None = Field(None, ge=300, le=86400)
    source_key: str | None = Field(None, max_length=80)


class SourceUpdateRequest(BaseModel):
    is_enabled: bool | None = None
    display_name: str | None = Field(None, min_length=1, max_length=200)
    poll_interval_seconds: int | None = Field(None, ge=300, le=86400)


class ReviewUpdateRequest(BaseModel):
    review_state: ReviewState
    note: str | None = Field(None, max_length=4000)


class ManualImportRequest(BaseModel):
    items: list[dict[str, Any]] = Field(..., min_length=1, max_length=500)
    source_id: UUID | None = None

    @field_validator("items")
    @classmethod
    def validate_items_size(cls, value: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(value) > 500:
            raise ValueError("at most 500 items")
        # Bound serialized payload size (mirrors service MAX_IMPORT_PAYLOAD_BYTES).
        from app.services.listening.limits import (
            MAX_IMPORT_PAYLOAD_BYTES,
            import_payload_byte_size,
        )

        size = import_payload_byte_size(value)
        if size > MAX_IMPORT_PAYLOAD_BYTES:
            raise ValueError(f"import payload exceeds {MAX_IMPORT_PAYLOAD_BYTES} bytes")
        return value


class FixtureIngestRequest(BaseModel):
    source_id: UUID | None = None


class ProjectResponse(BaseModel):
    id: UUID
    client_id: UUID | None = None
    name: str
    description: str | None = None
    status: str
    default_locale: str | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None


class ProjectListResponse(BaseModel):
    items: list[ProjectResponse]
    total: int
    limit: int
    offset: int


class SubjectResponse(BaseModel):
    id: UUID
    project_id: UUID
    subject_type: str
    canonical_name: str
    aliases: list[str] = Field(default_factory=list)
    handle: str | None = None
    domain: str | None = None
    is_active: bool
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class QueryResponse(BaseModel):
    id: UUID
    project_id: UUID
    subject_id: UUID | None = None
    name: str
    include_terms: list[str] = Field(default_factory=list)
    exclude_terms: list[str] = Field(default_factory=list)
    source_filters: list[str] = Field(default_factory=list)
    language_filters: list[str] = Field(default_factory=list)
    is_enabled: bool
    created_by_user_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class SourceResponse(BaseModel):
    id: UUID
    project_id: UUID
    source_type: str
    source_key: str
    display_name: str
    is_enabled: bool
    capability_status: str
    freshness_status: str
    freshness_watermark: datetime | None = None
    last_success_at: datetime | None = None
    integration_id: UUID | None = None
    provider_resource_ref: str | None = None
    health_status: str | None = None
    last_failure_at: datetime | None = None
    last_failure_code: str | None = None
    last_failure_summary: str | None = None
    last_checkpoint: str | None = None
    poll_interval_seconds: int | None = None
    provider_capability_version: str | None = None
    enabled_capabilities: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    observation_origin: str | None = None
    provider_limitation_text: str | None = None
    required_permissions: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class MatchResponse(BaseModel):
    id: UUID
    mention_id: UUID
    query_id: UUID | None = None
    subject_id: UUID | None = None
    match_type: str
    matched_term: str
    evidence_excerpt: str | None = None
    evidence_start: int | None = None
    evidence_end: int | None = None
    matcher_version: str
    created_at: datetime


class MentionResponse(BaseModel):
    id: UUID
    project_id: UUID | None = None
    source_id: UUID | None = None
    source_type: str
    observation_origin: str
    provider_account_ref: str | None = None
    provider_external_id: str | None = None
    canonical_url: str | None = None
    author_display: str | None = None
    content_excerpt: str | None = None
    content_text: str | None = None
    content_type: str
    language: str | None = None
    published_at: datetime | None = None
    observed_at: datetime
    first_observed_at: datetime
    last_observed_at: datetime
    source_updated_at: datetime | None = None
    engagement: dict[str, Any] | None = None
    review_state: str
    dedupe_version: str | None = None
    normalization_version: str | None = None
    ingestion_run_id: UUID | None = None
    provenance: dict[str, Any] | None = None
    matches: list[MatchResponse] = Field(default_factory=list)
    author_external_id: str | None = None
    content_fingerprint: str | None = None
    dedupe_key: str | None = None
    created_at: datetime
    updated_at: datetime


class MentionListResponse(BaseModel):
    items: list[MentionResponse]
    total: int
    limit: int
    offset: int


class ReviewResponse(BaseModel):
    id: UUID
    mention_id: UUID
    actor_user_id: UUID | None = None
    previous_state: str
    new_state: str
    note: str | None = None
    created_at: datetime


class IngestionRunResponse(BaseModel):
    id: UUID
    project_id: UUID | None = None
    source_id: UUID | None = None
    source_type: str
    trigger_type: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    fetched_count: int
    created_count: int
    updated_count: int
    duplicate_count: int
    rejected_count: int
    error_count: int
    match_count: int
    error_summary: str | None = None
    cursor_before: str | None = None
    cursor_after: str | None = None
    freshness_watermark: datetime | None = None
    provider_request_id: str | None = None
    created_by_user_id: UUID | None = None
    created_at: datetime


class IngestionRunListResponse(BaseModel):
    items: list[IngestionRunResponse]
    total: int
    limit: int
    offset: int


class OverviewResponse(BaseModel):
    schema_version: str
    coverage_notice: str
    live_provider_available: bool
    fixture_ingest_available: bool = True
    live_source_types: list[str] = []
    project_count: int
    projects: list[dict[str, Any]]
    mention_total: int
    unreviewed_count: int
    recent_mentions: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    recent_ingestion_runs: list[dict[str, Any]]
    source_capabilities: list[dict[str, Any]]


# ---- Phase 2 market intelligence schemas ----

WindowKey = Literal["7d", "30d", "90d", "custom"]
GranularityLit = Literal["hour", "day", "week"]
ReviewPolicy = Literal[
    "default_exclude_irrelevant",
    "include_all",
    "relevant_only",
]
InsightReviewState = Literal[
    "unreviewed",
    "acknowledged",
    "dismissed",
    "monitoring",
    "resolved",
]


class InsightReviewUpdateRequest(BaseModel):
    review_state: InsightReviewState
    note: str | None = Field(None, max_length=4000)


class InsightReviewResponse(BaseModel):
    id: UUID
    insight_key: str
    actor_user_id: UUID | None = None
    previous_state: str
    new_state: str
    note: str | None = None
    methodology_version: str | None = None
    created_at: datetime


__all__ = [
    "ProjectCreateRequest",
    "ProjectUpdateRequest",
    "SubjectCreateRequest",
    "SubjectUpdateRequest",
    "QueryCreateRequest",
    "QueryUpdateRequest",
    "SourceUpdateRequest",
    "ReviewUpdateRequest",
    "ManualImportRequest",
    "FixtureIngestRequest",
    "ProjectResponse",
    "ProjectListResponse",
    "SubjectResponse",
    "QueryResponse",
    "SourceResponse",
    "MatchResponse",
    "MentionResponse",
    "MentionListResponse",
    "ReviewResponse",
    "IngestionRunResponse",
    "IngestionRunListResponse",
    "OverviewResponse",
    "InsightReviewUpdateRequest",
    "InsightReviewResponse",
]
