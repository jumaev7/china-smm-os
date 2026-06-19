"""WhatsApp Sync v1 — API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WhatsAppAccountType = Literal[
    "whatsapp_business_api",
    "whatsapp_cloud_api",
    "third_party_connector",
    "manual_import",
]
WhatsAppSyncJobStatus = Literal["pending", "running", "completed", "failed"]
WhatsAppSyncJobType = Literal[
    "contacts",
    "conversations",
    "test_connection",
    "scheduled_contacts",
    "scheduled_conversations",
]


class WhatsAppSyncAccountResponse(BaseModel):
    id: UUID
    account_name: str
    account_type: WhatsAppAccountType
    status: str
    phone_number: Optional[str] = None
    provider: Optional[str] = None
    external_account_id: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppSyncAccountsResponse(BaseModel):
    items: list[WhatsAppSyncAccountResponse]
    total: int


class WhatsAppSyncJobResponse(BaseModel):
    id: UUID
    account_id: Optional[UUID] = None
    account_name: Optional[str] = None
    job_type: str
    trigger: str
    status: WhatsAppSyncJobStatus
    stats_json: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppSyncJobsResponse(BaseModel):
    items: list[WhatsAppSyncJobResponse]
    total: int


class WhatsAppSyncStatusOverview(BaseModel):
    accounts_total: int = 0
    accounts_connected: int = 0
    last_sync_at: Optional[datetime] = None
    pending_jobs: int = 0
    failed_jobs_recent: int = 0
    adapters_available: list[str] = Field(default_factory=list)


class WhatsAppSyncContactsRequest(BaseModel):
    account_id: Optional[UUID] = None


class WhatsAppSyncConversationsRequest(BaseModel):
    account_id: Optional[UUID] = None


class WhatsAppSyncTestConnectionRequest(BaseModel):
    account_id: UUID


class WhatsAppSyncRunResponse(BaseModel):
    job_id: UUID
    status: WhatsAppSyncJobStatus
    stats: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class WhatsAppSyncTestConnectionResponse(BaseModel):
    job_id: UUID
    ok: bool
    provider: str
    message: str
    latency_ms: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
