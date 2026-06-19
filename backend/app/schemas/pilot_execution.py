"""Pilot Client Onboarding Execution v1 — seed, report, readiness, page verification."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ExecutionStepStatus = Literal["completed", "warning", "blocked", "pending"]
PageVerifyStatus = Literal["ok", "warning", "error", "slow"]


class PilotExecutionReadinessSnapshot(BaseModel):
    real_factory_pilot: int = Field(ge=0, le=100, default=0)
    buyer_acquisition_engine: int = Field(ge=0, le=100, default=0)
    revenue_engine: int = Field(ge=0, le=100, default=0)
    factory_profile_score: int = Field(ge=0, le=100, default=0)


class PilotExecutionStep(BaseModel):
    step: str
    label: str
    status: ExecutionStepStatus
    message: Optional[str] = None


class PilotExecutionPageVerify(BaseModel):
    page: str
    route: str
    api_probe: Optional[str] = None
    status: PageVerifyStatus
    duration_ms: Optional[int] = None
    message: Optional[str] = None


class PilotExecutionSeedRequest(BaseModel):
    force: bool = False


class PilotExecutionSeedResponse(BaseModel):
    created: bool
    message: str
    execution_marker: str
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    login_email: Optional[str] = None
    login_password: Optional[str] = None
    counts: dict[str, Any] = Field(default_factory=dict)


class PilotExecutionReport(BaseModel):
    execution_marker: str
    execution_data_present: bool
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    completed_steps: List[PilotExecutionStep]
    remaining_blockers: List[str]
    readiness_before: PilotExecutionReadinessSnapshot
    readiness_after: PilotExecutionReadinessSnapshot
    next_action: Optional[str] = None
    verified_pages: List[PilotExecutionPageVerify] = Field(default_factory=list)
    pages_ok_count: int = 0
    pages_total: int = 0
    safety_notice: str
    implementation_complete: bool = False
    generated_at: datetime


class PilotExecutionOverview(BaseModel):
    execution_data_present: bool
    company_name: Optional[str] = None
    readiness_after: PilotExecutionReadinessSnapshot
    completed_step_count: int = 0
    blocked_step_count: int = 0
    remaining_blockers: List[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    safety_notice: str
    implementation_complete: bool = False


class PilotExecutionVerifyResponse(BaseModel):
    tests: List[PilotExecutionPageVerify]
    ok_count: int = 0
    total: int = 0
