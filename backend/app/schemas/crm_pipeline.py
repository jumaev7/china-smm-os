"""Executive CRM pipeline — 12-stage commercial lifecycle schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

PipelineStage = Literal[
    "lead",
    "qualified",
    "contacted",
    "meeting_scheduled",
    "proposal_sent",
    "negotiation",
    "contract_pending",
    "client_active",
    "publishing_active",
    "expansion_upsell",
    "closed_won",
    "closed_lost",
]

StageSource = Literal["manual", "auto", "proposal"]

PipelineEventType = Literal[
    "deal_created",
    "lead_created",
    "status_changed",
    "stage_changed",
    "proposal_sent",
    "proposal_accepted",
    "proposal_rejected",
    "meeting_added",
    "publishing_connected",
    "campaign_launched",
    "client_message",
    "manual_note",
    "ai_recommendation",
    "owner_changed",
    "client_linked",
]

PIPELINE_STAGES: list[PipelineStage] = [
    "lead",
    "qualified",
    "contacted",
    "meeting_scheduled",
    "proposal_sent",
    "negotiation",
    "contract_pending",
    "client_active",
    "publishing_active",
    "expansion_upsell",
    "closed_won",
    "closed_lost",
]

PIPELINE_STAGE_LABELS: dict[str, str] = {
    "lead": "Lead",
    "qualified": "Qualified",
    "contacted": "Contacted",
    "meeting_scheduled": "Meeting Scheduled",
    "proposal_sent": "Proposal Sent",
    "negotiation": "Negotiation",
    "contract_pending": "Contract Pending",
    "client_active": "Client Active",
    "publishing_active": "Publishing Active",
    "expansion_upsell": "Expansion / Upsell",
    "closed_won": "Closed Won",
    "closed_lost": "Closed Lost",
}

DEFAULT_STAGE_PROBABILITY: dict[str, int] = {
    "lead": 5,
    "qualified": 15,
    "contacted": 20,
    "meeting_scheduled": 30,
    "proposal_sent": 40,
    "negotiation": 55,
    "contract_pending": 70,
    "client_active": 85,
    "publishing_active": 90,
    "expansion_upsell": 75,
    "closed_won": 100,
    "closed_lost": 0,
}

TERMINAL_STAGES = frozenset({"closed_won", "closed_lost"})

# Ordered funnel — each stage may advance to the next or skip forward on business events.
# Terminal stages have no forward transitions.
ALLOWED_STAGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "lead": frozenset({
        "qualified", "contacted", "meeting_scheduled", "proposal_sent",
        "negotiation", "closed_lost",
    }),
    "qualified": frozenset({
        "contacted", "meeting_scheduled", "proposal_sent", "negotiation", "closed_lost",
    }),
    "contacted": frozenset({
        "meeting_scheduled", "proposal_sent", "negotiation", "contract_pending", "closed_lost",
    }),
    "meeting_scheduled": frozenset({
        "proposal_sent", "negotiation", "contract_pending", "closed_lost",
    }),
    "proposal_sent": frozenset({
        "negotiation", "contract_pending", "client_active", "closed_won", "closed_lost",
    }),
    "negotiation": frozenset({
        "contract_pending", "client_active", "closed_won", "closed_lost",
    }),
    "contract_pending": frozenset({
        "client_active", "closed_won", "closed_lost",
    }),
    "client_active": frozenset({
        "publishing_active", "expansion_upsell", "closed_won", "closed_lost",
    }),
    "publishing_active": frozenset({
        "expansion_upsell", "closed_won", "closed_lost",
    }),
    "expansion_upsell": frozenset({
        "closed_won", "closed_lost", "publishing_active",
    }),
    "closed_won": frozenset(),
    "closed_lost": frozenset({"lead", "qualified", "contacted"}),
}

LEGACY_STAGE_MAP: dict[str, str] = {
    "new_lead": "lead",
    "contacted": "contacted",
    "negotiation": "negotiation",
    "proposal_sent": "proposal_sent",
    "won": "closed_won",
    "lost": "closed_lost",
}


class CrmPipelineEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    event_type: str
    title: str
    description: str | None
    payload: dict | None
    customer_id: UUID | None
    lead_id: UUID | None
    deal_id: UUID | None
    actor: str | None
    created_at: datetime


class CrmPipelineEventListResponse(BaseModel):
    items: list[CrmPipelineEventResponse]
    total: int


class PipelineStageInfo(BaseModel):
    stage: PipelineStage
    label: str
    default_probability: int
    is_terminal: bool


class PipelineStagesResponse(BaseModel):
    stages: list[PipelineStageInfo]


class PipelineStageUpdate(BaseModel):
    stage: PipelineStage
    probability: int | None = Field(None, ge=0, le=100)
    expected_close_date: datetime | None = None
    notes: str | None = None
    stage_override: bool = True


class PipelineNoteCreate(BaseModel):
    title: str | None = Field(None, max_length=255)
    description: str = Field(..., min_length=1)


class PipelineMeetingCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    scheduled_at: datetime | None = None
    advance_stage: bool = True


class PipelineDealListResponse(BaseModel):
    items: list[dict]
    total: int


class CrmPipelinePublishingHealthSummary(BaseModel):
    total_accounts: int = 0
    meta_connected_count: int = 0
    healthy_count: int = 0
    warning_count: int = 0
    disconnected_count: int = 0
    mock_count: int = 0
    by_platform: dict[str, int] = Field(default_factory=dict)
    by_health: dict[str, int] = Field(default_factory=dict)


class CrmPipelineDashboardKpis(BaseModel):
    pipeline_value: Decimal = Decimal("0")
    weighted_expected_revenue: Decimal = Decimal("0")
    win_rate: float | None = None
    average_deal_time_days: float | None = None
    open_deals_count: int = 0
    stale_deals_count: int = 0
    clients_active_count: int = 0
    clients_publishing_count: int = 0
    clients_connected_to_meta: int = 0
    deals_won_count: int = 0
    deals_lost_count: int = 0
    publishing_health: CrmPipelinePublishingHealthSummary = Field(
        default_factory=CrmPipelinePublishingHealthSummary,
    )
    generated_at: datetime


class CrmPipelineForecastRow(BaseModel):
    month: str
    stage: str
    deal_count: int = 0
    pipeline_value: Decimal = Decimal("0")
    weighted_revenue: Decimal = Decimal("0")


class CrmPipelineRevenueForecastResponse(BaseModel):
    rows: list[CrmPipelineForecastRow] = Field(default_factory=list)
    total_weighted_revenue: Decimal = Decimal("0")
    generated_at: datetime


class CrmPipelineManagerPerformanceRow(BaseModel):
    owner_id: UUID | None = None
    owner_email: str | None = None
    open_deals: int = 0
    pipeline_value: Decimal = Decimal("0")
    weighted_expected_revenue: Decimal = Decimal("0")
    deals_won: int = 0
    deals_lost: int = 0
    win_rate: float | None = None
    stale_deals: int = 0


class CrmPipelineManagerPerformanceResponse(BaseModel):
    managers: list[CrmPipelineManagerPerformanceRow] = Field(default_factory=list)
    unassigned: CrmPipelineManagerPerformanceRow | None = None
    generated_at: datetime


# ─── Executive AI Sales Assistant (rule engine v1) ─────────────────────────────

RecommendationCategory = Literal[
    "follow_up_required",
    "likely_to_close",
    "deal_at_risk",
    "proposal_expiring",
    "proposal_waiting_too_long",
    "publishing_opportunity",
    "meta_connection_opportunity",
    "upsell_opportunity",
    "inactive_customer",
    "high_value_lead",
    "stale_deal",
    "manager_overload",
]

RecommendationSeverity = Literal["critical", "high", "medium", "low"]

RECOMMENDATION_CATEGORIES: list[RecommendationCategory] = [
    "follow_up_required",
    "likely_to_close",
    "deal_at_risk",
    "proposal_expiring",
    "proposal_waiting_too_long",
    "publishing_opportunity",
    "meta_connection_opportunity",
    "upsell_opportunity",
    "inactive_customer",
    "high_value_lead",
    "stale_deal",
    "manager_overload",
]

RECOMMENDATION_CATEGORY_LABELS: dict[str, str] = {
    "follow_up_required": "Follow-up Required",
    "likely_to_close": "Likely To Close",
    "deal_at_risk": "Deal At Risk",
    "proposal_expiring": "Proposal Expiring",
    "proposal_waiting_too_long": "Proposal Waiting Too Long",
    "publishing_opportunity": "Publishing Opportunity",
    "meta_connection_opportunity": "Meta Connection Opportunity",
    "upsell_opportunity": "Upsell Opportunity",
    "inactive_customer": "Inactive Customer",
    "high_value_lead": "High Value Lead",
    "stale_deal": "Stale Deal",
    "manager_overload": "Manager Overload",
}


class CrmPipelineIntelligenceRecommendation(BaseModel):
    rule_id: str
    category: RecommendationCategory
    category_label: str
    severity: RecommendationSeverity
    confidence: int = Field(ge=0, le=100)
    business_reason: str
    recommended_action: str
    deal_id: UUID | None = None
    deal_title: str | None = None
    customer_id: UUID | None = None
    customer_name: str | None = None
    lead_id: UUID | None = None
    lead_name: str | None = None
    proposal_id: UUID | None = None
    proposal_title: str | None = None
    owner_id: UUID | None = None
    owner_email: str | None = None
    priority_score: int = 0
    generated_at: datetime


class CrmPipelineIntelligenceResponse(BaseModel):
    recommendations: list[CrmPipelineIntelligenceRecommendation] = Field(default_factory=list)
    total: int = 0
    generated_at: datetime


class CrmPipelineManagerInsightRow(BaseModel):
    owner_id: UUID | None = None
    owner_email: str | None = None
    open_deals: int = 0
    pipeline_value: Decimal = Decimal("0")
    weighted_expected_revenue: Decimal = Decimal("0")
    stale_deals: int = 0
    likely_wins: int = 0
    workload_score: int = Field(ge=0, le=100)
    avg_response_time_days: float | None = None
    deals_won: int = 0
    deals_lost: int = 0
    win_rate: float | None = None


class CrmPipelineManagerInsightsResponse(BaseModel):
    managers: list[CrmPipelineManagerInsightRow] = Field(default_factory=list)
    unassigned: CrmPipelineManagerInsightRow | None = None
    generated_at: datetime


class CrmPipelineMorningBrief(BaseModel):
    todays_priorities: list[CrmPipelineIntelligenceRecommendation] = Field(default_factory=list)
    top_risks: list[CrmPipelineIntelligenceRecommendation] = Field(default_factory=list)
    top_opportunities: list[CrmPipelineIntelligenceRecommendation] = Field(default_factory=list)
    revenue_forecast: CrmPipelineRevenueForecastResponse
    pipeline_health: CrmPipelineDashboardKpis
    manager_workload: CrmPipelineManagerInsightsResponse
    publishing_health: CrmPipelinePublishingHealthSummary
    meta_health: CrmPipelinePublishingHealthSummary
    all_recommendations: list[CrmPipelineIntelligenceRecommendation] = Field(default_factory=list)
    generated_at: datetime
