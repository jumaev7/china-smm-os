"""Internal schemas for Social Listening adapters (not API models)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class SourceCapabilities:
    source_type: str
    capability_status: str  # import_only | fixture_only | live | unsupported
    supports_keyword_search: bool = False
    supports_account_feed: bool = False
    supports_historical_window: bool = False
    pagination_type: str = "none"  # none | cursor | offset
    engagement_fields_available: bool = False
    author_fields_available: bool = False
    deletion_signals_available: bool = False
    notes: str = ""
    unsupported_reason: str | None = None


@dataclass
class RawObservation:
    """Provider/adapter-native observation before normalization."""

    provider_external_id: str | None = None
    canonical_url: str | None = None
    author_display: str | None = None
    author_external_id: str | None = None
    content_text: str | None = None
    content_type: str = "post"
    language: str | None = None
    published_at: datetime | None = None
    source_updated_at: datetime | None = None
    engagement: dict[str, Any] | None = None
    provider_account_ref: str = ""
    raw_safe_summary: dict[str, Any] = field(default_factory=dict)
    malformed: bool = False
    reject_reason: str | None = None


@dataclass
class ObservationPage:
    items: list[RawObservation]
    next_cursor: str | None = None
    provider_request_id: str | None = None
    fetched_count: int = 0
    rejected_count: int = 0
    error_summary: str | None = None


@dataclass
class NormalizedMentionDraft:
    source_type: str
    observation_origin: str
    provider_account_ref: str
    provider_external_id: str | None
    canonical_url: str | None
    author_display: str | None
    author_external_id: str | None
    content_text: str | None
    content_excerpt: str | None
    content_type: str
    language: str | None
    published_at: datetime | None
    source_updated_at: datetime | None
    observed_at: datetime
    engagement_json: dict[str, Any] | None
    content_fingerprint: str
    dedupe_key: str
    dedupe_version: str
    normalization_version: str
    provenance_json: dict[str, Any]


@dataclass(frozen=True)
class MatchEvidence:
    query_id: Any
    subject_id: Any
    match_type: str
    matched_term: str
    evidence_excerpt: str | None
    evidence_start: int | None
    evidence_end: int | None
    matcher_version: str


__all__ = [
    "SourceCapabilities",
    "RawObservation",
    "ObservationPage",
    "NormalizedMentionDraft",
    "MatchEvidence",
]
