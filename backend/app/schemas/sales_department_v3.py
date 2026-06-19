"""AI Sales Department v3 — unified sales operating system schemas (read-only)."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SalesDeptV3PriorityLead(BaseModel):
    lead_id: UUID
    name: str
    company: Optional[str] = None
    priority_score: float = 0.0
    urgency: str = "medium"
    revenue_potential: float = 0.0
    lead_score: int = 0
    qualification_level: Optional[str] = None
    recommended_action: Optional[str] = None
    sources: list[str] = Field(default_factory=list)


class SalesDeptV3PriorityConversation(BaseModel):
    conversation_id: str
    channel: str = "unknown"
    source: str = "unknown"
    contact_name: Optional[str] = None
    response_urgency: str = "medium"
    follow_up_priority: str = "medium"
    communication_health: float = 50.0
    classification: Optional[str] = None
    recommended_action: Optional[str] = None


class SalesDeptV3OpportunityItem(BaseModel):
    opportunity_id: str
    title: str
    source: str = "crm"
    opportunity_health: float = 50.0
    deal_risk: str = "medium"
    closing_probability: float = 0.0
    expected_value: Optional[Decimal] = None
    lead_id: Optional[UUID] = None
    deal_room_id: Optional[UUID] = None
    priority: str = "medium"


class SalesDeptV3RiskItem(BaseModel):
    risk_id: str
    title: str
    issue: str
    severity: str = "medium"
    source: str = "sales_manager"
    category: Optional[str] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    conversation_id: Optional[str] = None


class SalesDeptV3RecommendedAction(BaseModel):
    action_id: str
    title: str
    description: str = ""
    priority: str = "medium"
    source: str = "operator_tasks"
    category: str = "task"
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    conversation_id: Optional[str] = None
    due_at: Optional[datetime] = None
    is_overdue: bool = False
    requires_escalation: bool = False


class SalesDeptV3RevenueForecast(BaseModel):
    pipeline_value: Decimal = Decimal("0")
    weighted_pipeline: Decimal = Decimal("0")
    closed_revenue: Decimal = Decimal("0")
    forecast_30d: Decimal = Decimal("0")
    forecast_90d: Decimal = Decimal("0")
    currency: str = "UZS"
    confidence: str = "medium"


class SalesDeptV3ExecutiveSummary(BaseModel):
    summary: str
    business_health_score: int = 50
    hot_leads: int = 0
    priority_leads: int = 0
    active_opportunities: int = 0
    open_risks: int = 0
    overdue_actions: int = 0
    communication_health: float = 50.0


class SalesDeptV3OverviewResponse(BaseModel):
    executive_summary: SalesDeptV3ExecutiveSummary
    top_opportunities: list[SalesDeptV3OpportunityItem] = Field(default_factory=list)
    top_risks: list[SalesDeptV3RiskItem] = Field(default_factory=list)
    priority_leads: list[SalesDeptV3PriorityLead] = Field(default_factory=list)
    priority_conversations: list[SalesDeptV3PriorityConversation] = Field(default_factory=list)
    recommended_actions: list[SalesDeptV3RecommendedAction] = Field(default_factory=list)
    revenue_forecast: SalesDeptV3RevenueForecast
    weekly_priorities: list[str] = Field(default_factory=list)
    coordination: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


class SalesDeptV3PrioritiesResponse(BaseModel):
    priority_leads: list[SalesDeptV3PriorityLead] = Field(default_factory=list)
    priority_conversations: list[SalesDeptV3PriorityConversation] = Field(default_factory=list)
    total: int = 0
    errors: list[str] = Field(default_factory=list)


class SalesDeptV3OpportunitiesResponse(BaseModel):
    items: list[SalesDeptV3OpportunityItem] = Field(default_factory=list)
    total: int = 0
    errors: list[str] = Field(default_factory=list)


class SalesDeptV3RisksResponse(BaseModel):
    items: list[SalesDeptV3RiskItem] = Field(default_factory=list)
    total: int = 0
    errors: list[str] = Field(default_factory=list)


class SalesDeptV3RecommendationsResponse(BaseModel):
    recommended_actions: list[SalesDeptV3RecommendedAction] = Field(default_factory=list)
    overdue_actions: list[SalesDeptV3RecommendedAction] = Field(default_factory=list)
    escalation_list: list[SalesDeptV3RecommendedAction] = Field(default_factory=list)
    total: int = 0
    errors: list[str] = Field(default_factory=list)


class SalesDeptV3BriefingRequest(BaseModel):
    client_id: Optional[UUID] = None


class SalesDeptV3BriefingResponse(BaseModel):
    executive_summary: str
    top_opportunities: list[str] = Field(default_factory=list)
    top_risks: list[str] = Field(default_factory=list)
    weekly_priorities: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    revenue_forecast_note: str = ""
    source: str = "heuristic"
    generated_at: datetime
    errors: list[str] = Field(default_factory=list)


class SalesDeptV3SummaryWidget(BaseModel):
    business_health_score: int = 50
    priority_leads: int = 0
    hot_leads: int = 0
    active_opportunities: int = 0
    open_risks: int = 0
    overdue_actions: int = 0
    pipeline_value: Decimal = Decimal("0")
    closed_revenue: Decimal = Decimal("0")
    communication_health: float = 50.0
    top_opportunities: list[dict[str, Any]] = Field(default_factory=list)
    top_risks: list[dict[str, Any]] = Field(default_factory=list)
    top_actions: list[dict[str, Any]] = Field(default_factory=list)
    weekly_priorities: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
