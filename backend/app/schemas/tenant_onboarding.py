"""Factory tenant onboarding — schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


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


class OnboardingAdminTenantItem(BaseModel):
    tenant_id: UUID
    company_name: str
    status: str
    progress_percent: int
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
