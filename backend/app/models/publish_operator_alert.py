"""Tenant-scoped operator alerts for publishing failures and recovery."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ALERT_TYPES = frozenset({
    "operator_review",
    "exhausted",
    "terminal_failure",
    "stale_in_progress",
    "recovery",
    "repeated_failure",
})
ALERT_STATES = frozenset({"open", "acknowledged", "resolved"})
ALERT_SEVERITIES = frozenset({"warning", "critical", "info"})

FAILURE_ALERT_TYPES = frozenset({
    "operator_review",
    "exhausted",
    "terminal_failure",
    "stale_in_progress",
    "repeated_failure",
})


class PublishOperatorAlert(Base):
    """Deduplicated publishing ops incident visible to tenant administrators."""

    __tablename__ = "publish_operator_alerts"
    __table_args__ = (
        Index("ix_publish_operator_alerts_tenant_state", "tenant_id", "state"),
        Index("ix_publish_operator_alerts_tenant_severity", "tenant_id", "severity"),
        Index("ix_publish_operator_alerts_tenant_platform", "tenant_id", "platform"),
        Index("ix_publish_operator_alerts_tenant_client", "tenant_id", "client_id"),
        Index("ix_publish_operator_alerts_tenant_latest", "tenant_id", "latest_occurred_at"),
        Index(
            "uq_publish_operator_alerts_open_dedupe",
            "tenant_id",
            "dedupe_key",
            unique=True,
            postgresql_where=text("state IN ('open', 'acknowledged')"),
        ),
        Index(
            "ix_publish_operator_alerts_open_destination",
            "tenant_id",
            "content_id",
            "platform",
            "account_id",
            postgresql_where=text("state IN ('open', 'acknowledged')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    dedupe_key: Mapped[str] = mapped_column(String(320), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open", index=True,
    )
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="warning", server_default="warning", index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text(), nullable=True)

    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="SET NULL"), nullable=True,
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True,
    )
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("publish_attempts.id", ondelete="SET NULL"), nullable=True, index=True,
    )
    platform: Mapped[str | None] = mapped_column(String(20), nullable=True)
    account_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    attempt_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    attempt_number: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text(), nullable=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    occurrence_count: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1",
    )
    first_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    resolve_note: Mapped[str | None] = mapped_column(Text(), nullable=True)
    resolved_by_system: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false",
    )

    action_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    context: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_delivery_channel: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_delivery_error: Mapped[str | None] = mapped_column(String(480), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
