"""Pydantic schemas for Marketing Intelligence Platform (read-only APIs)."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MarketingSignalOut(BaseModel):
    id: str
    signal_id: str
    tenant_id: str
    signal_type: str
    entity_type: str | None = None
    entity_id: str | None = None
    occurred_at: str | None = None
    metadata: dict[str, Any] | None = None
    source: str
    severity: str
    confidence: float
    platform_event_id: str | None = None
    platform_event_type: str | None = None
    created_at: str | None = None


class MarketingSignalListResponse(BaseModel):
    items: list[MarketingSignalOut]
    total: int
    page: int
    page_size: int


class MarketingScoreOut(BaseModel):
    id: str
    category: str
    score: int
    weight: float
    scoring_version: str
    explanation: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    computed_at: str | None = None


class MarketingScoreListResponse(BaseModel):
    scoring_version: str
    items: list[MarketingScoreOut]


class MarketingRecommendationOut(BaseModel):
    id: str
    recommendation_key: str
    category: str
    title: str
    reason: str
    evidence: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None
    confidence: float
    priority: str
    status: str
    rule_id: str
    rule_version: str
    action_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MarketingRecommendationListResponse(BaseModel):
    items: list[MarketingRecommendationOut]
    total: int
    page: int
    page_size: int
    engine_version: str


class MarketingInsightOut(BaseModel):
    id: str
    kind: str
    title: str
    summary: str
    category: str | None = None
    severity: str
    explanation: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    related_signal_ids: list[str] | None = None
    created_at: str | None = None


class MarketingInsightListResponse(BaseModel):
    items: list[MarketingInsightOut]
    total: int
    page: int
    page_size: int


class HealthCategoryOut(BaseModel):
    category: str
    score: int
    weight: float
    scoring_version: str


class MarketingHealthResponse(BaseModel):
    overall_score: int
    scoring_version: str
    recommendation_engine_version: str
    open_recommendations: int
    recent_signals_7d: int
    categories: list[HealthCategoryOut]
    computed_at: str
    status: str


class ScoreHistoryOut(BaseModel):
    category: str
    score: int
    scoring_version: str
    recorded_at: str | None = None
    explanation: dict[str, Any] | None = None


class RecommendationHistoryOut(BaseModel):
    recommendation_key: str
    category: str
    title: str
    priority: str
    status: str
    rule_id: str
    recorded_at: str | None = None


class TrendOut(BaseModel):
    metric_key: str
    bucket_start: str | None = None
    bucket_end: str | None = None
    value: float
    sample_count: int = 0


class MarketingHistoryResponse(BaseModel):
    days: int = Field(..., ge=1)
    scores: list[ScoreHistoryOut]
    recommendations: list[RecommendationHistoryOut]
    trends: list[TrendOut]
