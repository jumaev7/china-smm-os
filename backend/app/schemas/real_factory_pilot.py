"""First Real Factory Pilot v1 — workspace, checklist, readiness, guided actions."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PilotStatus = Literal[
    "not_started",
    "in_progress",
    "blocked",
    "ready_for_demo",
    "ready_for_live_pilot",
    "live_pilot_started",
    "completed",
]
ReadinessStatus = Literal["ready", "warning", "blocked"]
BlockerSeverity = Literal["critical", "warning"]
ChecklistStepStatus = Literal["completed", "pending", "blocked"]


class RealFactoryPilotWorkspace(BaseModel):
    application_id: Optional[UUID] = None
    company_name: Optional[str] = None
    client_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    subscription_status: Optional[str] = None
    admin_user_email: Optional[str] = None
    factory_profile_score: int = 0
    catalog_count: int = 0
    certificate_count: int = 0
    export_market_count: int = 0
    buyer_opportunity_count: int = 0
    marketplace_activity_count: int = 0
    factory_identified: bool = False


class RealFactoryPilotReadinessComponent(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(ge=0, le=100)
    status: ReadinessStatus = "warning"
    details: Optional[str] = None


class RealFactoryPilotReadiness(BaseModel):
    score: int = Field(ge=0, le=100)
    components: List[RealFactoryPilotReadinessComponent]
    factory_identified: bool = False
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    safety_notice: str


class RealFactoryPilotChecklistItem(BaseModel):
    step: str
    label: str
    completed: bool = False
    status: ChecklistStepStatus = "pending"
    completed_at: Optional[datetime] = None
    details: Optional[str] = None


class RealFactoryPilotChecklist(BaseModel):
    items: List[RealFactoryPilotChecklistItem]
    completed_count: int = 0
    total_steps: int = 0
    progress_percent: int = Field(ge=0, le=100, default=0)
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    safety_notice: str


class RealFactoryPilotBlocker(BaseModel):
    blocker: str
    label: str
    severity: BlockerSeverity
    message: str
    route_hint: Optional[str] = None


class RealFactoryPilotBlockersResponse(BaseModel):
    blockers: List[RealFactoryPilotBlocker]
    warnings: List[RealFactoryPilotBlocker] = Field(default_factory=list)
    blocker_count: int = 0
    warning_count: int = 0
    critical_count: int = 0
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    safety_notice: str


class RealFactoryPilotAction(BaseModel):
    action: str
    label: str
    description: str
    route_hint: str
    available: bool = False
    manual_only: bool = True


class RealFactoryPilotActionsResponse(BaseModel):
    actions: List[RealFactoryPilotAction]
    next_action: Optional[RealFactoryPilotAction] = None
    safety_notice: str


class RealFactoryPilotNextAction(BaseModel):
    title: str
    description: str
    route_hint: Optional[str] = None
    action: Optional[str] = None
    priority: Literal["high", "medium", "low"] = "high"


class RealFactoryPilotSummary(BaseModel):
    selected_factory: Optional[RealFactoryPilotWorkspace] = None
    status: PilotStatus = "not_started"
    readiness_score: int = Field(ge=0, le=100)
    blockers: List[RealFactoryPilotBlocker] = Field(default_factory=list)
    warnings: List[RealFactoryPilotBlocker] = Field(default_factory=list)
    next_best_action: Optional[RealFactoryPilotNextAction] = None
    pilot_launch_notes: List[str] = Field(default_factory=list)
    safety_notice: str


class RealFactoryPilotIntegrationCheck(BaseModel):
    module: str
    status: Literal["ok", "degraded"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class RealFactoryPilotOverview(BaseModel):
    status: PilotStatus = "not_started"
    readiness_score: int = Field(ge=0, le=100)
    factory_identified: bool = False
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    blocker_count: int = 0
    warning_count: int = 0
    critical_blocker_count: int = 0
    checklist_completed: int = 0
    checklist_total: int = 0
    workspace: RealFactoryPilotWorkspace
    readiness: RealFactoryPilotReadiness
    checklist: RealFactoryPilotChecklist
    blockers: List[RealFactoryPilotBlocker] = Field(default_factory=list)
    warnings: List[RealFactoryPilotBlocker] = Field(default_factory=list)
    actions: List[RealFactoryPilotAction] = Field(default_factory=list)
    next_best_action: Optional[RealFactoryPilotNextAction] = None
    pilot_launch_notes: List[str] = Field(default_factory=list)
    integration_checks: List[RealFactoryPilotIntegrationCheck] = Field(default_factory=list)
    safety_notice: str
    implementation_complete: bool = True


class RealFactoryPilotRefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int = Field(ge=0, le=100)
    status: PilotStatus = "not_started"
    blocker_count: int = 0
    next_best_action: Optional[RealFactoryPilotNextAction] = None
    safety_notice: str


class RealFactoryPilotSummaryWidget(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    status: PilotStatus = "not_started"
    factory_identified: bool = False
    company_name: Optional[str] = None
    blocker_count: int = 0
    critical_blocker_count: int = 0
    checklist_progress: int = Field(ge=0, le=100, default=0)
    next_action_title: Optional[str] = None
    safety_notice: str


class RealFactoryPilotCandidateIndicator(BaseModel):
    application_id: UUID
    is_pilot_candidate: bool = False
    is_selected_factory: bool = False
    company_name: Optional[str] = None
    readiness_score: int = 0
    status: PilotStatus = "not_started"
    safety_notice: str
