"""Versioned tenant workflow definitions and execution history (Option A).

Simple one-trigger/one-action automations remain on tenant_automation_flows.
This module stores multi-step workflow definitions separately.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

WORKFLOW_STATUSES = frozenset({"draft", "published", "paused", "archived"})
WORKFLOW_VERSION_STATES = frozenset({"draft", "published", "superseded"})
WORKFLOW_VALIDATION_STATUSES = frozenset({"pending", "valid", "invalid"})
WORKFLOW_EXECUTION_STATUSES = frozenset({
    "pending",
    "running",
    "success",
    "failed",
    "skipped",
    "cancelled",
})
WORKFLOW_EXECUTION_KINDS = frozenset({"event", "manual", "test"})
WORKFLOW_STEP_STATUSES = frozenset({
    "pending",
    "running",
    "success",
    "failed",
    "skipped",
    "cancelled",
})
WORKFLOW_FAILURE_POLICIES = frozenset({"stop_on_failure"})

# Definition limits (Phase 1)
WORKFLOW_SCHEMA_VERSION = 1
MAX_WORKFLOW_STEPS = 20
MAX_CONDITION_DEPTH = 4
MAX_TOTAL_CONDITIONS = 30
MAX_CONDITIONS_PER_GROUP = 15
MAX_CONDITION_STRING_LENGTH = 500
MAX_CONDITION_LIST_SIZE = 50
MAX_WORKFLOW_NAME_LENGTH = 255
MAX_WORKFLOW_KEY_LENGTH = 120

# Supported Phase 1 step types — branch steps deferred (no cycles / bounded depth complexity).
WORKFLOW_STEP_TYPES = frozenset({"action"})


class TenantWorkflow(Base):
    """Stable workflow identity with pointers to draft/active published versions."""

    __tablename__ = "tenant_workflows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_workflows_tenant_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True,
    )
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_workflow_versions.id", ondelete="SET NULL", use_alter=True, name="fk_tenant_workflows_active_version"),
        nullable=True,
    )
    draft_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_workflow_versions.id", ondelete="SET NULL", use_alter=True, name="fk_tenant_workflows_draft_version"),
        nullable=True,
    )
    draft_revision: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1",
    )
    trigger_event: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    failure_policy: Mapped[str] = mapped_column(
        String(40), nullable=False, default="stop_on_failure", server_default="stop_on_failure",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantWorkflowVersion(Base):
    """Immutable published (or mutable draft) workflow definition snapshot."""

    __tablename__ = "tenant_workflow_versions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_id",
            "version_number",
            name="uq_tenant_workflow_versions_workflow_number",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer(), nullable=False)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft", server_default="draft", index=True,
    )
    definition: Mapped[dict] = mapped_column(JSONB(), nullable=False, default=dict)
    definition_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending",
    )
    validation_errors: Mapped[list | dict | None] = mapped_column(JSONB(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TenantWorkflowExecution(Base):
    """Recorded workflow run for an event or test."""

    __tablename__ = "tenant_workflow_executions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workflow_id",
            "deduplication_key",
            name="uq_tenant_workflow_executions_dedup",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_workflow_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    execution_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="event", server_default="event",
    )
    deduplication_key: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True,
    )
    trigger_event: Mapped[str] = mapped_column(String(80), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    matched_conditions: Mapped[dict | list | None] = mapped_column(JSONB(), nullable=True)
    current_step_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    input_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )


class TenantWorkflowStepExecution(Base):
    """Per-step outcome within a workflow execution."""

    __tablename__ = "tenant_workflow_step_executions"
    __table_args__ = (
        UniqueConstraint(
            "workflow_execution_id",
            "step_id",
            name="uq_tenant_workflow_step_executions_exec_step",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    workflow_execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_id: Mapped[str] = mapped_column(String(80), nullable=False)
    step_type: Mapped[str] = mapped_column(String(40), nullable=False)
    action_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    step_index: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    input_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    result_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
