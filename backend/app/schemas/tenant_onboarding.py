"""Factory tenant onboarding — schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

StepReadinessStatus = Literal["completed", "missing", "recommended", "blocked"]
StepCategory = Literal["platform", "business", "first_success"]


class OnboardingStepReadiness(BaseModel):
    id: str
    label: str
    category: StepCategory
    status: StepReadinessStatus
    route: str
    estimated_minutes: int = 3
    weight: int = 5
    required: bool = True
    completed_at: datetime | None = None
    why_it_matters: str = ""
    next_action: str = ""
    business_value: str = ""


class ExecutiveWalkthroughPanel(BaseModel):
    id: str
    label: str
    route: str
    estimated_minutes: int = 2
    completed: bool = False


class ExecutiveWalkthroughState(BaseModel):
    panels: list[ExecutiveWalkthroughPanel] = Field(default_factory=list)
    completed_panels: int = 0
    total_panels: int = 0
    completed: bool = False


class FirstSuccessSummary(BaseModel):
    achieved_count: int = 0
    total_count: int = 0
    percent: int = 0
    milestones: list[OnboardingStepReadiness] = Field(default_factory=list)
    celebrated: bool = False


class OnboardingNorthStarGoalRequest(BaseModel):
    goal: Literal[
        "export_leads",
        "better_publishing",
        "more_buyers",
        "better_sales_pipeline",
        "brand_awareness",
    ]


class OnboardingNorthStarGoalResponse(BaseModel):
    saved: bool
    goal: str
    label: str


class OnboardingReadinessResponse(BaseModel):
    tenant_id: UUID
    platform_readiness_percent: int
    business_readiness_percent: int
    overall_percent: int
    estimated_minutes_remaining: int
    platform_ready: bool
    platform_steps: list[OnboardingStepReadiness] = Field(default_factory=list)
    business_steps: list[OnboardingStepReadiness] = Field(default_factory=list)
    first_success: FirstSuccessSummary | None = None
    next_step: OnboardingStepReadiness | None = None
    executive_walkthrough: ExecutiveWalkthroughState
    publishing_blockers: list[str] = Field(default_factory=list)
    auto_config_applied: bool = False
    last_activity_at: datetime | None = None
    onboarding_version: int = 2
    north_star_goal: str | None = None
    north_star_label: str | None = None


class OnboardingStepItem(BaseModel):
    id: str
    label: str
    completed: bool
    completed_at: datetime | None = None
    route: str
    estimated_minutes: int = 3


class OnboardingMilestoneMessage(BaseModel):
    step_id: str
    message: str
    shown_at: datetime


class OnboardingDashboardResponse(BaseModel):
    tenant_id: UUID
    status: str
    progress_percent: int
    completed_steps: int
    total_steps: int
    remaining_steps: int
    estimated_minutes_remaining: int
    steps: list[OnboardingStepItem]
    next_step: OnboardingStepItem | None = None
    demo_data_generated: bool
    new_milestones: list[OnboardingMilestoneMessage] = Field(default_factory=list)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    platform_readiness_percent: int = 0
    business_readiness_percent: int = 0
    overall_percent: int = 0
    platform_ready: bool = False
    readiness: OnboardingReadinessResponse | None = None


class OnboardingCompanyProfile(BaseModel):
    company_name: str
    industry: str | None = None
    country: str | None = None
    city: str | None = None
    website: str | None = None
    contact_person: str | None = None
    email: str | None = None
    phone: str | None = None
    preferred_languages: list[str] = Field(default_factory=list)


class OnboardingCompanySaveResponse(BaseModel):
    saved: bool
    profile: OnboardingCompanyProfile
    progress: OnboardingDashboardResponse


class OnboardingChannelStatus(BaseModel):
    telegram: dict[str, Any]
    wechat: dict[str, Any]
    whatsapp: dict[str, Any]


class OnboardingRefreshResponse(BaseModel):
    refreshed: bool
    progress: OnboardingDashboardResponse


class OnboardingDemoDataResponse(BaseModel):
    generated: bool
    message: str
    counts: dict[str, int]
    progress: OnboardingDashboardResponse


class OnboardingAssistantRequest(BaseModel):
    message: str
    context_step: str | None = None


class OnboardingAssistantResponse(BaseModel):
    reply: str
    suggested_route: str | None = None
    source: str = "rules"


class OnboardingGrowthCenterVisitResponse(BaseModel):
    recorded: bool
    progress: OnboardingDashboardResponse


class ExecutiveWalkthroughPanelRequest(BaseModel):
    panel_id: str


class ExecutiveWalkthroughPanelResponse(BaseModel):
    recorded: bool
    panel_id: str
    readiness: OnboardingReadinessResponse


class OnboardingAdminTenantReadinessItem(BaseModel):
    tenant_id: UUID
    company_name: str
    status: str
    platform_readiness_percent: int
    business_readiness_percent: int
    overall_percent: int
    platform_ready: bool
    estimated_minutes_remaining: int
    last_activity_at: datetime | None = None
    top_missing_step: str | None = None
    blocked: bool = False
    inactive: bool = False


class OnboardingAdminReadinessOverview(BaseModel):
    total_tenants: int
    average_platform_readiness: float
    average_business_readiness: float
    average_overall_readiness: float
    platform_ready_count: int
    blocked_tenant_count: int
    inactive_tenant_count: int
    top_missing_steps: dict[str, int] = Field(default_factory=dict)
    tenants: list[OnboardingAdminTenantReadinessItem] = Field(default_factory=list)


class OnboardingAdminTenantItem(BaseModel):
    tenant_id: UUID
    company_name: str
    status: str
    progress_percent: int
    platform_readiness_percent: int = 0
    business_readiness_percent: int = 0
    platform_ready: bool = False
    completed_steps: int
    total_steps: int
    demo_data_generated: bool
    started_at: datetime | None = None
    completed_at: datetime | None = None
    time_to_first_content_hours: float | None = None
    time_to_first_lead_hours: float | None = None
    time_to_first_proposal_hours: float | None = None
    time_to_growth_center_hours: float | None = None
    drop_off_step: str | None = None


class OnboardingAdminAnalytics(BaseModel):
    total_tenants: int
    started_count: int
    completed_count: int
    completion_rate_percent: float
    demo_data_usage_count: int
    avg_time_to_first_content_hours: float | None = None
    avg_time_to_first_lead_hours: float | None = None
    avg_time_to_first_proposal_hours: float | None = None
    avg_time_to_growth_center_hours: float | None = None
    drop_off_by_step: dict[str, int] = Field(default_factory=dict)
    tenants: list[OnboardingAdminTenantItem] = Field(default_factory=list)


class OnboardingAdminActionResponse(BaseModel):
    success: bool
    message: str
    progress: OnboardingDashboardResponse | None = None
