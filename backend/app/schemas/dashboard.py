"""Executive dashboard — unified business health overview and AI briefing."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID


class DashboardDealRisk(BaseModel):
    deal_id: UUID
    lead_id: UUID
    lead_name: Optional[str] = None
    deal_title: str
    risk_type: Literal[
        "stale_activity",
        "overdue_followup",
        "proposal_stalled",
        "invoice_unpaid",
    ]
    title: str
    severity: Literal["high", "medium"] = "medium"


class DashboardOperatorTaskItem(BaseModel):
    id: UUID
    title: str
    priority: str
    action_type: Optional[str] = None
    due_at: Optional[datetime] = None


class DashboardOverviewResponse(BaseModel):
    inbox_new: int
    tasks_open: int
    operator_tasks_today: int = 0
    operator_tasks_today_items: List[DashboardOperatorTaskItem] = Field(default_factory=list)
    content_ready: int
    content_scheduled: int
    clients_waiting_materials: int
    invoices_unpaid: int
    active_deals: int
    won_deals: int
    lost_deals: int
    pipeline_value: Decimal
    mrr: float
    overdue_followups: int
    near_limit_clients: int
    deal_risks: List[DashboardDealRisk] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class DashboardAiSummaryResponse(BaseModel):
    executive_summary: str
    top_priorities: List[str]
    risks: List[str]
    opportunities: List[str]
    recommended_actions: List[str]
    source: str = "fallback"
