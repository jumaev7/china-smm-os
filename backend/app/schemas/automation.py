"""Automation Center API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

AutomationFlowStatus = Literal["enabled", "paused", "disabled"]
AutomationExecutionStatus = Literal["pending", "running", "success", "failed", "skipped", "cancelled"]
AutomationExecutionKind = Literal["event", "manual", "retry"]
AutomationActionType = Literal[
    "create_notification",
    "create_crm_lead",
    "update_customer_success_progress",
    "record_activity",
]
AutomationErrorCategory = Literal[
    "validation",
    "configuration",
    "dependency",
    "transient",
    "conflict",
    "internal",
]
AutomationRetryBackoff = Literal["fixed", "linear", "exponential"]


class AutomationFlowSummary(BaseModel):
    id: UUID
    key: str
    name: str
    description: str | None = None
    category: str
    trigger_event: str
    action_type: AutomationActionType
    status: AutomationFlowStatus
    is_system: bool
    enabled: bool
    max_retry_attempts: int = 1
    retry_delay_seconds: int = 60
    retry_backoff: AutomationRetryBackoff = "fixed"
    last_executed_at: datetime | None = None
    last_execution_status: AutomationExecutionStatus | None = None
    execution_count: int = 0
    success_rate: float = 0.0
    created_at: datetime
    updated_at: datetime


class AutomationFlowDetail(AutomationFlowSummary):
    action_config: dict[str, Any] = Field(default_factory=dict)
    recent_executions: list["AutomationExecutionSummary"] = Field(default_factory=list)


class AutomationFlowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class AutomationExecutionSummary(BaseModel):
    id: UUID
    automation_flow_id: UUID
    automation_name: str | None = None
    event_id: UUID
    trigger_event: str
    status: AutomationExecutionStatus
    execution_kind: AutomationExecutionKind = "event"
    root_execution_id: UUID | None = None
    retry_of_execution_id: UUID | None = None
    retry_number: int = 0
    max_retry_attempts: int | None = None
    retry_eligible: bool = False
    retry_blocked_reason: str | None = None
    is_retryable: bool | None = None
    error_category: AutomationErrorCategory | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempt_number: int = 1
    is_manual_test: bool = False
    created_at: datetime


class AutomationExecutionDetail(AutomationExecutionSummary):
    input_summary: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None
    action_type: AutomationActionType | None = None


class AutomationFlowListResponse(BaseModel):
    items: list[AutomationFlowSummary]
    total: int


class AutomationExecutionListResponse(BaseModel):
    items: list[AutomationExecutionSummary]
    total: int
    page: int
    page_size: int
    pages: int


class AutomationKpiResponse(BaseModel):
    health_score: int
    active_count: int
    paused_count: int
    disabled_count: int
    failed_flow_count: int
    total_executions_24h: int
    success_rate_overall: float
    total_flows: int
    enabled_flows: int = 0
    executions_today: int = 0
    success_count_today: int = 0
    failure_count_today: int = 0
    success_rate: float = 100.0
    retry_count_today: int = 0
    retry_success_count_today: int = 0
    partial_publish_failures_today: int = 0
    average_duration_ms: float | None = None


class AutomationStatusChangeResponse(BaseModel):
    id: UUID
    status: AutomationFlowStatus
    enabled: bool
    updated_at: datetime


class AutomationManualRunResponse(BaseModel):
    execution_id: UUID
    flow_id: UUID
    status: AutomationExecutionStatus
    is_manual_test: bool = True
    duration_ms: int | None = None
    error_message: str | None = None


class AutomationRetryResponse(BaseModel):
    execution_id: UUID
    flow_id: UUID
    status: AutomationExecutionStatus
    execution_kind: AutomationExecutionKind = "retry"
    root_execution_id: UUID
    retry_of_execution_id: UUID
    retry_number: int
    duration_ms: int | None = None
    error_message: str | None = None
    error_category: AutomationErrorCategory | None = None
