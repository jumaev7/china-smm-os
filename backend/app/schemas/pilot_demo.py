"""Pilot Demo Scenario v1 — guided presentation, demo metrics, readiness."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

DemoStepStatus = Literal["ready", "warning", "blocked", "info"]
DemoHealthStatus = Literal["ok", "warning", "error"]
ScenarioAudience = Literal["factory_owner", "sales_director", "executive", "distributor"]


class PilotDemoScenario(BaseModel):
    id: str
    title: str
    audience: ScenarioAudience
    description: str
    estimated_minutes: int = Field(ge=1, le=180)
    recommended_for: str
    journey_route: Optional[str] = None


class PilotDemoScenariosResponse(BaseModel):
    scenarios: List[PilotDemoScenario]
    default_scenario_id: str = "factory_owner_demo"
    safety_notice: str


class PilotDemoJourneyStep(BaseModel):
    step: int
    id: str
    title: str
    narrative: str
    admin_route: Optional[str] = None
    tenant_route: Optional[str] = None
    status: DemoStepStatus = "info"
    message: Optional[str] = None
    show_next: bool = True


class PilotDemoJourney(BaseModel):
    scenario_id: str
    title: str
    steps: List[PilotDemoJourneyStep]
    completed_steps: int = 0
    total_steps: int = 0
    current_step_id: Optional[str] = None
    safety_notice: str


class PilotDemoMetrics(BaseModel):
    demo_buyers: int = 0
    demo_opportunities: int = 0
    demo_revenue_usd: float = 0
    demo_forecast_periods: int = 0
    demo_marketplace_opportunities: int = 0
    demo_deals: int = 0
    demo_proposals: int = 0
    demo_data_present: bool = False
    demo_company_name: Optional[str] = None
    details: dict[str, Any] = Field(default_factory=dict)


class PilotDemoHealthItem(BaseModel):
    key: str
    label: str
    status: DemoHealthStatus
    message: Optional[str] = None


class PilotDemoReadiness(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    missing_data: List[str] = Field(default_factory=list)
    broken_links: List[str] = Field(default_factory=list)
    unavailable_pages: List[str] = Field(default_factory=list)
    items: List[PilotDemoHealthItem] = Field(default_factory=list)
    demo_data_present: bool = False
    safety_notice: str


class PilotDemoPresentationStep(BaseModel):
    order: int
    title: str
    route: str
    minutes: int
    talking_points: List[str] = Field(default_factory=list)


class PilotDemoPresentationFlow(BaseModel):
    scenario_id: str
    title: str
    steps: List[PilotDemoPresentationStep]
    estimated_total_minutes: int
    recommended_flow: List[str] = Field(default_factory=list)
    what_to_show_next: Optional[str] = None
    safety_notice: str


class PilotDemoSummary(BaseModel):
    what_to_show_next: Optional[str] = None
    recommended_flow: List[str] = Field(default_factory=list)
    estimated_presentation_minutes: int = 0
    readiness_score: int = Field(ge=0, le=100)
    default_scenario_id: str = "factory_owner_demo"
    safety_notice: str


class PilotDemoOverview(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    demo_data_present: bool = False
    demo_company_name: Optional[str] = None
    active_scenario_id: str = "factory_owner_demo"
    metrics: PilotDemoMetrics
    summary: PilotDemoSummary
    next_recommended_step: Optional[str] = None
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    safety_notice: str
    implementation_complete: bool = True
    refreshed_at: datetime


class PilotDemoRefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int
    message: str
    safety_notice: str
