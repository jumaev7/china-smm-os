"""Pilot Readiness Dashboard — demo prep health and route stability audit."""
from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ReadinessStatus = Literal["ready", "warning", "blocked"]
RouteAuditStatus = Literal["pass", "fail", "denied", "slow", "skipped"]


class PilotReadinessHealthComponent(BaseModel):
    key: str
    label: str
    status: ReadinessStatus
    score: int = Field(ge=0, le=100)
    message: Optional[str] = None


class PilotReadinessRouteAudit(BaseModel):
    route: str
    canonical_route: Optional[str] = None
    audience: Literal["tenant", "admin", "both"]
    status: RouteAuditStatus
    access: Literal["allowed", "denied", "login_required", "unknown", "not_probed"]
    api_probe: Optional[str] = None
    api_status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    issue: Optional[str] = None


class PilotReadinessOverview(BaseModel):
    readiness_score: int = Field(ge=0, le=100)
    status: ReadinessStatus
    generated_at: datetime
    safety_notice: str

    demo_tenant_health: PilotReadinessHealthComponent
    auth_rbac_status: PilotReadinessHealthComponent
    backend_status: PilotReadinessHealthComponent
    database_status: PilotReadinessHealthComponent

    briefs_count: int = 0
    content_tasks_count: int = 0
    approved_content_count: int = 0
    scheduled_published_content_count: int = 0

    open_issues: List[str] = Field(default_factory=list)
    route_audits: List[PilotReadinessRouteAudit] = Field(default_factory=list)
    routes_pass_count: int = 0
    routes_fail_count: int = 0
