"""First Pilot Client Preparation v1 — readiness, blockers, recommendations."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

ReadinessStatus = Literal["ready", "warning", "blocked"]
BlockerSeverity = Literal["critical", "warning"]
RecommendationPriority = Literal["high", "medium", "low"]
OperationalStatus = Literal["ready", "warning", "blocked", "unavailable"]


class FirstPilotClientReadinessComponent(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(ge=0, le=100)
    status: ReadinessStatus = "warning"
    details: Optional[str] = None


class FirstPilotClientReadiness(BaseModel):
    score: int = Field(ge=0, le=100)
    components: List[FirstPilotClientReadinessComponent]
    client_identified: bool = False
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    safety_notice: str


class FirstPilotClientOperationalItem(BaseModel):
    key: str
    label: str
    status: OperationalStatus
    ready: bool = False
    message: Optional[str] = None


class FirstPilotClientOperationalReadiness(BaseModel):
    items: List[FirstPilotClientOperationalItem]
    ready_count: int = 0
    total: int = 0
    all_ready: bool = False
    safety_notice: str


class FirstPilotClientBlocker(BaseModel):
    blocker: str
    label: str
    severity: BlockerSeverity
    message: str
    route_hint: Optional[str] = None


class FirstPilotClientBlockersResponse(BaseModel):
    blockers: List[FirstPilotClientBlocker]
    blocker_count: int = 0
    critical_count: int = 0
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    safety_notice: str


class FirstPilotClientRecommendation(BaseModel):
    id: str
    title: str
    description: str
    priority: RecommendationPriority
    route_hint: Optional[str] = None


class FirstPilotClientRecommendationsResponse(BaseModel):
    high_priority: List[FirstPilotClientRecommendation]
    medium_priority: List[FirstPilotClientRecommendation]
    low_priority: List[FirstPilotClientRecommendation]
    total: int = 0
    safety_notice: str


class FirstPilotClientNextAction(BaseModel):
    title: str
    description: str
    route_hint: Optional[str] = None
    priority: RecommendationPriority = "high"


class FirstPilotClientSummary(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    operational_ready: bool = False
    launch_ready: bool = False
    blockers: List[FirstPilotClientBlocker] = Field(default_factory=list)
    recommendations: List[FirstPilotClientRecommendation] = Field(default_factory=list)
    next_action: Optional[FirstPilotClientNextAction] = None
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    onboarding_status: Optional[str] = None
    safety_notice: str


class FirstPilotClientIntegrationCheck(BaseModel):
    module: str
    status: Literal["ok", "degraded"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class FirstPilotClientOverview(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    operational_ready: bool = False
    launch_ready: bool = False
    client_identified: bool = False
    company_name: Optional[str] = None
    application_id: Optional[UUID] = None
    tenant_id: Optional[UUID] = None
    client_id: Optional[UUID] = None
    onboarding_status: Optional[str] = None
    blocker_count: int = 0
    critical_blocker_count: int = 0
    recommendation_count: int = 0
    client_readiness: FirstPilotClientReadiness
    operational_readiness: FirstPilotClientOperationalReadiness
    blockers: List[FirstPilotClientBlocker] = Field(default_factory=list)
    next_action: Optional[FirstPilotClientNextAction] = None
    integration_checks: List[FirstPilotClientIntegrationCheck] = Field(default_factory=list)
    safety_notice: str
    implementation_complete: bool = True


class FirstPilotClientRefreshResponse(BaseModel):
    refreshed_at: datetime
    readiness_score: int = Field(ge=0, le=100)
    blocker_count: int = 0
    launch_ready: bool = False
    next_action: Optional[FirstPilotClientNextAction] = None
    safety_notice: str


class FirstPilotClientSummaryWidget(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    launch_ready: bool = False
    client_identified: bool = False
    company_name: Optional[str] = None
    blocker_count: int = 0
    critical_blocker_count: int = 0
    onboarding_status: Optional[str] = None
    next_action_title: Optional[str] = None
    safety_notice: str
