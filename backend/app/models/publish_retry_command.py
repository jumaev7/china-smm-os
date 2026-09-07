"""Durable operator publish-retry command intent (Phase 3C.1B).

Infrastructure only: rows represent retry intent and forensic lineage.
Creating a command must not publish, claim provider writes, or create attempts.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Future worker state machine. provider_write_started is distinct from claimed.
RETRY_COMMAND_STATUSES = frozenset({
    "pending",
    "claimed",
    "provider_write_started",
    "succeeded",
    "failed",
    "ambiguous",
    "blocked",
    "superseded",
    "cancelled",
})

RETRY_COMMAND_ACTIVE_STATUSES = frozenset({
    "pending",
    "claimed",
    "provider_write_started",
})

RETRY_COMMAND_TERMINAL_STATUSES = frozenset({
    "succeeded",
    "failed",
    "ambiguous",
    "blocked",
    "superseded",
    "cancelled",
})

# Optional forensic refinement once a worker performs provider I/O (3C.1C+).
# Nullable at create time; status remains the primary lifecycle field.
RETRY_COMMAND_PROVIDER_OUTCOMES = frozenset({
    "known_success",
    "known_failure",
    "ambiguous",
    "superseded",
    "blocked",
})

RETRY_COMMAND_SOURCES = frozenset({
    "workspace",
    "admin",
    "api",
    "system",
})


class PublishRetryCommand(Base):
    """Tenant-scoped durable retry intent. No provider I/O in 3C.1B."""

    __tablename__ = "publish_retry_commands"
    __table_args__ = (
        Index("ix_publish_retry_commands_tenant_status", "tenant_id", "status"),
        Index("ix_publish_retry_commands_tenant_content", "tenant_id", "content_id"),
        Index("ix_publish_retry_commands_original_attempt", "original_attempt_id"),
        Index("ix_publish_retry_commands_correlation", "correlation_id"),
        Index(
            "uq_publish_retry_commands_active_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'claimed', 'provider_write_started')"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("publish_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    resulting_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("publish_attempts.id", ondelete="SET NULL"),
        nullable=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    publishing_account_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("publishing_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    publish_version: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_key: Mapped[str] = mapped_column(String(120), nullable=False)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True,
    )
    requested_source: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(420), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
    )
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    provider_outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    provider_write_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
