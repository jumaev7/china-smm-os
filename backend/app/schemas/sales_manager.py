"""AI Sales Manager v2 — executive sales analytics schemas (read-only)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SalesManagerInboxActivity(BaseModel):
    open_conversations: int = 0
    unanswered: int = 0
    active_24h: int = 0
    wechat_threads: int = 0
    whatsapp_threads: int = 0


class SalesManagerOperatorWorkload(BaseModel):
    open_tasks: int = 0
    overdue_tasks: int = 0
    urgent_tasks: int = 0
    unassigned_tasks: int = 0
    overloaded_assignees: int = 0


class SalesManagerOverviewResponse(BaseModel):
    leads_count: int = 0
    hot_leads: int = 0
    qualified_leads: int = 0
    neglected_leads: int = 0
    overdue_tasks: int = 0
    active_proposals: int = 0
    proposal_conversion_rate: float = 0.0
    inbox_activity: SalesManagerInboxActivity = Field(default_factory=SalesManagerInboxActivity)
    operator_workload: SalesManagerOperatorWorkload = Field(default_factory=SalesManagerOperatorWorkload)
    opportunities_count: int = 0
    risks_count: int = 0
    conversations_count: int = 0
    errors: List[str] = Field(default_factory=list)


class SalesManagerOpportunityItem(BaseModel):
    type: str
    source: str
    priority: Literal["urgent", "high", "medium", "low"]
    action: str
    title: str
    summary: Optional[str] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    conversation_id: Optional[str] = None
    entity_id: Optional[str] = None


class SalesManagerOpportunitiesResponse(BaseModel):
    items: List[SalesManagerOpportunityItem] = Field(default_factory=list)
    total: int = 0


class SalesManagerRiskItem(BaseModel):
    issue: str
    severity: Literal["critical", "high", "medium", "low"]
    recommendation: str
    type: str
    source: Optional[str] = None
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    conversation_id: Optional[str] = None


class SalesManagerRisksResponse(BaseModel):
    items: List[SalesManagerRiskItem] = Field(default_factory=list)
    total: int = 0


class SalesManagerRecommendationItem(BaseModel):
    category: Literal[
        "priority_action",
        "follow_up",
        "proposal_reminder",
        "lead_assignment",
        "workload_balance",
    ]
    title: str
    description: str
    priority: Literal["urgent", "high", "medium", "low"]
    lead_id: Optional[UUID] = None
    conversation_id: Optional[str] = None


class SalesManagerRecommendationsResponse(BaseModel):
    items: List[SalesManagerRecommendationItem] = Field(default_factory=list)
    total: int = 0


class SalesManagerBriefingRequest(BaseModel):
    use_ai: bool = False
    client_id: Optional[UUID] = None


class SalesManagerBriefingResponse(BaseModel):
    summary: str
    opportunities: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)
    recommendations: List[str] = Field(default_factory=list)
    source: str = "heuristic"
    generated_at: datetime
    errors: List[str] = Field(default_factory=list)


class SalesManagerSummaryWidget(BaseModel):
    hot_leads: int = 0
    opportunities_count: int = 0
    risks_count: int = 0
    overdue_tasks: int = 0
    open_conversations: int = 0
    active_proposals: int = 0
    top_opportunities: List[dict[str, Any]] = Field(default_factory=list)
    top_risks: List[dict[str, Any]] = Field(default_factory=list)
