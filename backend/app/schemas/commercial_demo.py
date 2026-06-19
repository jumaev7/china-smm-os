"""Commercial Demo Factory Experience — schemas for sales demo routes."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

DemoFactoryPackageId = Literal["haocheng", "toy_manufacturer", "textile_factory"]
DemoTourStepStatus = Literal["pending", "active", "complete"]
ExportStoryStepStatus = Literal["complete", "active", "pending"]


class DemoFactoryPackageSummary(BaseModel):
    id: DemoFactoryPackageId
    company_name: str
    industry: str
    country: str
    description: str
    highlights: list[str] = Field(default_factory=list)


class DemoFactoryPackageList(BaseModel):
    packages: list[DemoFactoryPackageSummary] = Field(default_factory=list)


class DemoFactoryLoadResponse(BaseModel):
    loaded: bool
    package_id: DemoFactoryPackageId
    company_name: str
    message: str
    counts: dict[str, int] = Field(default_factory=dict)


class DemoTourStep(BaseModel):
    order: int
    id: str
    title: str
    description: str
    route: str
    minutes: int
    talking_points: list[str] = Field(default_factory=list)
    business_value: str


class DemoTourResponse(BaseModel):
    title: str = "Platform Demo Tour"
    estimated_minutes: int = 10
    steps: list[DemoTourStep] = Field(default_factory=list)


class ExportGrowthStoryStep(BaseModel):
    order: int
    id: str
    title: str
    description: str
    route: str
    status: ExportStoryStepStatus = "pending"
    metric_label: str | None = None
    metric_value: str | None = None


class ExportGrowthStoryResponse(BaseModel):
    title: str = "Export Growth Story"
    subtitle: str
    steps: list[ExportGrowthStoryStep] = Field(default_factory=list)
    total_pipeline_usd: float = 0
    roi_improvement_pct: float = 0


class ValueDemoAction(BaseModel):
    id: str
    title: str
    description: str
    route: str
    priority: Literal["high", "medium", "low"] = "medium"


class ValueDemoResponse(BaseModel):
    buyers_found: int = 0
    opportunities_generated: int = 0
    pipeline_value_usd: float = 0
    estimated_revenue_influenced_usd: float = 0
    active_deals: int = 0
    proposals_sent: int = 0
    communications_active: int = 0
    content_pieces: int = 0
    ai_recommendations: int = 0
    actions_today: list[ValueDemoAction] = Field(default_factory=list)
    demo_data_loaded: bool = False
    company_name: str | None = None


class ExecutiveDemoKpi(BaseModel):
    label: str
    value: str
    change: str | None = None
    trend: Literal["up", "down", "neutral"] = "neutral"


class ExecutiveDemoSection(BaseModel):
    id: str
    title: str
    summary: str
    route: str
    highlights: list[str] = Field(default_factory=list)


class ExecutiveDemoResponse(BaseModel):
    company_name: str
    industry: str | None = None
    country: str | None = None
    headline: str
    kpis: list[ExecutiveDemoKpi] = Field(default_factory=list)
    sections: list[ExecutiveDemoSection] = Field(default_factory=list)
    ai_recommendations: list[str] = Field(default_factory=list)
    roi_score: int = Field(ge=0, le=100, default=0)
    generated_at: datetime


class PositioningComparison(BaseModel):
    category: str
    traditional: str
    this_platform: str


class ProductPositioningResponse(BaseModel):
    mission: str
    tagline: str
    differentiators: list[str] = Field(default_factory=list)
    comparisons: list[PositioningComparison] = Field(default_factory=list)
    key_capabilities: list[str] = Field(default_factory=list)


class ReadinessComponent(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: float
    status: Literal["ready", "partial", "missing"]
    notes: str | None = None


class DemoReadinessResponse(BaseModel):
    score: int = Field(ge=0, le=100)
    grade: Literal["A", "B", "C", "D", "F"]
    components: list[ReadinessComponent] = Field(default_factory=list)
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    recommended_next_steps: list[str] = Field(default_factory=list)


class DemoModeStatus(BaseModel):
    enabled: bool = False
    active_package: DemoFactoryPackageId | None = None
    message: str | None = None
