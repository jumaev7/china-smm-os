from datetime import date, datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

PublishMode = Literal["test_publish", "manual_publish", "scheduled_publish"]

PLATFORMS = ["telegram", "facebook", "instagram", "tiktok", "linkedin"]
ACCOUNT_STATUSES = ["connected", "disconnected", "mock"]

MOCK_ACCOUNT_LABELS = {
    "telegram": "Telegram Channel Mock",
    "instagram": "Instagram Mock",
    "facebook": "Facebook Page Mock",
    "tiktok": "TikTok Mock",
    "linkedin": "LinkedIn Mock",
}


class PublishingAccountCreate(BaseModel):
    platform: str
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    access_token_encrypted: Optional[str] = None
    status: str = "mock"
    mock: bool = False


class PublishingAccountUpdate(BaseModel):
    account_name: Optional[str] = None
    account_id: Optional[str] = None
    access_token_encrypted: Optional[str] = None
    status: Optional[str] = None


class PublishingAccountResponse(BaseModel):
    id: UUID
    platform: str
    account_name: str
    account_id: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PublishingAccountListResponse(BaseModel):
    items: List[PublishingAccountResponse]
    total: int


class PublishContentRequest(BaseModel):
    platforms: Optional[List[str]] = None
    account_id: Optional[UUID] = None
    test: bool = False
    mode: Optional[PublishMode] = None


class PublishAttemptResponse(BaseModel):
    id: UUID
    content_id: UUID
    platform: str
    account_id: Optional[UUID] = None
    account_name: Optional[str] = None
    status: str
    response: Optional[str] = None
    error: Optional[str] = None
    platform_post_id: Optional[str] = None
    post_url: Optional[str] = None
    created_at: datetime


class PublishAttemptListResponse(BaseModel):
    items: List[PublishAttemptResponse]
    total: int


class ScheduledPublishDebugItem(BaseModel):
    id: UUID
    status: str
    scheduled_for: Optional[datetime] = None
    utc_time: Optional[str] = None
    local_time: Optional[str] = None
    current_time: datetime
    is_due: bool
    approved_at: Optional[datetime] = None
    admin_approved: bool
    client_review_status: Optional[str] = None
    client_approved: bool
    platforms: List[str]
    platforms_count: int
    publishing_accounts_available: dict[str, List[str]]
    selected_accounts: dict[str, Optional[str]]
    has_media: bool
    has_caption: bool
    skip_reason: Optional[str] = None


class ScheduledPublishDebugResponse(BaseModel):
    current_time: datetime
    due_count: int
    items: List[ScheduledPublishDebugItem]


class PublishingCalendarItem(BaseModel):
    id: UUID
    title: str
    client_id: UUID
    company_name: str
    status: str
    scheduled_for: Optional[datetime] = None
    published_at: Optional[datetime] = None
    platforms: List[str] = Field(default_factory=list)


class PublishingCalendarResponse(BaseModel):
    items: List[PublishingCalendarItem]
    total: int
    from_date: date
    to_date: date


class PublishingQueueItem(BaseModel):
    id: UUID
    client_id: UUID
    company_name: str
    status: str
    scheduled_for: Optional[datetime] = None
    local_time: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    client_review_status: Optional[str] = None
    admin_approved: bool
    safety_status: str
    block_reason: Optional[str] = None
    block_reason_label: Optional[str] = None
    queue_category: str
    is_due: bool


class PublishingQueueResponse(BaseModel):
    current_time: datetime
    items: List[PublishingQueueItem]
    total: int
    counts: dict[str, int] = Field(default_factory=dict)


class PublishingQueueActionResponse(BaseModel):
    ok: bool
    message: str
    content_id: UUID
    status: Optional[str] = None
    safety_status: Optional[str] = None
    block_reason: Optional[str] = None
