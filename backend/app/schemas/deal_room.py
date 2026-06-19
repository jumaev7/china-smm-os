"""AI Deal Room v1 — schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.revenue_attribution import RevenueAttributionLeadSummary


DealRoomStage = Literal[
    "new", "qualification", "proposal", "negotiation", "contract", "closing", "won", "lost",
]
DealRoomStatus = Literal["active", "on_hold", "closed"]


class DealRoomItem(BaseModel):
    id: UUID
    crm_client_id: UUID
    client_name: Optional[str] = None
    deal_name: str
    stage: str
    status: str
    probability: int = 0
    expected_value: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime


class DealRoomListResponse(BaseModel):
    items: List[DealRoomItem] = Field(default_factory=list)
    total: int = 0


class DealRoomCreateRequest(BaseModel):
    crm_client_id: UUID
    deal_name: str = Field(..., min_length=1, max_length=255)
    stage: DealRoomStage = "new"
    status: DealRoomStatus = "active"
    expected_value: Optional[Decimal] = None
    crm_lead_id: Optional[UUID] = None


class DealRoomUpdateStageRequest(BaseModel):
    deal_room_id: UUID
    stage: DealRoomStage
    probability: Optional[int] = Field(None, ge=0, le=100)


class DealRoomFindOrCreateRequest(BaseModel):
    crm_lead_id: UUID
    crm_client_id: Optional[UUID] = None
    deal_name: Optional[str] = None


class DealRoomClientSummary(BaseModel):
    id: UUID
    company_name: str
    contact_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    lead_intelligence: Optional[dict[str, Any]] = None


class DealRoomConversationItem(BaseModel):
    id: str
    channel: str
    title: str
    status: str
    last_message_at: Optional[datetime] = None
    lead_id: Optional[UUID] = None
    unread_count: int = 0


class DealRoomProposalItem(BaseModel):
    id: UUID
    title: str
    status: str
    language: Optional[str] = None
    sent_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class DealRoomTaskItem(BaseModel):
    id: UUID
    title: str
    status: str
    priority: str
    due_at: Optional[datetime] = None
    action_type: Optional[str] = None


class DealRoomRecommendationItem(BaseModel):
    id: str
    source: Literal["sales_assistant", "executive_copilot"]
    title: str
    description: str
    priority: str
    recommended_action: Optional[str] = None


class DealRoomRiskItem(BaseModel):
    type: str
    severity: Literal["critical", "high", "medium", "low"]
    issue: str
    recommendation: str


class DealRoomProbability(BaseModel):
    score: int = 0
    factors: List[str] = Field(default_factory=list)
    stored_probability: int = 0


class DealRoomDetailResponse(BaseModel):
    id: UUID
    crm_client_id: UUID
    deal_name: str
    stage: str
    status: str
    expected_value: Optional[Decimal] = None
    created_at: datetime
    updated_at: datetime
    client: Optional[DealRoomClientSummary] = None
    conversations: List[DealRoomConversationItem] = Field(default_factory=list)
    proposals: List[DealRoomProposalItem] = Field(default_factory=list)
    tasks: List[DealRoomTaskItem] = Field(default_factory=list)
    recommendations: List[DealRoomRecommendationItem] = Field(default_factory=list)
    risks: List[DealRoomRiskItem] = Field(default_factory=list)
    probability: DealRoomProbability = Field(default_factory=DealRoomProbability)
    communication_analysis: List[dict[str, Any]] = Field(default_factory=list)
    revenue_attribution: Optional[RevenueAttributionLeadSummary] = None
    buyer_intelligence: Optional[dict[str, Any]] = None
    deal_risk: Optional[dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)


# --- Deal Room v2 ---

DealRoomV2PipelineStage = Literal[
    "inquiry", "qualification", "quotation", "negotiation", "sample",
    "contract", "payment", "closed_won", "closed_lost",
]


class DealRoomV2Overview(BaseModel):
    total_deal_rooms: int = 0
    active_deal_rooms: int = 0
    readiness_score: int = 0
    average_health_score: int = 0
    total_pipeline_value: float = 0.0
    weighted_pipeline_value: float = 0.0
    high_risk_deals: int = 0
    integrations: dict[str, Any] = Field(default_factory=dict)
    safety_notice: str = ""


class DealRoomV2DealOverview(BaseModel):
    deal_health_score: int = 0
    deal_value: float = 0.0
    expected_revenue: float = 0.0
    close_probability: int = 0
    estimated_close_date: Optional[datetime] = None
    deal_owner: Optional[str] = None
    currency: str = "UZS"
    current_stage: str = "inquiry"
    current_stage_label: str = "Inquiry"


class DealRoomV2PipelineStageItem(BaseModel):
    stage: str
    label: str
    status: Literal["completed", "current", "upcoming", "skipped"]
    probability: int = 0


class DealRoomV2Pipeline(BaseModel):
    current_stage: str
    current_stage_label: str
    stages: List[DealRoomV2PipelineStageItem] = Field(default_factory=list)


class DealRoomV2BuyerInformation(BaseModel):
    linked_buyer_profile_id: Optional[str] = None
    company_name: Optional[str] = None
    contact_name: Optional[str] = None
    country: Optional[str] = None
    industry: Optional[str] = None
    relationship_strength: str = "unknown"
    acquisition_source: str = "manual"
    lead_id: Optional[UUID] = None
    crm_deal_id: Optional[UUID] = None
    match_score: Optional[int] = None
    email: Optional[str] = None
    phone: Optional[str] = None


class DealRoomV2RevenueIntegration(BaseModel):
    expected_revenue: float = 0.0
    weighted_revenue: float = 0.0
    revenue_forecast_impact: str = "neutral"
    pipeline_contribution: float = 0.0
    deal_value: float = 0.0
    close_probability: int = 0
    currency: str = "UZS"


class DealRoomV2RiskAssessment(BaseModel):
    commercial_risk: int = 0
    commercial_risk_level: str = "low"
    payment_risk: int = 0
    payment_risk_level: str = "low"
    logistics_risk: int = 0
    logistics_risk_level: str = "low"
    compliance_risk: int = 0
    compliance_risk_level: str = "low"
    overall_risk_score: int = 0
    overall_risk_level: str = "low"
    deal_health_score: int = 0
    deal_risk_classification: str = "watchlist"
    risk_factors: List[str] = Field(default_factory=list)


class DealRoomV2DocumentItem(BaseModel):
    id: str
    category: str
    title: str
    status: str
    document_type: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    certificate_number: Optional[str] = None
    updated_at: Optional[datetime] = None
    sent_at: Optional[datetime] = None


class DealRoomV2Documents(BaseModel):
    items: List[DealRoomV2DocumentItem] = Field(default_factory=list)
    quotation_count: int = 0
    contract_count: int = 0
    certificate_count: int = 0
    shipping_count: int = 0
    payment_count: int = 0


class DealRoomV2TimelineItem(BaseModel):
    id: str
    event_type: str
    category: str
    title: str
    description: str = ""
    occurred_at: Optional[datetime] = None


class DealRoomV2Timeline(BaseModel):
    items: List[DealRoomV2TimelineItem] = Field(default_factory=list)


class DealRoomV2GuidedAction(BaseModel):
    action_id: str
    title: str
    description: str
    route: str


class DealRoomV2WorkspaceResponse(BaseModel):
    id: UUID
    deal_name: str
    crm_client_id: UUID
    client_name: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
    deal_overview: Optional[DealRoomV2DealOverview] = None
    pipeline: Optional[DealRoomV2Pipeline] = None
    buyer_information: Optional[DealRoomV2BuyerInformation] = None
    revenue_integration: Optional[DealRoomV2RevenueIntegration] = None
    risk_assessment: Optional[DealRoomV2RiskAssessment] = None
    documents: Optional[DealRoomV2Documents] = None
    activity_timeline: Optional[DealRoomV2Timeline] = None
    integrations: dict[str, Any] = Field(default_factory=dict)
    guided_actions: List[DealRoomV2GuidedAction] = Field(default_factory=list)
    safety_notice: str = ""
    errors: List[str] = Field(default_factory=list)


class DealRoomV2ListItem(DealRoomItem):
    v2_stage: str = "inquiry"
    v2_stage_label: str = "Inquiry"
    deal_value: float = 0.0
    close_probability: int = 0


class DealRoomV2ListResponse(BaseModel):
    items: List[DealRoomV2ListItem] = Field(default_factory=list)
    total: int = 0


class DealRoomV2SummaryWidget(BaseModel):
    readiness_score: int = 0
    total_deal_rooms: int = 0
    active_deal_rooms: int = 0
    total_pipeline_value: float = 0.0
    weighted_pipeline_value: float = 0.0
    average_health_score: int = 0
    high_risk_deals: int = 0
    top_deal: Optional[dict[str, Any]] = None
    currency: str = "UZS"
    safety_notice: str = ""


class DealRoomV2RefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int = 0
    active_deal_rooms: int = 0
    total_pipeline_value: float = 0.0
    safety_notice: str = ""
