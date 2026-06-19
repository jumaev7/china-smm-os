"""WeChat Sync v1 — API schemas."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

WeChatAccountType = Literal["personal_wechat", "wecom", "official_account"]
WeChatSyncJobStatus = Literal["pending", "running", "completed", "failed"]
WeChatSyncJobType = Literal[
    "contacts",
    "conversations",
    "test_connection",
    "scheduled_contacts",
    "scheduled_conversations",
]


class WeChatSyncAccountResponse(BaseModel):
    id: UUID
    account_name: str
    account_type: WeChatAccountType
    status: str
    provider: Optional[str] = None
    external_account_id: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WeChatSyncAccountsResponse(BaseModel):
    items: list[WeChatSyncAccountResponse]
    total: int


class WeChatSyncJobResponse(BaseModel):
    id: UUID
    account_id: Optional[UUID] = None
    account_name: Optional[str] = None
    job_type: str
    trigger: str
    status: WeChatSyncJobStatus
    stats_json: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class WeChatSyncJobsResponse(BaseModel):
    items: list[WeChatSyncJobResponse]
    total: int


class WeChatSyncStatusOverview(BaseModel):
    accounts_total: int = 0
    accounts_connected: int = 0
    last_sync_at: Optional[datetime] = None
    pending_jobs: int = 0
    failed_jobs_recent: int = 0
    adapters_available: list[str] = Field(default_factory=list)


class WeChatSyncContactsRequest(BaseModel):
    account_id: Optional[UUID] = None


class WeChatSyncConversationsRequest(BaseModel):
    account_id: Optional[UUID] = None


class WeChatSyncTestConnectionRequest(BaseModel):
    account_id: UUID


class WeChatSyncRunResponse(BaseModel):
    job_id: UUID
    status: WeChatSyncJobStatus
    stats: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class WeChatSyncTestConnectionResponse(BaseModel):
    job_id: UUID
    ok: bool
    provider: str
    message: str
    latency_ms: int = 0
    details: dict[str, Any] = Field(default_factory=dict)
