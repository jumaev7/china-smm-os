"""Pydantic schemas for Customer Success & Factory ROI Center."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.buyer_crm import DistributionItem

HealthStatus = Literal["healthy", "needs_attention", "at_risk"]
ReportPeriod = Literal["monthly", "quarterly"]
InsightCategory = Literal["working", "not_working", "market", "buyer", "activity"]
ChurnRiskLevel = Literal["low", "medium", "high"]


class RoiConfigWeights(BaseModel):
    """Configurable ROI calculation weights — extend without schema changes."""
    pipeline_weight: float = Field(default=0.35, ge=0, le=1)
    proposal_weight: float = Field(default=0.25, ge=0, le=1)
    won_deals_weight: float = Field(default=0.40, ge=0, le=1)
    lead_value_multiplier: float = Field(default=500.0, ge=0)


class FactoryRoiKpis(BaseModel):
    total_leads_generated: int = 0
    total_buyers_added: int = 0
    active_buyers: int = 0
    deals_created: int = 0
    deals_won: int = 0
    proposal_value: Decimal = Decimal("0")
    pipeline_value: Decimal = Decimal("0")
    estimated_revenue_influenced: Decimal = Decimal("0")
    communication_messages: int = 0
    content_items_created: int = 0


class RoiCalculation(BaseModel):
    subscription_cost: Decimal = Decimal("0")
    subscription_currency: str = "USD"
    leads_generated: int = 0
    deals_created: int = 0
    pipeline_value: Decimal = Decimal("0")
    proposal_value: Decimal = Decimal("0")
    won_revenue: Decimal = Decimal("0")
    value_generated: Decimal = Decimal("0")
    revenue_influenced: Decimal = Decimal("0")
    estimated_roi_pct: float = 0.0
    roi_label: str = "Not yet measurable"
    config: RoiConfigWeights = Field(default_factory=RoiConfigWeights)


class AdoptionMetric(BaseModel):
    key: str
    label: str
    count: int
    period_count: int = 0
    score: int = Field(ge=0, le=100)


class AdoptionDashboard(BaseModel):
    metrics: list[AdoptionMetric]
    engagement_score: int = Field(ge=0, le=100)
    user_logins_30d: int = 0
    active_users: int = 0
    total_users: int = 0


class BusinessImpactMetrics(BaseModel):
    buyers_acquired: int = 0
    buyers_reactivated: int = 0
    opportunities_created: int = 0
    proposal_acceptance_rate: float = 0.0
    average_deal_progression_days: float = 0.0
    won_deal_value: Decimal = Decimal("0")
    pipeline_created_value: Decimal = Decimal("0")


class HealthScoreFactor(BaseModel):
    factor: str
    label: str
    score: int = Field(ge=0, le=100)
    weight_pct: float
    summary: str


class CustomerSuccessHealthScore(BaseModel):
    score: int = Field(ge=0, le=100)
    status: HealthStatus
    label: str
    summary: str
    factors: list[HealthScoreFactor]


class AiInsight(BaseModel):
    id: str
    category: InsightCategory
    title: str
    detail: str
    priority: Literal["urgent", "high", "medium", "low"] = "medium"
    href: str | None = None


class ExecutiveReportSection(BaseModel):
    title: str
    bullets: list[str]


class ExecutiveReport(BaseModel):
    period: ReportPeriod
    title: str
    generated_at: datetime
    executive_summary: str
    sections: list[ExecutiveReportSection]
    kpis: FactoryRoiKpis
    roi: RoiCalculation
    health_score: CustomerSuccessHealthScore


class ChurnRiskItem(BaseModel):
    tenant_id: UUID
    tenant_name: str
    risk_level: ChurnRiskLevel
    health_score: int
    days_since_login: int | None
    subscription_status: str | None
    reasons: list[str]
    recommendations: list[str]


class AdminTenantSummary(BaseModel):
    tenant_id: UUID
    tenant_name: str
    status: str
    plan_name: str | None
    health_score: int
    health_status: HealthStatus
    engagement_score: int
    estimated_roi_pct: float
    pipeline_value: Decimal
    active_buyers: int
    churn_risk: ChurnRiskLevel


class CustomerSuccessDashboardResponse(BaseModel):
    roi_kpis: FactoryRoiKpis
    roi: RoiCalculation
    health_score: CustomerSuccessHealthScore
    adoption_summary: AdoptionDashboard
    business_impact: BusinessImpactMetrics
    insights: list[AiInsight]
    top_markets: list[DistributionItem] = Field(default_factory=list)
    is_demo: bool = False
    generated_at: datetime


class CustomerSuccessSummaryResponse(BaseModel):
    customer_health_score: CustomerSuccessHealthScore
    adoption_score: int = Field(default=0, ge=0, le=100)
    roi_estimate: RoiCalculation
    active_users: int = 0
    content_activity: int = 0
    crm_activity: int = 0
    churn_risk: ChurnRiskLevel = "low"
    top_insights: list[AiInsight] = Field(default_factory=list)
    is_demo: bool = False
    generated_at: datetime
