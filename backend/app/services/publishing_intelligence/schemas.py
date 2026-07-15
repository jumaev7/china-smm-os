"""Internal dataclasses for Publishing Intelligence (not API schemas)."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class CheckResult:
    check_key: str
    category: str
    status: str  # passed | warning | failed | not_applicable
    severity: str = "info"
    score: int | None = None
    weight: int = 1
    evidence: dict[str, Any] = field(default_factory=dict)
    recommendation_key: str | None = None
    recommendation_params: dict[str, Any] | None = None


@dataclass
class RecommendationItem:
    key: str
    category: str
    priority: str
    reason: str
    evidence_summary: str
    suggested_action: str
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "category": self.category,
            "priority": self.priority,
            "reason": self.reason,
            "evidence_summary": self.evidence_summary,
            "suggested_action": self.suggested_action,
            "params": self.params,
        }


@dataclass
class PlatformReviewResult:
    platform: str
    platform_score: int
    caption_score: int | None = None
    media_score: int | None = None
    cta_score: int | None = None
    hashtag_score: int | None = None
    language_score: int | None = None
    compliance_score: int | None = None
    recommendations: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class CategoryScore:
    category: str
    score: int
    weight: int
    applicable: bool
    evidence: dict[str, Any] = field(default_factory=dict)
    check_count: int = 0
    warning_count: int = 0
    failure_count: int = 0


@dataclass
class ReviewContext:
    """Normalized review-relevant content snapshot."""

    content_id: UUID
    tenant_id: UUID
    status: str
    platforms: list[str]
    captions: dict[str, str]  # lang -> text
    primary_language: str | None
    hashtags_raw: str
    hashtags: list[str]
    scheduled_for: datetime | None
    approved_at: datetime | None
    client_review_status: str | None
    media: dict[str, Any] | None
    content_type: str  # image | video | text | unknown
    keywords: list[str]
    cta_hint: str | None
    link: str | None


@dataclass
class ReviewEngineResult:
    review_id: UUID
    content_id: UUID
    review_version: int
    review_engine_version: str
    content_fingerprint: str
    overall_score: int
    status: str
    is_current: bool
    is_stale: bool
    primary_language: str | None
    target_platforms: list[str]
    summary: dict[str, Any]
    category_scores: dict[str, CategoryScore]
    platform_reviews: list[PlatformReviewResult]
    checks: list[CheckResult]
    recommendations: list[RecommendationItem]
    publish_readiness: str  # ready | ready_with_warnings | blocked
    created_at: datetime
    completed_at: datetime | None
