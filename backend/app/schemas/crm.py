from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.revenue_attribution import RevenueAttributionLeadSummary

LeadSource = Literal["manual", "telegram", "website", "instagram", "referral", "landing_page", "other"]
LeadStatus = Literal[
    "new",
    "contacted",
    "qualified",
    "proposal_sent",
    "negotiation",
    "won",
    "lost",
]
LeadPriority = Literal["high", "medium", "low"]
QualificationLevel = Literal["cold", "warm", "hot", "qualified", "opportunity"]
ActivityType = Literal["note", "call", "message", "meeting", "proposal", "follow_up"]

PIPELINE_STATUSES: list[LeadStatus] = [
    "new",
    "contacted",
    "qualified",
    "proposal_sent",
    "negotiation",
    "won",
    "lost",
]


class CrmLeadCreate(BaseModel):
    client_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    telegram: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    source: LeadSource = "manual"
    language: Optional[str] = Field(None, max_length=20)
    interest: Optional[str] = None
    notes: Optional[str] = None
    status: LeadStatus = "new"
    priority: LeadPriority = "medium"
    estimated_value: Optional[Decimal] = None
    next_follow_up_at: Optional[datetime] = None
    attribution_source: Optional[str] = Field(None, max_length=50)
    attribution_campaign: Optional[str] = Field(None, max_length=255)
    attribution_notes: Optional[str] = None
    attributed_by: Optional[str] = Field(None, max_length=100)
    attribution_link_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    referral_code: Optional[str] = Field(None, max_length=50)


class CrmLeadUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    company: Optional[str] = Field(None, max_length=255)
    phone: Optional[str] = Field(None, max_length=50)
    telegram: Optional[str] = Field(None, max_length=100)
    email: Optional[str] = Field(None, max_length=255)
    source: Optional[LeadSource] = None
    language: Optional[str] = Field(None, max_length=20)
    interest: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[LeadStatus] = None
    priority: Optional[LeadPriority] = None
    estimated_value: Optional[Decimal] = None
    next_follow_up_at: Optional[datetime] = None
    attribution_source: Optional[str] = Field(None, max_length=50)
    attribution_campaign: Optional[str] = Field(None, max_length=255)
    attribution_notes: Optional[str] = None
    attributed_by: Optional[str] = Field(None, max_length=100)
    attribution_link_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    referral_code: Optional[str] = Field(None, max_length=50)


class CrmLeadResponse(BaseModel):
    id: UUID
    client_id: UUID
    company_name: Optional[str] = None
    name: str
    company: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    email: Optional[str] = None
    source: LeadSource
    language: Optional[str] = None
    interest: Optional[str] = None
    notes: Optional[str] = None
    status: LeadStatus
    priority: LeadPriority
    estimated_value: Optional[Decimal] = None
    next_follow_up_at: Optional[datetime] = None
    attribution_source: Optional[str] = None
    attribution_campaign: Optional[str] = None
    attribution_notes: Optional[str] = None
    attributed_by: Optional[str] = None
    attribution_link_id: Optional[UUID] = None
    partner_id: Optional[UUID] = None
    referral_code: Optional[str] = None
    partner_name: Optional[str] = None
    lead_score: Optional[int] = None
    qualification_level: Optional[QualificationLevel] = None
    ai_summary: Optional[str] = None
    recommended_action: Optional[str] = None
    last_scored_at: Optional[datetime] = None
    lead_insights: Optional["LeadInsights"] = None
    revenue_attribution: Optional[RevenueAttributionLeadSummary] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class LeadInsights(BaseModel):
    score: int = Field(..., ge=0, le=100)
    level: QualificationLevel
    strengths: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    next_action: str


class LeadScoreResponse(BaseModel):
    lead_id: UUID
    insights: LeadInsights
    ai_summary: Optional[str] = None
    recommended_action: Optional[str] = None
    demo_mode: bool = False
    lead: CrmLeadResponse


class LeadRescoreRequest(BaseModel):
    client_id: Optional[UUID] = None
    limit: int = Field(50, ge=1, le=500)


class LeadRescoreResponse(BaseModel):
    scored: int
    failed: int = 0
    message: str


class LeadIntelligenceHotLead(BaseModel):
    lead_id: UUID
    name: str
    company: Optional[str] = None
    lead_score: int
    qualification_level: QualificationLevel
    recommended_action: Optional[str] = None
    status: LeadStatus


class LeadIntelligenceMetrics(BaseModel):
    hot_leads: int = 0
    qualified_leads: int = 0
    neglected_leads: int = 0
    leads_without_activity: int = 0
    top_hot_leads: list[LeadIntelligenceHotLead] = Field(default_factory=list)


class CrmLeadListResponse(BaseModel):
    items: List[CrmLeadResponse]
    total: int


class CrmActivityCreate(BaseModel):
    type: ActivityType = "note"
    content: str = Field(..., min_length=1)


class CrmActivityResponse(BaseModel):
    id: UUID
    lead_id: UUID
    type: ActivityType
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CrmActivityListResponse(BaseModel):
    items: List[CrmActivityResponse]
    total: int


class CrmPipelineColumn(BaseModel):
    status: LeadStatus
    label: str
    leads: List[CrmLeadResponse]
    count: int


class CrmPipelineResponse(BaseModel):
    columns: List[CrmPipelineColumn]
    total: int
    counts: dict[str, int]
    errors: List[str] = Field(default_factory=list)


class CrmExtractLeadRequest(BaseModel):
    client_id: UUID
    text: str = Field(..., min_length=1, max_length=8000)


