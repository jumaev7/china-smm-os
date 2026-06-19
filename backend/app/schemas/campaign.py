from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

CampaignStatus = Literal["draft", "active", "completed", "archived"]


class CampaignCreate(BaseModel):
    client_id: UUID
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    objective: str | None = Field(None, max_length=100)
    status: CampaignStatus = "draft"
    start_date: date | None = None
    end_date: date | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    objective: str | None = Field(None, max_length=100)
    status: CampaignStatus | None = None
    start_date: date | None = None
    end_date: date | None = None


class CampaignContentItem(BaseModel):
    id: UUID
    status: str
    platforms: list[str]
    source: str
    scheduled_for: datetime | None = None
    published_at: datetime | None = None
    created_at: datetime
    media_url: str | None = None
    caption_preview: str | None = None

    model_config = {"from_attributes": True}


class CampaignStatusCounts(BaseModel):
    draft: int = 0
    review: int = 0
    approved: int = 0
    scheduled: int = 0
    published: int = 0


class CampaignListItem(BaseModel):
    id: UUID
    client_id: UUID
    name: str
    description: str | None
    objective: str | None
    status: str
    start_date: date | None
    end_date: date | None
    created_at: datetime
    updated_at: datetime
    client_name: str | None = None
    posts_count: int = 0


class CampaignListResponse(BaseModel):
    items: list[CampaignListItem]
    total: int


class CampaignDetailResponse(CampaignListItem):
    status_counts: CampaignStatusCounts
    content_items: list[CampaignContentItem] = Field(default_factory=list)


class CampaignAssignContentRequest(BaseModel):
    content_ids: list[UUID] = Field(..., min_length=1)


class CampaignAssignContentResponse(BaseModel):
    assigned: int
    campaign_id: UUID


class CampaignUnassignContentResponse(BaseModel):
    unassigned: int
    campaign_id: UUID
