"""Revenue Engine v1 — deal pipeline, forecasting, and factory revenue analytics (read-only)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

DealStage = Literal[
    "lead",
    "qualified",
    "negotiation",
    "quotation",
    "sample",
    "contract",
    "won",
    "lost",
]

RevenueHealthStatus = Literal["healthy", "warning", "critical"]

GuidedActionKey = Literal[
    "open_buyer_acquisition_engine",
    "open_crm",
    "open_real_factory_pilot",
    "open_factory_platform",
]


class RevenueEngineDealRecord(BaseModel):
    deal_id: UUID
    title: str
    buyer_name: Optional[str] = None
    buyer_company: Optional[str] = None
    factory_id: UUID
    factory_name: Optional[str] = None
    value: float = 0.0
    currency: str = "UZS"
    stage: DealStage
    stage_label: str
    probability: int = Field(default=0, ge=0, le=100)
    expected_close_date: Optional[datetime] = None
    lead_id: Optional[UUID] = None
    crm_deal_status: Optional[str] = None
    lead_status: Optional[str] = None
    sources: List[str] = Field(default_factory=list)


class RevenueEngineDealsResponse(BaseModel):
    items: List[RevenueEngineDealRecord]
    total: int
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class PipelineStageCount(BaseModel):
    stage: DealStage
    label: str
    count: int
    value: float = 0.0
    weighted_value: float = 0.0


class RevenueEnginePipelineResponse(BaseModel):
    stages: List[PipelineStageCount]
    total_deals: int = 0
    active_deals: int = 0
    pipeline_value: float = 0.0
    weighted_pipeline_value: float = 0.0
    currency: str = "UZS"
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class RevenueEngineForecastResponse(BaseModel):
    pipeline_value: float = 0.0
    weighted_pipeline_value: float = 0.0
    expected_revenue: float = 0.0
    won_revenue: float = 0.0
    lost_revenue: float = 0.0
    currency: str = "UZS"
    forecast_quality: str = "medium"
    active_deals: int = 0
    won_deals: int = 0
    lost_deals: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class FactoryRevenueView(BaseModel):
    factory_id: UUID
    factory_name: str
    tenant_id: Optional[UUID] = None
    active_deals: int = 0
    won_deals: int = 0
    lost_deals: int = 0
    pipeline_value: float = 0.0
    weighted_pipeline_value: float = 0.0
    expected_revenue: float = 0.0
    won_revenue: float = 0.0
    average_deal_size: float = 0.0
    currency: str = "UZS"


class RevenueEngineFactoriesResponse(BaseModel):
    items: List[FactoryRevenueView]
    total: int
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class RevenueOpportunityItem(BaseModel):
    opportunity_id: str
    title: str
    subtitle: Optional[str] = None
    buyer_name: Optional[str] = None
    factory_name: Optional[str] = None
    value: float = 0.0
    stage: Optional[DealStage] = None
    probability: int = 0
    score: int = Field(default=0, ge=0, le=100)
    sources: List[str] = Field(default_factory=list)
    recommended_action: Optional[str] = None


class RevenueEngineOpportunitiesResponse(BaseModel):
    top_revenue_opportunities: List[RevenueOpportunityItem] = Field(default_factory=list)
    highest_value_buyers: List[RevenueOpportunityItem] = Field(default_factory=list)
    highest_value_factories: List[RevenueOpportunityItem] = Field(default_factory=list)
    total: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class RevenueHealthFactor(BaseModel):
    key: str
    label: str
    status: RevenueHealthStatus
    score: int = Field(default=0, ge=0, le=100)
    message: str


class RevenueEngineHealthResponse(BaseModel):
    status: RevenueHealthStatus = "warning"
    health_score: int = Field(default=0, ge=0, le=100)
    factors: List[RevenueHealthFactor] = Field(default_factory=list)
    pipeline_coverage_ratio: float = 0.0
    win_rate: float = 0.0
    active_deals: int = 0
    forecast_quality: str = "medium"
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class RevenueEngineExecutiveDashboard(BaseModel):
    total_pipeline_value: float = 0.0
    forecasted_revenue: float = 0.0
    won_revenue: float = 0.0
    lost_revenue: float = 0.0
    active_opportunities: int = 0
    deal_count: int = 0
    weighted_pipeline_value: float = 0.0
    currency: str = "UZS"


class RevenueEngineGuidedAction(BaseModel):
    key: GuidedActionKey
    title: str
    description: str
    route: str
    enabled: bool = True


class RevenueEngineGuidedActionsResponse(BaseModel):
    items: List[RevenueEngineGuidedAction]
    safety_notice: str


class RevenueEngineOverview(BaseModel):
    executive_dashboard: RevenueEngineExecutiveDashboard
    forecast: RevenueEngineForecastResponse
    pipeline: RevenueEnginePipelineResponse
    health: RevenueEngineHealthResponse
    top_opportunities: List[RevenueOpportunityItem] = Field(default_factory=list)
    factory_count: int = 0
    readiness_score: int = Field(default=0, ge=0, le=100)
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    guided_actions: List[RevenueEngineGuidedAction] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class RevenueEngineSummary(BaseModel):
    executive_dashboard: RevenueEngineExecutiveDashboard
    health_status: RevenueHealthStatus = "warning"
    health_score: int = Field(default=0, ge=0, le=100)
    readiness_score: int = Field(default=0, ge=0, le=100)
    forecast_quality: str = "medium"
    win_rate: float = 0.0
    active_deals: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class RevenueEngineRefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int = Field(ge=0, le=100)
    health_status: RevenueHealthStatus
    total_pipeline_value: float = 0.0
    forecasted_revenue: float = 0.0
    active_deals: int = 0
    safety_notice: str
