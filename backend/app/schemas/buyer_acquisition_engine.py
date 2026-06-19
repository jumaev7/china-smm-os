"""Buyer Acquisition Engine v1 — lead generation and matching schemas (read-only)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

LeadPipelineStatus = Literal[
    "new",
    "contacted",
    "replied",
    "negotiating",
    "quotation_sent",
    "sample_sent",
    "won",
    "lost",
]

BuyerDatabaseStatus = Literal[
    "prospect",
    "active",
    "engaged",
    "customer",
    "inactive",
    "unknown",
]

OpportunityType = Literal["buyer", "country", "industry"]

GuidedActionKey = Literal[
    "open_factory_platform",
    "open_customer_portal",
    "open_crm",
    "open_real_factory_pilot",
]


class BuyerEngineBuyerRecord(BaseModel):
    buyer_id: str
    company_name: str
    country: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    whatsapp: Optional[str] = None
    wechat: Optional[str] = None
    status: BuyerDatabaseStatus = "unknown"
    pipeline_status: LeadPipelineStatus = "new"
    match_score: int = Field(default=0, ge=0, le=100)
    sources: List[str] = Field(default_factory=list)
    crm_lead_id: Optional[UUID] = None
    discovery_id: Optional[UUID] = None
    network_id: Optional[UUID] = None
    client_id: Optional[UUID] = None


class BuyerEngineBuyersResponse(BaseModel):
    items: List[BuyerEngineBuyerRecord]
    total: int
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class BuyerEngineMatchItem(BaseModel):
    buyer_id: str
    company_name: str
    country: Optional[str] = None
    industry: Optional[str] = None
    match_score: int = Field(default=0, ge=0, le=100)
    match_factors: dict[str, Any] = Field(default_factory=dict)
    pipeline_status: LeadPipelineStatus = "new"
    recommended_action: Optional[str] = None


class BuyerEngineMatchesResponse(BaseModel):
    items: List[BuyerEngineMatchItem]
    total: int
    average_match_score: int = 0
    factory_industries: List[str] = Field(default_factory=list)
    factory_products: List[str] = Field(default_factory=list)
    export_markets: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class PipelineStageCount(BaseModel):
    status: LeadPipelineStatus
    label: str
    count: int


class BuyerEnginePipelineResponse(BaseModel):
    stages: List[PipelineStageCount]
    total: int
    active_count: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class BuyerEngineOpportunityItem(BaseModel):
    opportunity_id: str
    opportunity_type: OpportunityType
    title: str
    subtitle: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    buyer_company: Optional[str] = None
    score: int = Field(default=0, ge=0, le=100)
    lead_count: int = 0
    estimated_value: Optional[float] = None
    recommended_action: Optional[str] = None


class BuyerEngineOpportunitiesResponse(BaseModel):
    buyer_opportunities: List[BuyerEngineOpportunityItem] = Field(default_factory=list)
    country_opportunities: List[BuyerEngineOpportunityItem] = Field(default_factory=list)
    industry_opportunities: List[BuyerEngineOpportunityItem] = Field(default_factory=list)
    total: int = 0
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class BuyerEngineCrmSummary(BaseModel):
    total_leads: int = 0
    active_leads: int = 0
    won_deals: int = 0
    lost_deals: int = 0
    pipeline_value: float = 0.0
    average_match_score: int = 0
    safety_notice: str


class BuyerEngineFactoryView(BaseModel):
    top_buyers: List[BuyerEngineMatchItem] = Field(default_factory=list)
    best_matches: List[BuyerEngineMatchItem] = Field(default_factory=list)
    active_opportunities: int = 0
    lead_counts: dict[str, int] = Field(default_factory=dict)


class BuyerEngineGuidedAction(BaseModel):
    key: GuidedActionKey
    title: str
    description: str
    route: str
    enabled: bool = True


class BuyerEngineGuidedActionsResponse(BaseModel):
    items: List[BuyerEngineGuidedAction]
    safety_notice: str


class BuyerEngineOverview(BaseModel):
    total_buyers: int = 0
    database_buyers: int = 0
    matched_buyers: int = 0
    high_match_buyers: int = 0
    active_pipeline_leads: int = 0
    total_opportunities: int = 0
    average_match_score: int = 0
    readiness_score: int = Field(default=0, ge=0, le=100)
    factory_view: BuyerEngineFactoryView
    crm_summary: BuyerEngineCrmSummary
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    guided_actions: List[BuyerEngineGuidedAction] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    safety_notice: str


class BuyerEngineRefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int = Field(ge=0, le=100)
    total_buyers: int = 0
    matched_buyers: int = 0
    active_pipeline_leads: int = 0
    safety_notice: str