class CrmExtractLeadResponse(BaseModel):
    name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    telegram: Optional[str] = None
    email: Optional[str] = None
    interest: Optional[str] = None
    language: Optional[str] = None
    priority: LeadPriority = "medium"
    suggested_next_step: Optional[str] = None
    source: str = "fallback"


MessagePurpose = Literal[
    "first_contact",
    "follow_up",
    "proposal",
    "objection_reply",
    "meeting_reminder",
]


class CrmAiSuggestNextStepResponse(BaseModel):
    recommended_next_step: str
    suggested_message: str
    suggested_status_change: Optional[LeadStatus] = None
    follow_up_date: Optional[datetime] = None
    reasoning: str
    activity_id: UUID
    source: str = "fallback"


class CrmAiGenerateMessageRequest(BaseModel):
    purpose: MessagePurpose
    language: str = Field(default="ru", max_length=10)


class CrmAiGenerateMessageResponse(BaseModel):
    message_text: str
    tone: str
    cta: str
    purpose: MessagePurpose
    language: str
    source: str = "fallback"


class CrmAiSaveMessageRequest(BaseModel):
    message_text: str = Field(..., min_length=1)
    purpose: MessagePurpose = "follow_up"
    tone: Optional[str] = None


ProposalStatus = Literal["draft", "sent", "accepted", "rejected"]


class CrmProposalGenerateRequest(BaseModel):
    language: Optional[str] = Field(None, max_length=10)


class CrmProposalUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    proposal_text: Optional[str] = Field(None, min_length=1)
    status: Optional[ProposalStatus] = None
    estimated_value: Optional[Decimal] = None
    valid_until: Optional[datetime] = None
    language: Optional[str] = Field(None, max_length=10)


class CrmProposalResponse(BaseModel):
    id: UUID
    lead_id: UUID
    client_id: UUID
    lead_name: Optional[str] = None
    title: str
    language: str
    status: ProposalStatus
    proposal_text: str
    estimated_value: Optional[Decimal] = None
    valid_until: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CrmProposalListResponse(BaseModel):
    items: List[CrmProposalResponse]
    total: int


DocumentType = Literal["contract", "invoice", "offer"]
DocumentStatus = Literal["draft", "sent", "signed", "paid", "canceled"]


class CrmDocumentGenerateRequest(BaseModel):
    document_type: DocumentType
    language: Optional[str] = Field(None, max_length=10)


class CrmDocumentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    document_text: Optional[str] = Field(None, min_length=1)
    status: Optional[DocumentStatus] = None
    amount: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=10)
    due_date: Optional[datetime] = None
    language: Optional[str] = Field(None, max_length=10)


class CrmDocumentResponse(BaseModel):
    id: UUID
    proposal_id: UUID
    lead_id: UUID
    client_id: UUID
    lead_name: Optional[str] = None
    proposal_title: Optional[str] = None
    document_type: DocumentType
    title: str
    language: str
    status: DocumentStatus
    document_text: str
    amount: Optional[Decimal] = None
    currency: str
    due_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CrmDocumentListResponse(BaseModel):
    items: List[CrmDocumentResponse]
    total: int


DealStatus = Literal[
    "new",
    "proposal",
    "contract",
    "invoice",
    "waiting_payment",
    "won",
    "lost",
]

DealEventType = Literal[
    "activity",
    "proposal",
    "contract",
    "invoice",
    "note",
    "status_change",
]

RiskLevel = Literal["low", "medium", "high"]


class CrmDealCreate(BaseModel):
    lead_id: UUID
    client_id: UUID
    title: str = Field(..., min_length=1, max_length=255)
    status: DealStatus = "new"
    expected_value: Optional[Decimal] = None
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_close_date: Optional[datetime] = None


class CrmDealUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[DealStatus] = None
    expected_value: Optional[Decimal] = None
    probability: Optional[int] = Field(None, ge=0, le=100)
    expected_close_date: Optional[datetime] = None


class CrmDealResponse(BaseModel):
    id: UUID
    lead_id: UUID
    client_id: UUID
    lead_name: Optional[str] = None
    client_name: Optional[str] = None
    title: str
    status: DealStatus
    expected_value: Optional[Decimal] = None
    probability: int
    expected_close_date: Optional[datetime] = None
    deal_amount: Optional[Decimal] = None
    currency: str = "UZS"
    commission_percent: Optional[Decimal] = None
    commission_amount: Optional[Decimal] = None
    commission_status: Optional[str] = None
    partner_commission_percent: Optional[Decimal] = None
    partner_commission_amount: Optional[Decimal] = None
    days_in_pipeline: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CrmDealListResponse(BaseModel):
    items: List[CrmDealResponse]
    total: int


class CrmDealEventCreate(BaseModel):
    event_type: DealEventType = "note"
    title: str = Field(..., min_length=1, max_length=255)
    payload_json: Optional[dict] = None


class CrmDealEventResponse(BaseModel):
    id: UUID
    deal_id: UUID
    event_type: DealEventType
    title: str
    payload_json: dict = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class CrmDealDetailResponse(CrmDealResponse):
    lead: CrmLeadResponse
    proposals: List[CrmProposalResponse] = Field(default_factory=list)
    contracts: List[CrmDocumentResponse] = Field(default_factory=list)
    invoices: List[CrmDocumentResponse] = Field(default_factory=list)
    activities: List[CrmActivityResponse] = Field(default_factory=list)
    events: List[CrmDealEventResponse] = Field(default_factory=list)


class CrmDealHealthResponse(BaseModel):
    deal_score: int = Field(..., ge=0, le=100)
    risk_level: RiskLevel
    recommended_action: str
    reasoning: str
    source: str = "fallback"
