"""Operator Workspace — attention projection and Phase 1 action schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


AttentionCategory = Literal[
    "content_internal_review",
    "waiting_for_client",
    "publishing_issue",
    "scheduling_issue",
    "integration_issue",
    "telegram_ingestion_issue",
    "automation_failure",
]

AttentionPriority = Literal["critical", "high", "medium", "low"]

ResponsibleParty = Literal["operator", "client", "system", "provider"]

AttentionSourceDomain = Literal[
    "content",
    "publishing",
    "calendar",
    "integration",
    "telegram",
    "automation",
]

WorkspaceActionType = Literal["mutation", "navigation"]

WorkspaceActionId = Literal[
    "open",
    "acknowledge_alert",
    "resolve_alert",
    "retry_publish",
    "approve_content",
]


class OperatorWorkspaceAction(BaseModel):
    """Derived action metadata — never persisted; recomputed from canonical state."""

    action_id: str
    label: str
    action_type: WorkspaceActionType
    enabled: bool = True
    requires_confirmation: bool = False
    confirmation_message: str | None = None
    disabled_reason: str | None = None
    destructive: bool = False
    external_side_effect: bool = False
    target_resource: str | None = None
    href: str | None = None
    primary: bool = False


class OperatorAttentionItem(BaseModel):
    id: str
    attention_type: AttentionCategory
    priority: AttentionPriority
    client_id: UUID | None = None
    company_name: str
    content_id: UUID | None = None
    resource_id: str | None = None
    title: str
    reason: str
    current_state: str | None = None
    responsible_party: ResponsibleParty
    suggested_action: str
    action_path: str
    created_at: datetime | None = None
    due_at: datetime | None = None
    overdue: bool = False
    source_domain: AttentionSourceDomain
    metadata: dict = Field(default_factory=dict)
    actions: list[OperatorWorkspaceAction] = Field(default_factory=list)


class OperatorWorkspaceSummary(BaseModel):
    needs_action_now: int = 0
    waiting_for_client: int = 0
    publishing_issues: int = 0
    due_today: int = 0
    integration_issues: int = 0
    scheduling_issues: int = 0
    telegram_issues: int = 0
    automation_failures: int = 0
    total: int = 0


class OperatorWorkspaceItemsResponse(BaseModel):
    items: list[OperatorAttentionItem]
    total: int
    page: int
    page_size: int
    summary: OperatorWorkspaceSummary


class OperatorWorkspaceSummaryResponse(BaseModel):
    summary: OperatorWorkspaceSummary


class OperatorWorkspaceActionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class OperatorWorkspaceActionResult(BaseModel):
    success: bool
    action_id: str
    message: str
    canonical_state: dict | None = None
    attention_still_relevant: bool = False
    refresh_recommended: bool = True
    redirect_path: str | None = None


MetricsWindow = Literal["24h", "7d", "30d"]


class OperatorWorkspaceMetricsResponse(BaseModel):
    """Compact observability payload. Null/unavailable fields are preferred over guesses."""

    window: MetricsWindow
    generated_at: datetime
    attention: dict = Field(default_factory=dict)
    actions: dict = Field(default_factory=dict)
    resolution: dict = Field(default_factory=dict)
    automation_candidates: list[dict] = Field(default_factory=list)
    top_recurring_issue: str | None = None
    oldest_unresolved_age_seconds: int | None = None
    age_semantics: dict[str, str] = Field(default_factory=dict)
    notes: dict[str, str] = Field(default_factory=dict)
    candidate_catalog: list[dict] = Field(default_factory=list)
