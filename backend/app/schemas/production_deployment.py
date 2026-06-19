"""Production Deployment Preparation v1 — readiness, environment, checklist schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

ReadinessStatus = Literal["ready", "warning", "blocked"]
EnvCheckStatus = Literal["valid", "warning", "critical"]
ChecklistStatus = Literal["completed", "warning", "blocked"]
BackupStatus = Literal["ready", "warning", "blocked"]
MonitoringStatus = Literal["ready", "warning", "blocked"]
FindingSeverity = Literal["critical", "warning"]
RecommendationPriority = Literal["high", "medium", "low"]


class ProductionReadinessComponent(BaseModel):
    key: str
    label: str
    score: int = Field(ge=0, le=100)
    weight: int = Field(ge=0, le=100)
    status: ReadinessStatus = "warning"
    details: Optional[str] = None


class ProductionReadiness(BaseModel):
    production_readiness_score: int = Field(ge=0, le=100)
    components: List[ProductionReadinessComponent]
    safety_notice: str


class ProductionEnvironmentCheck(BaseModel):
    key: str
    label: str
    status: EnvCheckStatus
    message: str
    configured: bool = False


class ProductionEnvironmentValidation(BaseModel):
    valid: bool = False
    critical_count: int = 0
    warning_count: int = 0
    checks: List[ProductionEnvironmentCheck]
    safety_notice: str


class ProductionChecklistItem(BaseModel):
    key: str
    label: str
    status: ChecklistStatus
    message: str
    next_action: Optional[str] = None


class ProductionDeploymentChecklist(BaseModel):
    items: List[ProductionChecklistItem]
    completed_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    all_ready: bool = False
    next_action: Optional[str] = None
    safety_notice: str


class ProductionBackupItem(BaseModel):
    key: str
    label: str
    status: BackupStatus
    message: str
    configured: bool = False


class ProductionBackupReadiness(BaseModel):
    items: List[ProductionBackupItem]
    ready_count: int = 0
    total: int = 0
    all_ready: bool = False
    safety_notice: str


class ProductionMonitoringItem(BaseModel):
    key: str
    label: str
    status: MonitoringStatus
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ProductionMonitoringReadiness(BaseModel):
    items: List[ProductionMonitoringItem]
    ready_count: int = 0
    total: int = 0
    all_ready: bool = False
    safety_notice: str


class ProductionSecurityFinding(BaseModel):
    key: str
    label: str
    severity: FindingSeverity
    message: str


class ProductionSecurityReadiness(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    critical_findings: List[ProductionSecurityFinding] = Field(default_factory=list)
    warnings: List[ProductionSecurityFinding] = Field(default_factory=list)
    protected_route_count: int = 0
    open_route_count: int = 0
    permission_coverage_percent: float = 0.0
    implementation_complete: bool = False
    safety_notice: str


class ProductionRecommendation(BaseModel):
    id: str
    title: str
    description: str
    priority: RecommendationPriority
    route_hint: Optional[str] = None


class ProductionNextAction(BaseModel):
    title: str
    description: str
    route_hint: Optional[str] = None
    priority: RecommendationPriority = "high"


class ProductionSummary(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    deployment_ready: bool = False
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    recommendations: List[ProductionRecommendation] = Field(default_factory=list)
    next_action: Optional[ProductionNextAction] = None
    safety_notice: str


class ProductionIntegrationCheck(BaseModel):
    module: str
    status: Literal["ok", "degraded"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ProductionDeploymentOverview(BaseModel):
    production_readiness_score: int = Field(ge=0, le=100)
    deployment_ready: bool = False
    environment_valid: bool = False
    checklist_completed: int = 0
    checklist_blocked: int = 0
    backup_ready: bool = False
    monitoring_ready: bool = False
    security_score: int = Field(ge=0, le=100)
    critical_finding_count: int = 0
    blocker_count: int = 0
    warning_count: int = 0
    readiness: ProductionReadiness
    environment: ProductionEnvironmentValidation
    checklist: ProductionDeploymentChecklist
    backups: ProductionBackupReadiness
    monitoring: ProductionMonitoringReadiness
    security: ProductionSecurityReadiness
    summary: ProductionSummary
    integration_checks: List[ProductionIntegrationCheck] = Field(default_factory=list)
    safety_notice: str
    implementation_complete: bool = True


class ProductionDeploymentRefreshResponse(BaseModel):
    refreshed_at: datetime
    production_readiness_score: int = Field(ge=0, le=100)
    deployment_ready: bool = False
    blocker_count: int = 0
    next_action: Optional[ProductionNextAction] = None
    safety_notice: str


class ProductionDeploymentSummaryWidget(BaseModel):
    production_readiness_score: int = Field(ge=0, le=100)
    deployment_ready: bool = False
    blocker_count: int = 0
    critical_finding_count: int = 0
    environment_valid: bool = False
    next_action_title: Optional[str] = None
    safety_notice: str
