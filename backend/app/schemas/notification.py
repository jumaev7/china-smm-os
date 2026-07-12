"""Pydantic schemas for tenant Notification Center API."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

NotificationCategory = Literal[
    "publishing",
    "crm",
    "integrations",
    "automation",
    "journey",
    "billing",
    "security",
    "platform",
]
NotificationSeverity = Literal["info", "success", "warning", "error", "critical"]


class NotificationItem(BaseModel):
    id: UUID
    event_id: UUID
    event_type: str
    title: str
    message: str | None = None
    category: NotificationCategory
    severity: NotificationSeverity
    is_read: bool
    read_at: datetime | None = None
    action_url: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationItem]
    total: int
    page: int
    page_size: int
    pages: int


class NotificationUnreadCountResponse(BaseModel):
    unread_count: int


class NotificationMarkReadResponse(BaseModel):
    id: UUID
    is_read: bool
    read_at: datetime | None = None


class NotificationMarkAllReadResponse(BaseModel):
    updated_count: int


class NotificationDeleteResponse(BaseModel):
    id: UUID
    deleted: bool = True
