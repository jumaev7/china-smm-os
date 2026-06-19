from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.content import PLATFORMS

ContentStudioGoal = Literal[
    "Brand awareness",
    "Lead generation",
    "Product promotion",
    "Distributor recruitment",
    "Trade show announcement",
]

CONTENT_STUDIO_GOALS = (
    "Brand awareness",
    "Lead generation",
    "Product promotion",
    "Distributor recruitment",
    "Trade show announcement",
)


class ContentStudioGenerateRequest(BaseModel):
    client_id: UUID
    campaign_id: UUID | None = None
    media_asset_ids: list[UUID] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    content_count: int = Field(default=3, ge=1, le=10)
    content_goal: ContentStudioGoal = "Brand awareness"


class ContentStudioDraftItem(BaseModel):
    content_id: UUID
    title: str
    preview: str
    platforms: list[str]
    media_asset_id: UUID | None = None
    media_url: str | None = None
    status: str = "draft"


class ContentStudioGenerateResponse(BaseModel):
    drafts: list[ContentStudioDraftItem]
    generated_count: int
    demo_mode: bool = False


class ContentStudioSuggestionsRequest(BaseModel):
    client_id: UUID
    campaign_id: UUID | None = None
    media_asset_ids: list[UUID] = Field(default_factory=list)


class ContentStudioSuggestion(BaseModel):
    title: str
    angle: str
    content_goal: str
    suggested_platforms: list[str]
    rationale: str


class ContentStudioSuggestionsResponse(BaseModel):
    suggestions: list[ContentStudioSuggestion]
    demo_mode: bool = False
