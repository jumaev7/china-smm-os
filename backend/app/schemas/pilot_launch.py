"""Pilot Launch QA & Demo Data v1 — launch readiness, demo seed, smoke tests."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

LaunchItemStatus = Literal["completed", "warning", "blocked"]
SmokeStatus = Literal["ok", "warning", "error", "slow"]
QaStepStatus = Literal["pass", "warning", "fail", "skipped"]


class PilotLaunchReadinessComponent(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(ge=0, le=100)
    status: LaunchItemStatus = "warning"
    details: Optional[str] = None


class PilotLaunchReadiness(BaseModel):
    score: int = Field(ge=0, le=100)
    components: List[PilotLaunchReadinessComponent]
    demo_data_present: bool = False
    safety_notice: str


class PilotLaunchChecklistItem(BaseModel):
    id: str
    label: str
    status: LaunchItemStatus
    message: Optional[str] = None
    next_action: Optional[str] = None


class PilotLaunchChecklist(BaseModel):
    items: List[PilotLaunchChecklistItem]
    completed_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    next_action: Optional[str] = None
    safety_notice: str


class PilotLaunchSmokeTest(BaseModel):
    page: str
    route: str
    api_probe: Optional[str] = None
    status: SmokeStatus
    duration_ms: Optional[int] = None
    message: Optional[str] = None


class PilotLaunchSmokeTestsResponse(BaseModel):
    tests: List[PilotLaunchSmokeTest]
    ok_count: int = 0
    total: int = 0


class PilotLaunchQaStep(BaseModel):
    step: str
    label: str
    status: QaStepStatus
    message: Optional[str] = None


class PilotLaunchIntegrationCheck(BaseModel):
    module: str
    status: Literal["ok", "degraded"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class PilotLaunchOverview(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    demo_data_present: bool = False
    demo_company_name: Optional[str] = None
    demo_application_id: Optional[UUID] = None
    demo_tenant_id: Optional[UUID] = None
    qa_pass_count: int = 0
    qa_total: int = 0
    smoke_ok_count: int = 0
    smoke_total: int = 0
    checklist_completed: int = 0
    checklist_blocked: int = 0
    blockers: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    integration_checks: List[PilotLaunchIntegrationCheck] = Field(default_factory=list)
    safety_notice: str
    implementation_complete: bool = True


class PilotLaunchDemoSeedRequest(BaseModel):
    force: bool = False


class PilotLaunchDemoSeedResponse(BaseModel):
    created: bool
    message: str
    demo_marker: str
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    portal_account_id: Optional[UUID] = None
    subscription_id: Optional[UUID] = None
    login_email: Optional[str] = None
    login_password: Optional[str] = None
    counts: dict[str, int] = Field(default_factory=dict)


class PilotLaunchQaResponse(BaseModel):
    ran_at: datetime
    pass_count: int
    warning_count: int
    fail_count: int
    steps: List[PilotLaunchQaStep]
    safety_notice: str
