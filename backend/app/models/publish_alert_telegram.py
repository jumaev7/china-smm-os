"""Tenant-scoped Telegram delivery settings and outbox for publish operator alerts."""
from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

DELIVERY_STATES = frozenset({
    "pending",
    "sending",
    "delivered",
    "retrying",
    "failed",
    "exhausted",
    "cancelled",
})

DELIVERY_CHANNELS = frozenset({"telegram"})
MESSAGE_KINDS = frozenset({"alert", "recovery", "test"})

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}

ENROLLMENT_STATUSES = frozenset({
    "pending_start",
    "candidate_received",
    "confirmed",
    "expired",
    "revoked",
    "rejected",
})
ENROLLMENT_ACTIVE_STATUSES = frozenset({"pending_start", "candidate_received"})
ENROLLMENT_PURPOSE = "operator_alert_enrollment"
ENROLLMENT_REJECTION_REASONS = frozenset({
    "not_private_chat",
    "is_bot",
    "anonymous_admin",
    "unsupported_chat_type",
    "token_invalid",
    "token_expired",
    "token_revoked",
    "token_consumed",
    "enrollment_disabled",
    "user_rejected",
    "replaced",
    "max_recipients",
})


class TenantPublishAlertTelegramSettings(Base):
    """Explicit tenant-admin recipient config for operator-alert Telegram delivery.

    Never reuse client intake groups or publish destinations. Destination must be a
    numeric chat ID present on the allowlist.
    """

    __tablename__ = "tenant_publish_alert_telegram_settings"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_publish_alert_telegram_settings_tenant"),
        Index("ix_tenant_publish_alert_tg_settings_enabled", "enabled"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false",
    )
    # Numeric Telegram chat ID only (user or group). Never a @username.
    recipient_chat_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    recipient_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Explicit allowlist of numeric chat IDs. Recipient must be listed to deliver.
    allowed_chat_ids: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    # Minimum severity to deliver: info | warning | critical
    severity_threshold: Mapped[str] = mapped_column(
        String(20), nullable=False, default="warning", server_default="warning",
    )
    # Null/empty = all alert types; otherwise selected types only
    alert_types: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    quiet_hours_enabled: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false",
    )
    quiet_hours_start: Mapped[time | None] = mapped_column(Time(), nullable=True)
    quiet_hours_end: Mapped[time | None] = mapped_column(Time(), nullable=True)
    quiet_hours_timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recovery_messages_enabled: Mapped[bool] = mapped_column(
        Boolean(), nullable=False, default=False, server_default="false",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class PublishAlertTelegramDelivery(Base):
    """Durable outbox row: one logical Telegram send per alert/recipient/channel/version."""

    __tablename__ = "publish_alert_telegram_deliveries"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_publish_alert_tg_deliveries_dedupe"),
        Index("ix_publish_alert_tg_deliveries_tenant_status", "tenant_id", "status"),
        Index("ix_publish_alert_tg_deliveries_alert", "alert_id"),
        Index(
            "ix_publish_alert_tg_deliveries_due",
            "status",
            "next_attempt_at",
            "created_at",
        ),
        Index("ix_publish_alert_tg_deliveries_lease", "lease_expires_at"),
        Index(
            "ix_publish_alert_tg_deliveries_sending_stale",
            "status",
            "lease_expires_at",
            postgresql_where=text("status = 'sending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    alert_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("publish_operator_alerts.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Stable uniqueness: alert|recipient|channel|alert_version|message_kind
    dedupe_key: Mapped[str] = mapped_column(String(420), nullable=False)
    channel: Mapped[str] = mapped_column(
        String(20), nullable=False, default="telegram", server_default="telegram",
    )
    message_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="alert", server_default="alert",
    )
    alert_version: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=1, server_default="1",
    )
    recipient_chat_id: Mapped[int] = mapped_column(BigInteger(), nullable=False)
    recipient_label: Mapped[str | None] = mapped_column(String(120), nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True,
    )
    attempt_number: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=0, server_default="0",
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer(), nullable=False, default=8, server_default="8",
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(String(480), nullable=True)

    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Safe snapshot for message body (no tokens / raw provider payloads)
    payload_snapshot: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class PublishAlertTelegramEnrollment(Base):
    """Short-lived, single-use operator-alert Telegram recipient enrollment.

    Stores only a hash of the deep-link token. Numeric chat IDs are internal;
    API responses expose masked IDs only. Enrollment never enables delivery.
    """

    __tablename__ = "publish_alert_telegram_enrollments"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_publish_alert_tg_enroll_token_hash"),
        Index("ix_publish_alert_tg_enroll_tenant_status", "tenant_id", "status"),
        Index("ix_publish_alert_tg_enroll_expires_at", "expires_at"),
        Index(
            "ix_publish_alert_tg_enroll_source_update",
            "source_update_id",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    created_by_admin_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    purpose: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=ENROLLMENT_PURPOSE,
        server_default=ENROLLMENT_PURPOSE,
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending_start", server_default="pending_start", index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    telegram_user_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    telegram_chat_id_masked: Mapped[str | None] = mapped_column(String(32), nullable=True)
    telegram_display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telegram_chat_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_update_id: Mapped[int | None] = mapped_column(BigInteger(), nullable=True)
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejection_reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )
