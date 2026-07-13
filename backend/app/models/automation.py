"""Tenant automation flow definitions and execution history."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

AUTOMATION_FLOW_STATUSES = frozenset({"enabled", "paused", "disabled"})
AUTOMATION_EXECUTION_STATUSES = frozenset({"pending", "running", "success", "failed", "skipped"})
AUTOMATION_ACTION_TYPES = frozenset({
    "create_notification",
    "create_crm_lead",
    "update_customer_success_progress",
    "record_activity",
})


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
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    input_payload: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    result_payload: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    attempt_number: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True,
    )
