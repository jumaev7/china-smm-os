"""Pilot Launch Validation v1 — end-to-end pilot experience readiness."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

ValidationStatus = Literal["ready", "warning", "blocked"]
FlowItemStatus = Literal["ready", "warning", "blocked"]
DataItemStatus = Literal["ready", "warning", "blocked"]


class PilotLaunchValidationReadinessComponent(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(ge=0, le=100)
    status: ValidationStatus = "warning"
    details: Optional[str] = None


class PilotLaunchValidationReadiness(BaseModel):
    score: int = Field(ge=0, le=100)
    components: List[PilotLaunchValidationReadinessComponent]
    execution_data_present: bool = False
    safety_notice: str


class PilotLaunchValidationFlowItem(BaseModel):
    id: str
    label: str
    route: str
    api_probe: Optional[str] = None
    status: FlowItemStatus
    reason: Optional[str] = None
    missing_items: List[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    duration_ms: Optional[int] = None


class PilotLaunchValidationFlow(BaseModel):
    flow_type: Literal["admin", "tenant"]
    items: List[PilotLaunchValidationFlowItem]
    ready_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    safety_notice: str


class PilotLaunchValidationDataItem(BaseModel):
    id: str
    label: str
    status: DataItemStatus
    count: int = 0
    required_min: int = 0
    reason: Optional[str] = None
    missing_items: List[str] = Field(default_factory=list)
    next_action: Optional[str] = None


class PilotLaunchValidationDataCompleteness(BaseModel):
    items: List[PilotLaunchValidationDataItem]
    ready_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    execution_data_present: bool = False
    company_name: Optional[str] = None
    safety_notice: str


class PilotLaunchValidationPageReadiness(BaseModel):
    page: str
    route: str
    status: ValidationStatus
    reason: Optional[str] = None
    missing_items: List[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    api_probe: Optional[str] = None
    probe_status: Optional[str] = None


class PilotLaunchValidationClientFacing(BaseModel):
    pages: List[PilotLaunchValidationPageReadiness]
    ready_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    safety_notice: str


class PilotLaunchValidationBlocker(BaseModel):
    id: str
    label: str
    category: Literal["admin_flow", "tenant_flow", "data", "page", "auth", "other"]
    severity: Literal["warning", "blocked"]
    reason: Optional[str] = None
    next_action: Optional[str] = None


class PilotLaunchValidationBlockers(BaseModel):
    blockers: List[PilotLaunchValidationBlocker]
    warning_count: int = 0
    blocked_count: int = 0
    safety_notice: str


class PilotLaunchValidationNextActions(BaseModel):
    actions: List[str] = Field(default_factory=list)
    primary_action: Optional[str] = None
    safety_notice: str


class PilotLaunchValidationOverview(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    execution_marker: str = "[PILOT_EXECUTION_V1]"
    execution_data_present: bool = False
    company_name: Optional[str] = None
    admin_flow_ready: int = 0
    admin_flow_total: int = 0
    tenant_flow_ready: int = 0
    tenant_flow_total: int = 0
    data_ready_count: int = 0
    data_total: int = 0
    client_facing_ready: int = 0
    client_facing_total: int = 0
    blocker_count: int = 0
    warning_count: int = 0
    blockers: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)
    primary_next_action: Optional[str] = None
    implementation_complete: bool = False
    safety_notice: str
    refreshed_at: datetime


class PilotLaunchValidationSummaryWidget(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    execution_data_present: bool = False
    company_name: Optional[str] = None
    admin_flow_ready: int = 0
    admin_flow_total: int = 0
    tenant_flow_ready: int = 0
    tenant_flow_total: int = 0
    blocker_count: int = 0
    warning_count: int = 0
    primary_next_action: Optional[str] = None
    implementation_complete: bool = False
    safety_notice: str


class PilotLaunchValidationRefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int = Field(ge=0, le=100)
    message: str
    safety_notice: str
