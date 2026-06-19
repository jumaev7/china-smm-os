"""Pilot Demo Polish & Sales Presentation v1 — execution dataset sales walkthrough."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

SalesDemoStepStatus = Literal["ready", "warning", "blocked", "info"]


class PilotSalesDemoMetrics(BaseModel):
    readiness_score: int = Field(ge=0, le=100, default=0)
    buyers_found: int = 0
    opportunities: int = 0
    active_deals: int = 0
    pipeline_value_usd: float = 0
    revenue_forecast_usd: float = 0
    deal_rooms: int = 0
    buyer_countries: List[str] = Field(default_factory=list)
    execution_data_present: bool = False
    company_name: Optional[str] = None
    factory_profile_score: int = Field(ge=0, le=100, default=0)
    details: dict[str, Any] = Field(default_factory=dict)


class PilotSalesDemoStoryPhase(BaseModel):
    phase: str
    title: str
    narrative: str
    highlights: List[str] = Field(default_factory=list)
    status: SalesDemoStepStatus = "info"


class PilotSalesDemoFactoryOwnerStory(BaseModel):
    company_name: Optional[str] = None
    execution_data_present: bool = False
    phases: List[PilotSalesDemoStoryPhase] = Field(default_factory=list)
    safety_notice: str


class PilotSalesDemoFlowStep(BaseModel):
    order: int
    title: str
    route: str
    minutes: int
    talking_points: List[str] = Field(default_factory=list)
    module: str


class PilotSalesDemoFlow(BaseModel):
    title: str = "15-Minute Sales Demo Flow"
    steps: List[PilotSalesDemoFlowStep] = Field(default_factory=list)
    estimated_total_minutes: int = 15
    safety_notice: str


class PilotSalesDemoCta(BaseModel):
    id: str
    title: str
    description: str
    route: str
    action_type: Literal["link", "hint"] = "link"


class PilotSalesDemoSection(BaseModel):
    id: str
    title: str
    summary: str
    highlights: List[str] = Field(default_factory=list)
    status: SalesDemoStepStatus = "info"
    route: Optional[str] = None


class PilotSalesDemoOverview(BaseModel):
    execution_marker: str = "[PILOT_EXECUTION_V1]"
    execution_data_present: bool = False
    company_name: Optional[str] = None
    implementation_complete: bool = False
    readiness_score: int = Field(ge=0, le=100, default=0)
    metrics: PilotSalesDemoMetrics
    sections: List[PilotSalesDemoSection] = Field(default_factory=list)
    factory_owner_story: PilotSalesDemoFactoryOwnerStory
    demo_flow: PilotSalesDemoFlow
    ctas: List[PilotSalesDemoCta] = Field(default_factory=list)
    executive_summary: str = ""
    pilot_execution_report_route: str = "/real-factory-pilot"
    safety_notice: str
    refreshed_at: datetime


class PilotSalesDemoSummaryWidget(BaseModel):
    readiness_score: int = Field(ge=0, le=100, default=0)
    execution_data_present: bool = False
    company_name: Optional[str] = None
    buyers_found: int = 0
    active_deals: int = 0
    pipeline_value_usd: float = 0
    deal_rooms: int = 0
    implementation_complete: bool = False
    next_demo_step: Optional[str] = None
    safety_notice: str


class PilotSalesDemoRefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int
    message: str
    safety_notice: str
