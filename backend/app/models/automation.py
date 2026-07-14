"""Tenant automation flow definitions and execution history."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

AUTOMATION_FLOW_STATUSES = frozenset({"enabled", "paused", "disabled"})
# Keep "success" (Phase 1) — do not rename to "succeeded".
AUTOMATION_EXECUTION_STATUSES = frozenset({
    "pending",
    "running",
    "success",
    "failed",
    "skipped",
    "cancelled",
})
AUTOMATION_EXECUTION_KINDS = frozenset({"event", "manual", "retry"})
AUTOMATION_RETRY_BACKOFFS = frozenset({"fixed", "linear", "exponential"})
AUTOMATION_ERROR_CATEGORIES = frozenset({
    "validation",
    "configuration",
    "dependency",
    "transient",
    "conflict",
    "internal",
})
AUTOMATION_ACTION_TYPES = frozenset({
    "create_notification",
    "create_crm_lead",
    "update_customer_success_progress",
    "record_activity",
})

DEFAULT_MAX_RETRY_ATTEMPTS = 1
MAX_RETRY_ATTEMPTS_BOUND = 3
DEFAULT_RETRY_DELAY_SECONDS = 60
MAX_RETRY_DELAY_SECONDS = 3600

# Durable scheduler (Phase 1)
AUTOMATION_JOB_KINDS = frozenset({"automation_retry"})
AUTOMATION_JOB_STATUSES = frozenset({
    "scheduled",
    "leased",
    "running",
    "succeeded",
    "failed",
    "dead_letter",
    "cancelled",
})
AUTOMATION_JOB_TERMINAL_STATUSES = frozenset({
    "succeeded",
    "failed",
    "dead_letter",
    "cancelled",
})
DEFAULT_SCHEDULER_LEASE_SECONDS = 300
MAX_SCHEDULER_LEASE_SECONDS = 900
MAX_SCHEDULER_DELAY_SECONDS = 86400  # 24h hard cap for retry delays
MAX_LEASE_RECOVERIES = 5
DEFAULT_SCHEDULER_BATCH_SIZE = 10
DEFAULT_SCHEDULER_POLL_SECONDS = 2


class TenantAutomationFlow(Base):
    """Tenant-scoped automation flow definition (trigger + fixed action)."""

    __tablename__ = "tenant_automation_flows"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_tenant_automation_flows_tenant_key"),
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
    category: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    trigger_event: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(60), nullable=False)
    action_config: Mapped[dict] = mapped_column(JSONB(), nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="enabled", server_default="enabled", index=True,
    )
    is_system: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="false",
    )
    max_retry_attempts: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=DEFAULT_MAX_RETRY_ATTEMPTS, server_default="1",
    )
    retry_delay_seconds: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=DEFAULT_RETRY_DELAY_SECONDS, server_default="60",
    )
    retry_backoff: Mapped[str] = mapped_column(
        String(20), nullable=False, default="fixed", server_default="fixed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
    last_executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_execution_status: Mapped[str | None] = mapped_column(String(20), nullable=True)


class TenantAutomationExecution(Base):
    """Recorded automation flow execution attempt."""

    __tablename__ = "tenant_automation_executions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "automation_flow_id",
            "deduplication_key",
            name="uq_tenant_automation_executions_dedup",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    automation_flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_automation_flows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    trigger_event: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True,
    )
    execution_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="event", server_default="event",
    )
    deduplication_key: Mapped[str] = mapped_column(String(160), nullable=False)
    root_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_automation_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    retry_of_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_automation_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    retry_number: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0",
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    input_payload: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_retryable: Mapped[bool | None] = mapped_column(nullable=True)
    attempt_number: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )


class TenantAutomationJob(Base):
    """Durable scheduled automation job (PostgreSQL-backed worker queue)."""

    __tablename__ = "tenant_automation_jobs"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "deduplication_key",
            name="uq_tenant_automation_jobs_dedup",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    automation_flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_automation_flows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_automation_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    root_execution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_automation_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    job_kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="automation_retry", server_default="automation_retry",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="scheduled", server_default="scheduled", index=True,
    )
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    attempt_number: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1",
    )
    priority: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=100, server_default="100",
    )
    deduplication_key: Mapped[str] = mapped_column(String(180), nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_recovery_count: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0",
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB(), nullable=False, default=dict)
    result_payload: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(),
    )
