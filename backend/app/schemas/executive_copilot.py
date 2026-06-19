"""AI Executive Copilot v1 — business-wide executive analytics (read-only, heuristic)."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ExecutiveCopilotRevenueSummary(BaseModel):
    closed_revenue: float = 0.0
    pipeline_value: float = 0.0
    deals_won: int = 0
    pending_commission: float = 0.0
    currency: str = "UZS"


class ExecutiveCopilotOverviewResponse(BaseModel):
    revenue: ExecutiveCopilotRevenueSummary = Field(default_factory=ExecutiveCopilotRevenueSummary)
    opportunities: int = 0
    hot_leads: int = 0
    overdue_tasks: int = 0
    active_conversations: int = 0
    proposals_pending: int = 0
    risk_count: int = 0
    business_health_score: int = 0
    leads_count: int = 0
    open_tasks: int = 0
    workflow_recommendations: int = 0
    revenue_attribution: dict = Field(default_factory=dict)
    wechat_sync: dict = Field(default_factory=dict)
    whatsapp_sync: dict = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)


class ExecutiveCopilotAlertItem(BaseModel):
    id: str
    type: str
    severity: Literal["critical", "high", "medium", "low"]
    title: str
    message: str
    source: str
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    conversation_id: Optional[str] = None


class ExecutiveCopilotAlertsResponse(BaseModel):
    items: List[ExecutiveCopilotAlertItem] = Field(default_factory=list)
    total: int = 0


class ExecutiveCopilotRecommendationItem(BaseModel):
    category: Literal[
        "hot_lead_follow_up",
        "proposal_follow_up",
        "inactive_lead_recovery",
        "overdue_task_escalation",
        "conversation_response_reminder",
    ]
    title: str
    description: str
    priority: Literal["urgent", "high", "medium", "low"]
    lead_id: Optional[UUID] = None
    conversation_id: Optional[str] = None
    entity_id: Optional[str] = None
    source: str = "executive_copilot"


class ExecutiveCopilotRecommendationsResponse(BaseModel):
    items: List[ExecutiveCopilotRecommendationItem] = Field(default_factory=list)
    total: int = 0


class ExecutiveCopilotBriefingRequest(BaseModel):
    client_id: Optional[UUID] = None


class ExecutiveCopilotBriefingResponse(BaseModel):
    summary: str
    business_health_score: int = 0
    opportunities: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    communication_intelligence: dict = Field(default_factory=dict)
    source: str = "heuristic"
    generated_at: datetime
    errors: List[str] = Field(default_factory=list)


class ExecutiveCopilotSummaryWidget(BaseModel):
    business_health_score: int = 0
    hot_leads: int = 0
    opportunities: int = 0
    risk_count: int = 0
    overdue_tasks: int = 0
    active_conversations: int = 0
    proposals_pending: int = 0
    closed_revenue: float = 0.0
    revenue_attribution: dict = Field(default_factory=dict)
    top_alerts: List[ExecutiveCopilotAlertItem] = Field(default_factory=list)
    top_recommendations: List[ExecutiveCopilotRecommendationItem] = Field(default_factory=list)
    factory_partner_pending: int = 0
