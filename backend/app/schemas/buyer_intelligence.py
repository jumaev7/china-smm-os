"""Buyer Intelligence v2 — read-only buyer scoring and classification schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

BuyerClassification = Literal[
    "hot_buyer",
    "strategic_buyer",
    "high_potential_buyer",
    "active_buyer",
    "inactive_buyer",
    "price_sensitive_buyer",
    "at_risk_buyer",
]
RiskLevel = Literal["low", "medium", "high", "critical"]


class BuyerPotential(BaseModel):
    expected_annual_revenue: Decimal = Decimal("0")
    expected_deal_size: Decimal = Decimal("0")
    growth_potential: str = "stable"
    currency: str = "UZS"


class BuyerIntelligenceInsight(BaseModel):
    buyer_score: int = Field(ge=0, le=100)
    classification: BuyerClassification
    risk_level: RiskLevel = "low"
    annual_potential: Decimal = Decimal("0")
    insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)


class BuyerIntelligenceOverview(BaseModel):
    hot_buyers: int = 0
    strategic_buyers: int = 0
    high_potential_buyers: int = 0
    active_buyers: int = 0
    inactive_buyers: int = 0
    price_sensitive_buyers: int = 0
    at_risk_buyers: int = 0
    total_buyers: int = 0
    average_buyer_score: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str = (
        "Read-only intelligence — no automatic messaging, CRM updates, deal updates, or task execution."
    )


class BuyerListItem(BaseModel):
    buyer_id: UUID
    name: str
    company: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    buyer_score: int
    classification: BuyerClassification
    annual_potential: Decimal = Decimal("0")
    risk_level: RiskLevel = "low"
    status: str = "new"
    client_id: UUID


class BuyerListResponse(BaseModel):
    items: List[BuyerListItem]
    total: int


class BuyerLinkedDeal(BaseModel):
    deal_id: UUID
    title: str
    status: str
    expected_value: Optional[Decimal] = None
    updated_at: Optional[datetime] = None


class BuyerLinkedProposal(BaseModel):
    proposal_id: UUID
    title: str
    status: str
    updated_at: Optional[datetime] = None


class BuyerLinkedCommunication(BaseModel):
    thread_id: UUID
    channel: Optional[str] = None
    title: Optional[str] = None
    message_count: int = 0


class BuyerIntelligenceDetail(BaseModel):
    buyer_id: UUID
    name: str
    company: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    status: str
    client_id: UUID
    buyer_score: int
    classification: BuyerClassification
    risk_level: RiskLevel
    potential: BuyerPotential
    insights: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    linked_deals: List[BuyerLinkedDeal] = Field(default_factory=list)
    linked_proposals: List[BuyerLinkedProposal] = Field(default_factory=list)
    linked_communications: List[BuyerLinkedCommunication] = Field(default_factory=list)
    last_activity_at: Optional[datetime] = None


class BuyerRankingItem(BaseModel):
    rank: int
    buyer_id: UUID
    name: str
    company: Optional[str] = None
    buyer_score: int
    classification: BuyerClassification
    annual_potential: Decimal = Decimal("0")
    metric_label: str = ""


class BuyerTopBuyersResponse(BaseModel):
    top_buyers: List[BuyerRankingItem] = Field(default_factory=list)
    fastest_growing: List[BuyerRankingItem] = Field(default_factory=list)
    highest_revenue: List[BuyerRankingItem] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class BuyerRiskItem(BaseModel):
    buyer_id: UUID
    name: str
    company: Optional[str] = None
    risk_level: RiskLevel
    classification: BuyerClassification
    buyer_score: int
    title: str
    description: str = ""
    risk_signals: List[str] = Field(default_factory=list)


class BuyerRisksResponse(BaseModel):
    items: List[BuyerRiskItem] = Field(default_factory=list)
    total: int = 0
    by_level: dict[str, int] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class BuyerRecalculateRequest(BaseModel):
    client_id: Optional[UUID] = None
    limit: int = Field(200, ge=1, le=500)


class BuyerRecalculateResponse(BaseModel):
    evaluated: int = 0
    overview: BuyerIntelligenceOverview
    message: str = ""
    errors: List[str] = Field(default_factory=list)


class BuyerIntelligenceSummaryWidget(BaseModel):
    hot_buyers: int = 0
    strategic_buyers: int = 0
    high_potential_buyers: int = 0
    at_risk_buyers: int = 0
    average_buyer_score: int = 0
    top_buyer_name: Optional[str] = None
    top_buyer_score: int = 0
    errors: List[str] = Field(default_factory=list)
