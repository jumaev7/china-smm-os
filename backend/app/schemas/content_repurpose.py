from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

RepurposeSourceType = Literal["media_asset", "content_item", "campaign"]

RepurposeOutputFormat = Literal[
    "instagram_post",
    "facebook_post",
    "linkedin_post",
    "telegram_post",
    "short_video_script",
    "carousel_post",
    "distributor_recruitment_post",
]

REPURPOSE_OUTPUT_FORMATS = (
    "instagram_post",
    "facebook_post",
    "linkedin_post",
    "telegram_post",
    "short_video_script",
    "carousel_post",
    "distributor_recruitment_post",
)

REPURPOSE_FORMAT_LABELS: dict[str, str] = {
    "instagram_post": "Instagram Post",
    "facebook_post": "Facebook Post",
    "linkedin_post": "LinkedIn Post",
    "telegram_post": "Telegram Post",
    "short_video_script": "Short Video Script",
    "carousel_post": "Carousel Post",
    "distributor_recruitment_post": "Distributor Recruitment Post",
}


class ContentRepurposeGenerateRequest(BaseModel):
    client_id: UUID
    source_type: RepurposeSourceType
    source_id: UUID
    output_formats: list[RepurposeOutputFormat] = Field(min_length=1, max_length=7)


class ContentRepurposeDraftItem(BaseModel):
    content_id: UUID
    output_format: str
    format_label: str
    preview: str
    platforms: list[str]
    media_asset_id: UUID | None = None
    media_url: str | None = None
    parent_content_id: UUID | None = None
    parent_media_asset_id: UUID | None = None
    status: str = "draft"


class ContentRepurposeGenerateResponse(BaseModel):
    drafts: list[ContentRepurposeDraftItem]
    generated_count: int
    demo_mode: bool = False


class ContentRepurposeSuggestionsRequest(BaseModel):
    client_id: UUID
    source_type: RepurposeSourceType
    source_id: UUID


class ContentRepurposeFormatSuggestion(BaseModel):
    output_format: str
    format_label: str
    rationale: str
    priority: int = 1


class ContentRepurposeSuggestionsResponse(BaseModel):
    suggestions: list[ContentRepurposeFormatSuggestion]
    demo_mode: bool = False
