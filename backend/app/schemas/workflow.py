"""Workflow Builder API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

WorkflowStatus = Literal["draft", "published", "paused", "archived"]
WorkflowVersionState = Literal["draft", "published", "superseded"]
WorkflowValidationStatus = Literal["pending", "valid", "invalid"]
WorkflowExecutionStatus = Literal["pending", "running", "success", "failed", "skipped", "cancelled"]
WorkflowExecutionKind = Literal["event", "manual", "test"]
WorkflowTestMode = Literal["evaluate_only"]
AutomationActionType = Literal[
    "create_notification",
    "create_crm_lead",
    "update_customer_success_progress",
    "record_activity",
]


class WorkflowDefinitionTrigger(BaseModel):
    event: str


class WorkflowActionStep(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    type: Literal["action"] = "action"
    action_type: AutomationActionType
    config: dict[str, Any] = Field(default_factory=dict)


class WorkflowDefinition(BaseModel):
    schema_version: int = 1
    trigger: WorkflowDefinitionTrigger
    conditions: dict[str, Any] | None = None
    steps: list[WorkflowActionStep] = Field(default_factory=list)
    failure_policy: Literal["stop_on_failure"] = "stop_on_failure"


class WorkflowCreate(BaseModel):
    key: str | None = Field(None, min_length=1, max_length=120)
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    definition: dict[str, Any] | None = None


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    definition: dict[str, Any] | None = None
    draft_revision: int = Field(..., ge=1)


class WorkflowValidateRequest(BaseModel):
    definition: dict[str, Any] | None = None


class WorkflowValidationErrorItem(BaseModel):
    code: str
    message: str
    path: str | None = None


class WorkflowValidateResponse(BaseModel):
    valid: bool
    errors: list[WorkflowValidationErrorItem] = Field(default_factory=list)
    definition_hash: str | None = None
    normalized_definition: dict[str, Any] | None = None


class WorkflowVersionSummary(BaseModel):
    id: UUID
    workflow_id: UUID
    version_number: int
    state: WorkflowVersionState
    validation_status: WorkflowValidationStatus
    definition_hash: str | None = None
    created_at: datetime
    published_at: datetime | None = None


class WorkflowVersionDetail(WorkflowVersionSummary):
    definition: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[WorkflowValidationErrorItem] | list[dict[str, Any]] | None = None


class WorkflowSummary(BaseModel):
    id: UUID
    key: str
    name: str
    description: str | None = None
    status: WorkflowStatus
    trigger_event: str | None = None
    active_version_id: UUID | None = None
    draft_version_id: UUID | None = None
    draft_revision: int
    failure_policy: str = "stop_on_failure"
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    active_version_number: int | None = None
    draft_version_number: int | None = None


class WorkflowDetail(WorkflowSummary):
    draft_definition: dict[str, Any] | None = None
    active_definition: dict[str, Any] | None = None
    draft_validation_status: WorkflowValidationStatus | None = None
    draft_validation_errors: list[WorkflowValidationErrorItem] | list[dict[str, Any]] | None = None
    recent_versions: list[WorkflowVersionSummary] = Field(default_factory=list)


class WorkflowListResponse(BaseModel):
    items: list[WorkflowSummary]
    total: int


class WorkflowVersionListResponse(BaseModel):
    items: list[WorkflowVersionSummary]
    total: int


class WorkflowStepExecutionSummary(BaseModel):
    id: UUID
    step_id: str
    step_type: str
    action_type: str | None = None
    step_index: int = 0
    status: WorkflowExecutionStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    input_summary: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None


class WorkflowExecutionSummary(BaseModel):
    id: UUID
    workflow_id: UUID
    workflow_version_id: UUID
    workflow_name: str | None = None
    platform_event_id: UUID | None = None
    execution_kind: WorkflowExecutionKind
    status: WorkflowExecutionStatus
    trigger_event: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    current_step_id: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime


class WorkflowExecutionDetail(WorkflowExecutionSummary):
    matched_conditions: dict[str, Any] | list[Any] | None = None
    input_summary: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None
    steps: list[WorkflowStepExecutionSummary] = Field(default_factory=list)


class WorkflowExecutionListResponse(BaseModel):
    items: list[WorkflowExecutionSummary]
    total: int


class WorkflowStatusChangeResponse(BaseModel):
    id: UUID
    status: WorkflowStatus
    draft_revision: int
    updated_at: datetime
    active_version_id: UUID | None = None
    draft_version_id: UUID | None = None


class WorkflowPublishResponse(WorkflowStatusChangeResponse):
    published_version_id: UUID
    published_version_number: int
    definition_hash: str | None = None


class WorkflowCloneResponse(WorkflowDetail):
    pass


class WorkflowTestRequest(BaseModel):
    mode: WorkflowTestMode = "evaluate_only"
    version_id: UUID | None = None
    synthetic_payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowTestResponse(BaseModel):
    mode: WorkflowTestMode
    valid: bool
    matched: bool | None = None
    evaluation_status: str | None = None
    planned_steps: list[dict[str, Any]] = Field(default_factory=list)
    evaluated_conditions: list[dict[str, Any]] = Field(default_factory=list)
    failed_condition_ids: list[str] = Field(default_factory=list)
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    validation_errors: list[WorkflowValidationErrorItem] = Field(default_factory=list)


class WorkflowCatalogField(BaseModel):
    name: str
    type: str
    description: str = ""
    operators: list[str] = Field(default_factory=list)
    enum_values: list[str] | None = None


class WorkflowCatalogEvent(BaseModel):
    event: str
    fields: list[WorkflowCatalogField] = Field(default_factory=list)


class WorkflowCatalogResponse(BaseModel):
    events: list[WorkflowCatalogEvent]
    action_types: list[str]
    limits: dict[str, int]
