"""Pydantic schemas for Customer Success Journey (post-onboarding adoption)."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.customer_success import CustomerSuccessHealthScore

NorthStarGoal = Literal[
    "export_leads",
    "better_publishing",
    "more_buyers",
    "better_sales_pipeline",
    "brand_awareness",
]
JourneyStatus = Literal["not_started", "active", "completed"]
CheckpointStatus = Literal["locked", "pending", "in_progress", "achieved", "missed"]
RecommendationPriority = Literal["urgent", "high", "medium", "low"]
TimelineEntryType = Literal["checkpoint", "feature", "weekly_win", "outcome"]


class NorthStarGoalOption(BaseModel):
    key: NorthStarGoal
    label: str
    description: str


class JourneyCriterionResult(BaseModel):
    key: str
    label: str
    met: bool
    current_value: str
    target: str


class JourneyCheckpoint(BaseModel):
    id: str
    day: int
    label: str
    theme: str
    status: CheckpointStatus
    weight: int = Field(ge=0, le=100)
    achieved_at: datetime | None = None
    criteria: list[JourneyCriterionResult] = Field(default_factory=list)
    completion_percent: int = Field(default=0, ge=0, le=100)


class JourneyFeatureAdoption(BaseModel):
    key: str
    label: str
    adopted: bool
    score: int = Field(ge=0, le=100)
    first_used_at: datetime | None = None
    summary: str = ""


class JourneyRecommendation(BaseModel):
    id: str
    title: str
    detail: str
    priority: RecommendationPriority = "medium"
    href: str | None = None
    checkpoint_day: int | None = None
    north_star_goal: NorthStarGoal | None = None
    dismissed: bool = False


class JourneyWeeklyWin(BaseModel):
    id: str
    title: str
    detail: str
    category: str
    occurred_at: datetime
    href: str | None = None


class JourneyTimelineEntry(BaseModel):
    id: str
    entry_type: TimelineEntryType
    title: str
    detail: str
    occurred_at: datetime
    checkpoint_id: str | None = None
    feature_key: str | None = None


class JourneySuccessScore(BaseModel):
    score: int = Field(ge=0, le=100)
    label: str
    summary: str
    checkpoint_completion_pct: int = Field(ge=0, le=100)
    feature_breadth_pct: int = Field(ge=0, le=100)
    outcome_signals_pct: int = Field(ge=0, le=100)


class RenewalReadinessScore(BaseModel):
    score: int = Field(ge=0, le=100)
    label: str
    days_to_renewal: int | None = None
    subscription_status: str | None = None
    summary: str


class ExpansionOpportunity(BaseModel):
    id: str
    title: str
    detail: str
    signal_type: str
    href: str | None = None
    priority: RecommendationPriority = "medium"


class CustomerSuccessJourneyDashboard(BaseModel):
    tenant_id: UUID
    status: JourneyStatus
    north_star_goal: NorthStarGoal | None = None
    north_star_label: str | None = None
    platform_ready: bool = False
    journey_day: int = Field(default=0, ge=0, le=30)
    days_remaining: int = Field(default=30, ge=0)
    started_at: datetime | None = None
    current_checkpoint: str | None = None
    checkpoints: list[JourneyCheckpoint] = Field(default_factory=list)
    features: list[JourneyFeatureAdoption] = Field(default_factory=list)
    recommendations: list[JourneyRecommendation] = Field(default_factory=list)
    weekly_wins: list[JourneyWeeklyWin] = Field(default_factory=list)
    timeline: list[JourneyTimelineEntry] = Field(default_factory=list)
    success_score: JourneySuccessScore
    health_score: CustomerSuccessHealthScore | None = None
    renewal_readiness: RenewalReadinessScore
    expansion_opportunities: list[ExpansionOpportunity] = Field(default_factory=list)
    generated_at: datetime


class JourneyRefreshResponse(BaseModel):
    refreshed: bool
    journey: CustomerSuccessJourneyDashboard


class JourneyDismissRecommendationResponse(BaseModel):
    dismissed: bool
    recommendation_id: str
    journey: CustomerSuccessJourneyDashboard


class JourneyAdminTenantItem(BaseModel):
    tenant_id: UUID
    tenant_name: str
    journey_status: JourneyStatus
    journey_day: int
    north_star_goal: NorthStarGoal | None = None
    success_score: int
    health_score: int | None = None
    current_checkpoint: str | None = None
    at_risk: bool = False
    days_since_login: int | None = None


class JourneyAdminOverview(BaseModel):
    total_tenants: int
    active_journeys: int
    completed_journeys: int
    at_risk_count: int
    tenants: list[JourneyAdminTenantItem] = Field(default_factory=list)
    generated_at: datetime
