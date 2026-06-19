"""Pilot Client Onboarding v1 — guided admin workflow schemas (read-only aggregation)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PilotOnboardingStatus = Literal[
    "not_started",
    "in_progress",
    "blocked",
    "ready",
    "completed",
]

PilotOnboardingChecklistStep = Literal[
    "application_submitted",
    "application_approved",
    "client_created",
    "tenant_created",
    "portal_account_created",
    "subscription_created",
    "admin_user_created",
    "factory_profile_completed",
    "product_catalog_added",
    "billing_ready",
    "pilot_ready",
]

PilotOnboardingBlocker = Literal[
    "tenant",
    "subscription",
    "portal_account",
    "admin_user",
    "company_profile",
    "products",
    "billing",
    "application_rejected",
    "application_not_approved",
]

PilotOnboardingAction = Literal[
    "approve_application",
    "create_client",
    "create_tenant",
    "create_portal_account",
    "create_subscription",
    "create_admin_user",
    "open_factory_profile",
    "open_billing",
]


class PilotOnboardingChecklistItem(BaseModel):
    step: PilotOnboardingChecklistStep
    label: str
    completed: bool = False
    completed_at: Optional[datetime] = None
    details: Optional[str] = None


class PilotOnboardingBlockerItem(BaseModel):
    blocker: PilotOnboardingBlocker
    label: str
    severity: Literal["critical", "warning"] = "critical"
    message: str


class PilotOnboardingActionItem(BaseModel):
    action: PilotOnboardingAction
    label: str
    description: str
    available: bool = False
    route_hint: Optional[str] = None
    manual_only: bool = True


class PilotOnboardingSummary(BaseModel):
    application_id: UUID
    company: str
    status: PilotOnboardingStatus
    application_status: str
    readiness_score: int = Field(default=0, ge=0, le=100)
    blockers: List[PilotOnboardingBlockerItem] = Field(default_factory=list)
    next_best_action: Optional[PilotOnboardingActionItem] = None
    tenant_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    updated_at: Optional[datetime] = None


class PilotOnboardingOverview(BaseModel):
    total_applications: int = 0
    not_started: int = 0
    in_progress: int = 0
    blocked: int = 0
    ready: int = 0
    completed: int = 0
    average_readiness_score: int = 0
    pilot_ready_count: int = 0
    pending_approval: int = 0
    integration_checks: List[dict[str, Any]] = Field(default_factory=list)
    safety_notice: str = (
        "Guided onboarding only — no automatic approval, tenant creation, "
        "subscription creation, or user creation."
    )


class PilotOnboardingApplicationsResponse(BaseModel):
    items: List[PilotOnboardingSummary]
    total: int


class PilotOnboardingDetail(PilotOnboardingSummary):
    checklist: List[PilotOnboardingChecklistItem] = Field(default_factory=list)
    available_actions: List[PilotOnboardingActionItem] = Field(default_factory=list)
    country: Optional[str] = None
    industry: Optional[str] = None
    submitted_at: Optional[datetime] = None
    reviewed_at: Optional[datetime] = None


class PilotOnboardingChecklistResponse(BaseModel):
    application_id: UUID
    company: str
    readiness_score: int = Field(default=0, ge=0, le=100)
    checklist: List[PilotOnboardingChecklistItem]
    completed_count: int = 0
    total_steps: int = 11


class PilotOnboardingBlockersResponse(BaseModel):
    application_id: UUID
    company: str
    blockers: List[PilotOnboardingBlockerItem]
    blocker_count: int = 0


class PilotOnboardingActionsResponse(BaseModel):
    application_id: UUID
    company: str
    actions: List[PilotOnboardingActionItem]
    next_best_action: Optional[PilotOnboardingActionItem] = None


class PilotOnboardingRefreshResponse(BaseModel):
    application_id: UUID
    company: str
    status: PilotOnboardingStatus
    readiness_score: int = Field(default=0, ge=0, le=100)
    blockers: List[PilotOnboardingBlockerItem] = Field(default_factory=list)
    next_best_action: Optional[PilotOnboardingActionItem] = None
    refreshed_at: datetime
    message: str = "Onboarding state refreshed — manual admin actions only."


class PilotOnboardingSummaryWidget(BaseModel):
    total_tracked: int = 0
    in_progress: int = 0
    blocked: int = 0
    pilot_ready: int = 0
    average_readiness_score: int = 0
    pending_approval: int = 0
    latest_company_name: Optional[str] = None
    safety_notice: str = (
        "Guided onboarding only — no automatic approval or provisioning."
    )
