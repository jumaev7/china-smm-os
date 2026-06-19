"""Deal Risk Engine v2 — read-only deal health, risk classification, and close probability schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

DealRiskLevel = Literal[
    "healthy",
    "watchlist",
    "at_risk",
    "critical",
    "stalled",
    "lost_probability_high",
]

ConfidenceLevel = Literal["low", "medium", "high"]


class DealRiskEvaluation(BaseModel):
    deal_health_score: int = Field(ge=0, le=100)
    risk_level: DealRiskLevel
    close_probability: float = Field(ge=0, le=100)
    expected_close_date: Optional[datetime] = None
    confidence_level: ConfidenceLevel = "medium"
    risk_reasons: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class DealRiskOverview(BaseModel):
    healthy_deals: int = 0
    watchlist_deals: int = 0
    at_risk_deals: int = 0
    critical_deals: int = 0
    stalled_deals: int = 0
    lost_probability_high_deals: int = 0
    high_close_probability_deals: int = 0
    total_deals: int = 0
    average_health_score: int = 0
    total_at_risk_revenue: Decimal = Decimal("0")
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only intelligence — no automatic messaging, CRM updates, deal stage updates, or task execution."
    )


class DealRiskListItem(BaseModel):
    deal_id: UUID
    title: str
    buyer_name: Optional[str] = None
    buyer_company: Optional[str] = None
    lead_id: UUID
    client_id: UUID
    status: str
    deal_health_score: int
    risk_level: DealRiskLevel
    close_probability: float
    expected_close_date: Optional[datetime] = None
    revenue: Decimal = Decimal("0")
    currency: str = "UZS"


class DealRiskListResponse(BaseModel):
    items: List[DealRiskListItem]
    total: int


class DealRiskLinkedBuyer(BaseModel):
    buyer_id: UUID
    name: str
    company: Optional[str] = None
    buyer_score: int = 0
    classification: Optional[str] = None
    risk_level: Optional[str] = None


class DealRiskLinkedCommunication(BaseModel):
    thread_id: UUID
    channel: Optional[str] = None
    title: Optional[str] = None
    message_count: int = 0


class DealRiskLinkedProposal(BaseModel):
    proposal_id: UUID
    title: str
    status: str
    updated_at: Optional[datetime] = None


class DealRiskLinkedTask(BaseModel):
    task_id: UUID
    title: str
    status: str
    priority: str = "medium"
    due_at: Optional[datetime] = None
    is_overdue: bool = False


class DealRiskDetail(BaseModel):
    deal_id: UUID
    title: str
    status: str
    client_id: UUID
    lead_id: UUID
    buyer_name: Optional[str] = None
    buyer_company: Optional[str] = None
    expected_value: Optional[Decimal] = None
    currency: str = "UZS"
    deal_health_score: int
    risk_level: DealRiskLevel
    close_probability: float
    expected_close_date: Optional[datetime] = None
    confidence_level: ConfidenceLevel = "medium"
    risk_reasons: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    risk_factors: List[str] = Field(default_factory=list)
    linked_buyer_intelligence: Optional[DealRiskLinkedBuyer] = None
    linked_communications: List[DealRiskLinkedCommunication] = Field(default_factory=list)
    linked_proposals: List[DealRiskLinkedProposal] = Field(default_factory=list)
    linked_tasks: List[DealRiskLinkedTask] = Field(default_factory=list)
    last_activity_at: Optional[datetime] = None


class DealRiskRankingItem(BaseModel):
    rank: int
    deal_id: UUID
    title: str
    buyer_name: Optional[str] = None
    deal_health_score: int
    risk_level: DealRiskLevel
    close_probability: float
    revenue: Decimal = Decimal("0")
    risk_reasons: List[str] = Field(default_factory=list)


class DealRiskHighRiskResponse(BaseModel):
    items: List[DealRiskRankingItem] = Field(default_factory=list)
    total: int = 0
    largest_at_risk_revenue: Decimal = Decimal("0")
    requiring_intervention: int = 0
    errors: List[str] = Field(default_factory=list)


class DealRiskOpportunityItem(BaseModel):
    rank: int
    deal_id: UUID
    title: str
    buyer_name: Optional[str] = None
    close_probability: float
    expected_close_date: Optional[datetime] = None
    revenue: Decimal = Decimal("0")
    deal_health_score: int


class DealRiskOpportunitiesResponse(BaseModel):
    items: List[DealRiskOpportunityItem] = Field(default_factory=list)
    likely_close_this_month: int = 0
    total: int = 0
    errors: List[str] = Field(default_factory=list)


class DealRiskRecalculateRequest(BaseModel):
    client_id: Optional[UUID] = None
    limit: int = Field(200, ge=1, le=500)


class DealRiskRecalculateResponse(BaseModel):
    evaluated: int = 0
    overview: DealRiskOverview
    message: str = ""
    errors: List[str] = Field(default_factory=list)


class DealRiskSummaryWidget(BaseModel):
    healthy_deals: int = 0
    at_risk_deals: int = 0
    critical_deals: int = 0
    high_close_probability_deals: int = 0
    average_health_score: int = 0
    total_at_risk_revenue: Decimal = Decimal("0")
    top_risk_deal_title: Optional[str] = None
    errors: List[str] = Field(default_factory=list)


class DealRiskExecutiveInsights(BaseModel):
    overview: DealRiskOverview
    highest_risk_deals: List[DealRiskRankingItem] = Field(default_factory=list)
    largest_at_risk_revenue: Decimal = Decimal("0")
    requiring_intervention: int = 0
    likely_close_this_month: List[DealRiskOpportunityItem] = Field(default_factory=list)
