"""Operator Workspace Phase 1 — read-only attention projection schemas."""
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
