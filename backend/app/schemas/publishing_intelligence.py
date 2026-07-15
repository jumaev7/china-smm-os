"""API schemas for Publishing Intelligence (deterministic pre-publish review)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReviewCheckResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    check_key: str
    category: str
    status: str
    severity: str
    score: int | None = None
    weight: int = 1
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommendation_key: str | None = None
    recommendation_params: dict[str, Any] | None = None


class CategoryScoreResponse(BaseModel):
    category: str
    score: int
    weight: int
    applicable: bool
    warning_count: int = 0
    failure_count: int = 0
    evidence: dict[str, Any] = Field(default_factory=dict)


class PlatformReviewResponse(BaseModel):
    platform: str
    platform_score: int
    caption_score: int | None = None
    media_score: int | None = None
    cta_score: int | None = None
    hashtag_score: int | None = None
    language_score: int | None = None
    compliance_score: int | None = None
    recommendations: list[dict[str, Any]] = Field(default_factory=list)


class ReviewRecommendationResponse(BaseModel):
    key: str
    category: str
    priority: str
    reason: str
    evidence_summary: str
    suggested_action: str
    params: dict[str, Any] = Field(default_factory=dict)


class PublishingReviewResponse(BaseModel):
    review_id: UUID
    content_id: UUID
    review_version: int
    review_engine_version: str
    content_fingerprint: str
    overall_score: int
    status: str
    is_current: bool
    is_stale: bool
    primary_language: str | None = None
    target_platforms: list[str] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)
    category_scores: dict[str, CategoryScoreResponse] = Field(default_factory=dict)
    platform_reviews: list[PlatformReviewResponse] = Field(default_factory=list)
    checks: list[ReviewCheckResponse] = Field(default_factory=list)
    recommendations: list[ReviewRecommendationResponse] = Field(default_factory=list)
    publish_readiness: str = "ready_with_warnings"
    created_at: datetime | None = None
    completed_at: datetime | None = None


class PublishingReviewListResponse(BaseModel):
    items: list[PublishingReviewResponse]
    total: int
    page: int
    page_size: int


class PublishingPolicyCatalogResponse(BaseModel):
    catalog_version: str
    platforms: dict[str, Any]
    category_weights: dict[str, int]
    critical_score_cap: int
    low_score_threshold: int
    constraint_legend: dict[str, str]


class PublishingCheckCatalogResponse(BaseModel):
    engine_version: str
    categories: list[str]
    checks: list[dict[str, str]]


class PublishingValidateResponse(BaseModel):
    """Ephemeral validation distinct from persisted review — hard blockers only."""

    content_id: UUID
    publish_readiness: str
    overall_score: int | None = None
    is_advisory_score: bool = True
    hard_blockers: list[dict[str, Any]] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
