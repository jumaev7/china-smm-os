"""Sales Department Dashboard — executive AI sales department metrics."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SalesDeptOverviewKpis(BaseModel):
    total_leads: int = 0
    new_leads: int = 0
    qualified_leads: int = 0
    active_deals: int = 0
    won_deals: int = 0
    lost_deals: int = 0
    pipeline_value: Decimal = Decimal("0")
    closed_revenue: Decimal = Decimal("0")
    commission_earned: Decimal = Decimal("0")
    pending_commission: Decimal = Decimal("0")
    partner_count: int = 0
    buyer_recommendations_count: int = 0
    landing_page_leads: int = 0
    attribution_clicks: int = 0


class SalesDeptFunnel(BaseModel):
    leads: int = 0
    contacted: int = 0
    qualified: int = 0
    proposal_sent: int = 0
    negotiation: int = 0
    won: int = 0
    lost: int = 0


class SalesDeptTopProduct(BaseModel):
    product_id: UUID
    product_name: str
    leads_count: int = 0
    deals_count: int = 0
    revenue: Decimal = Decimal("0")
    buyer_recommendations_count: int = 0


class SalesDeptTopCountry(BaseModel):
    country: str
    leads_count: int = 0
    deals_count: int = 0
    revenue: Decimal = Decimal("0")
    opportunity_score: float = 0.0


class SalesDeptAttributionSource(BaseModel):
    source: str
    clicks: int = 0
    leads: int = 0
    deals: int = 0
    revenue: Decimal = Decimal("0")
    conversion_rate: float = 0.0


class SalesDeptPartnerPerformance(BaseModel):
    partner_id: UUID
    partner_name: str
    leads: int = 0
    deals: int = 0
    revenue: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")


class SalesDeptFollowupItem(BaseModel):
    lead_id: UUID
    name: str
    due_at: Optional[datetime] = None


class SalesDeptProposalItem(BaseModel):
    proposal_id: UUID
    lead_id: UUID
    title: str
    status: str


class SalesDeptInvoiceItem(BaseModel):
    document_id: UUID
    lead_id: UUID
    title: str


class SalesDeptSalesAgentItem(BaseModel):
    id: UUID
    title: str
    priority: str
    recommendation_type: str
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None


class SalesDeptSalesAssistantItem(BaseModel):
    id: UUID
    title: str
    priority: str
    recommendation_type: str
    lead_id: Optional[UUID] = None
    deal_id: Optional[UUID] = None
    conversation_id: Optional[str] = None


class SalesDeptSalesAssistantWidget(BaseModel):
    open_count: int = 0
    urgent_count: int = 0
    top_recommendations: list[SalesDeptSalesAssistantItem] = Field(default_factory=list)


class SalesDeptOperatorTasksWidget(BaseModel):
    open_count: int = 0
    urgent_count: int = 0
    overdue_count: int = 0
    top_tasks: list[dict] = Field(default_factory=list)


class SalesDeptRiskyDealItem(BaseModel):
    deal_id: UUID
    lead_id: UUID
    deal_title: str
    lead_name: Optional[str] = None
    risk_type: str
    title: str
    severity: str = "medium"


class SalesDeptActionQueue(BaseModel):
    overdue_followups: list[SalesDeptFollowupItem] = Field(default_factory=list)
    pending_proposals: list[SalesDeptProposalItem] = Field(default_factory=list)
    unpaid_invoices: list[SalesDeptInvoiceItem] = Field(default_factory=list)
    high_priority_sales_agent_recommendations: list[SalesDeptSalesAgentItem] = Field(default_factory=list)
    risky_deals: list[SalesDeptRiskyDealItem] = Field(default_factory=list)


class SalesDeptSalesManagerWidget(BaseModel):
    leads_count: int = 0
    hot_leads: int = 0
    opportunities_count: int = 0
    risks_count: int = 0
    overdue_tasks: int = 0
    active_proposals: int = 0
    top_recommendations: list[dict] = Field(default_factory=list)


class SalesDepartmentDashboardResponse(BaseModel):
    overview: SalesDeptOverviewKpis
    sales_funnel: SalesDeptFunnel
    top_products: list[SalesDeptTopProduct] = Field(default_factory=list)
    top_countries: list[SalesDeptTopCountry] = Field(default_factory=list)
    top_attribution_sources: list[SalesDeptAttributionSource] = Field(default_factory=list)
    partner_performance: list[SalesDeptPartnerPerformance] = Field(default_factory=list)
    action_queue: SalesDeptActionQueue
    sales_assistant: SalesDeptSalesAssistantWidget = Field(default_factory=SalesDeptSalesAssistantWidget)
    operator_tasks: SalesDeptOperatorTasksWidget = Field(default_factory=SalesDeptOperatorTasksWidget)
    sales_manager: SalesDeptSalesManagerWidget = Field(default_factory=SalesDeptSalesManagerWidget)
    lead_intelligence: dict[str, Any] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    filters: dict[str, Any] = Field(default_factory=dict)


class SalesDepartmentAiBriefingResponse(BaseModel):
    executive_summary: str
    what_is_working: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    opportunities: list[str] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)
    priority_score: float = 50.0
    source: str = "fallback"
    errors: list[str] = Field(default_factory=list)
