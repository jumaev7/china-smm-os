"""Pydantic schemas for publish operator alerts."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

AlertType = Literal[
    "operator_review",
    "exhausted",
    "terminal_failure",
    "stale_in_progress",
    "recovery",
    "repeated_failure",
]
AlertState = Literal["open", "acknowledged", "resolved"]
AlertSeverity = Literal["warning", "critical", "info"]


class PublishAlertItem(BaseModel):
    id: UUID
    tenant_id: UUID
    dedupe_key: str
    alert_type: AlertType
    state: AlertState
    severity: AlertSeverity
    title: str
    body: str | None = None
    client_id: UUID | None = None
    content_id: UUID | None = None
    account_id: UUID | None = None
    attempt_id: UUID | None = None
    platform: str | None = None
    account_name: str | None = None
    company_name: str | None = None
    attempt_status: str | None = None
    attempt_number: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    next_retry_at: datetime | None = None
    occurrence_count: int = 1
    first_occurred_at: datetime
    latest_occurred_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None
    resolve_note: str | None = None
    resolved_by_system: bool = False
    action_url: str | None = None
    content_url: str | None = None
    queue_url: str | None = None
    attempts_url: str | None = None
    context: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime


class PublishAlertListResponse(BaseModel):
    items: list[PublishAlertItem]
    total: int
    page: int
    page_size: int
    pages: int


class PublishAlertCountsResponse(BaseModel):
    open_count: int = 0
    acknowledged_count: int = 0
    resolved_count: int = 0
    critical_open_count: int = 0
    warning_open_count: int = 0
    info_open_count: int = 0
    unread_open_count: int = 0


class PublishAlertAcknowledgeResponse(BaseModel):
    id: UUID
    state: AlertState
    acknowledged_at: datetime | None = None


class PublishAlertResolveRequest(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class PublishAlertResolveResponse(BaseModel):
    id: UUID
    state: AlertState
    resolved_at: datetime | None = None
    resolve_note: str | None = None


# ── Telegram delivery (outbound; distinct from in-app alerts) ──────────────


class TelegramAlertSettingsUpdate(BaseModel):
    enabled: bool | None = None
    recipient_chat_id: int | str | None = None
    recipient_label: str | None = Field(default=None, max_length=120)
    allowed_chat_ids: list[int | str] | None = None
    severity_threshold: AlertSeverity | None = None
    alert_types: list[AlertType] | None = None
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: str | None = Field(default=None, description="HH:MM")
    quiet_hours_end: str | None = Field(default=None, description="HH:MM")
    quiet_hours_timezone: str | None = Field(default=None, max_length=64)
    recovery_messages_enabled: bool | None = None


class TelegramAlertSettingsResponse(BaseModel):
    configured: bool = False
    enabled: bool = False
    global_telegram_enabled: bool = False
    delivery_effective: bool = False
    recipient_chat_id: int | None = None
    recipient_chat_id_masked: str | None = None
    recipient_label: str | None = None
    allowed_chat_ids: list[int] = Field(default_factory=list)
    allowed_chat_ids_masked: list[str] = Field(default_factory=list)
    severity_threshold: str = "warning"
    alert_types: list[str] | None = None
    quiet_hours_enabled: bool = False
    quiet_hours_start: str | None = None
    quiet_hours_end: str | None = None
    quiet_hours_timezone: str | None = None
    recovery_messages_enabled: bool = False
    updated_at: str | None = None


class TelegramDeliveryItem(BaseModel):
    id: str
    tenant_id: str
    alert_id: str
    status: str
    message_kind: str
    channel: str
    alert_version: int = 1
    recipient_chat_id: int | None = None
    recipient_chat_id_masked: str | None = None
    recipient_label: str | None = None
    attempt_number: int = 0
    max_attempts: int = 8
    next_attempt_at: str | None = None
    telegram_message_id: int | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    delivered_at: str | None = None
    cancelled_at: str | None = None
    created_at: str | None = None


class TelegramDeliveryListResponse(BaseModel):
    items: list[TelegramDeliveryItem]
    total: int
    page: int
    page_size: int


class TelegramTestSendRequest(BaseModel):
    confirm: bool = False


# ── Operator Telegram enrollment (self-serve recipient connect) ────────────


EnrollmentStatus = Literal[
    "pending_start",
    "candidate_received",
    "confirmed",
    "expired",
    "revoked",
    "rejected",
]


class TelegramEnrollmentResponse(BaseModel):
    id: str | None = None
    tenant_id: str | None = None
    status: EnrollmentStatus | None = None
    purpose: str | None = None
    expires_at: str | None = None
    consumed_at: str | None = None
    telegram_chat_id_masked: str | None = None
    telegram_display_name: str | None = None
    telegram_username: str | None = None
    telegram_chat_type: str | None = None
    bot_username: str | None = None
    rejection_reason_code: str | None = None
    confirmed_at: str | None = None
    revoked_at: str | None = None
    rejected_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    deep_link: str | None = None
    start_token: str | None = None
    enrollment_enabled: bool = False
    max_confirmed_recipients: int = 1
    poll_interval_seconds: float = 3.0
    delivery_still_disabled_note: str | None = None


class TelegramEnrollmentConfirmRequest(BaseModel):
    replace_existing: bool = False


class TelegramEnrollmentConfirmResponse(BaseModel):
    enrollment: dict[str, Any]
    settings: dict[str, Any]
    idempotent: bool = False
    delivery_enabled: bool = False
    tenant_delivery_flag: bool | None = None


class TelegramRecipientItem(BaseModel):
    id: str
    tenant_id: str
    status: str
    telegram_chat_id: int | None = None
    telegram_chat_id_masked: str | None = None
    telegram_display_name: str | None = None
    telegram_username: str | None = None
    confirmed_at: str | None = None
    confirmed_by: str | None = None
    revoked_at: str | None = None
    created_at: str | None = None


class TelegramRecipientListResponse(BaseModel):
    items: list[TelegramRecipientItem]
    total: int
    page: int
    page_size: int
    pages: int
    max_confirmed_recipients: int = 1


class TelegramRecipientRemoveResponse(BaseModel):
    removed: bool = True
    enrollment: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None
