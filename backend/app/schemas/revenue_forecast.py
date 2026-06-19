"""AI Revenue Forecasting v1 — heuristic read-only forecasts."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class RevenueForecastPeriod(BaseModel):
    period: str
    best_case: Decimal = Decimal("0")
    expected_case: Decimal = Decimal("0")
    worst_case: Decimal = Decimal("0")
    currency: str = "UZS"


class RevenueForecastPipelineStage(BaseModel):
    stage: str
    count: int = 0
    forecast_revenue: Decimal = Decimal("0")
    win_probability: float = 0.0


class RevenueForecastRiskItem(BaseModel):
    risk_id: str
    category: str
    title: str
    description: str = ""
    severity: str = "medium"
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None


class RevenueForecastGrowthOpportunity(BaseModel):
    opportunity_id: str
    title: str
    description: str = ""
    expected_impact: Decimal = Decimal("0")
    priority: str = "medium"
    source: str = "forecast"


class RevenueForecastExecutive(BaseModel):
    forecast_summary: str
    top_growth_opportunities: list[RevenueForecastGrowthOpportunity] = Field(default_factory=list)
    top_revenue_risks: list[RevenueForecastRiskItem] = Field(default_factory=list)


class RevenueForecastOverviewResponse(BaseModel):
    forecasts: list[RevenueForecastPeriod] = Field(default_factory=list)
    currency: str = "UZS"
    confidence: str = "medium"
    inputs_summary: dict[str, Any] = Field(default_factory=dict)
    safety_notice: str = "Read-only forecasting — no automatic CRM, deal, messaging, or task actions."
    errors: list[str] = Field(default_factory=list)


class RevenueForecastPipelineResponse(BaseModel):
    stages: list[RevenueForecastPipelineStage] = Field(default_factory=list)
    total_pipeline_forecast: Decimal = Decimal("0")
    currency: str = "UZS"
    errors: list[str] = Field(default_factory=list)


class RevenueForecastRisksResponse(BaseModel):
    inactive_deals: list[RevenueForecastRiskItem] = Field(default_factory=list)
    overdue_opportunities: list[RevenueForecastRiskItem] = Field(default_factory=list)
    proposals_at_risk: list[RevenueForecastRiskItem] = Field(default_factory=list)
    communication_risks: list[RevenueForecastRiskItem] = Field(default_factory=list)
    total: int = 0
    errors: list[str] = Field(default_factory=list)


class RevenueForecastExecutiveResponse(BaseModel):
    executive: RevenueForecastExecutive
    forecasts: list[RevenueForecastPeriod] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class RevenueForecastGenerateRequest(BaseModel):
    client_id: Optional[UUID] = None


class RevenueForecastGenerateResponse(BaseModel):
    forecasts: list[RevenueForecastPeriod] = Field(default_factory=list)
    pipeline: list[RevenueForecastPipelineStage] = Field(default_factory=list)
    executive: RevenueForecastExecutive
    risks_total: int = 0
    currency: str = "UZS"
    source: str = "heuristic"
    generated_at: datetime
    safety_notice: str = "Manual review only — forecasting does not modify CRM or deals."
    errors: list[str] = Field(default_factory=list)


class RevenueForecastSummaryWidget(BaseModel):
    expected_30d: Decimal = Decimal("0")
    best_case_30d: Decimal = Decimal("0")
    worst_case_30d: Decimal = Decimal("0")
    pipeline_forecast: Decimal = Decimal("0")
    confidence: str = "medium"
    top_growth: list[dict[str, Any]] = Field(default_factory=list)
    top_risks: list[dict[str, Any]] = Field(default_factory=list)
    currency: str = "UZS"
    errors: list[str] = Field(default_factory=list)
