from datetime import datetime
from typing import Literal

from pydantic import BaseModel

AuditSeverity = Literal["critical", "warning", "info"]


class AuditIssue(BaseModel):
    id: str
    severity: AuditSeverity
    category: str
    title: str
    description: str
    entity_type: str
    entity_id: str | None = None
    suggested_fix: str
    fix_action_type: str | None = None
    fix_action_label: str | None = None
    fix_action_endpoint: str | None = None
    fix_action_method: str | None = None


class AuditFixApplyResponse(BaseModel):
    ok: bool
    message: str
    fix_action_type: str
    entity_type: str | None = None
    entity_id: str | None = None
    navigate_to: str | None = None
    result: dict | None = None


class AuditSummary(BaseModel):
    critical: int
    warning: int
    info: int
    total: int


class AuditOverviewResponse(BaseModel):
    issues: list[AuditIssue]
    summary: AuditSummary
    categories: list[str]
    ran_at: datetime
    errors: list[str] = []
