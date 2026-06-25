"""Admin tenant operations / onboarding readiness schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class TenantOpsCheckItem(BaseModel):
    id: str
    label: str
    ok: bool
    detail: Optional[str] = None
    critical: bool = True


class TenantOpsClientTelegram(BaseModel):
    client_id: UUID
    company_name: str
    is_placeholder: bool
    telegram_group_id: Optional[str] = None
    telegram_group_title: Optional[str] = None
    telegram_workflow_mode: Optional[str] = None
    telegram_publish_chat_id: Optional[str] = None
    intake_linked: bool
    duplicate_group_warning: bool = False
    duplicate_client_ids: list[str] = Field(default_factory=list)
    last_intake_at: Optional[datetime] = None


class TenantOpsTelegramHealth(BaseModel):
    bot_configured: bool
    ingestion_enabled: bool
    webhook_url: Optional[str] = None
    webhook_pending_updates: Optional[int] = None
    webhook_last_error: Optional[str] = None


class TenantOperationsResponse(BaseModel):
    tenant_id: UUID
    company_name: str
    tenant_status: str
    plan: str
    readiness: str  # ready | onboarding_incomplete
    checks: list[TenantOpsCheckItem]
    blockers: list[str]
    owner_email: Optional[str] = None
    owner_has_password: bool = False
    client_count: int = 0
    primary_client_id: Optional[UUID] = None
    content_count: int = 0
    telegram_content_count: int = 0
    subscription_status: Optional[str] = None
    has_publishing_destination: bool = False
    connected_publishing_accounts: int = 0
    clients_telegram: list[TenantOpsClientTelegram] = Field(default_factory=list)
    telegram_health: TenantOpsTelegramHealth
    next_steps: list[str] = Field(default_factory=list)
