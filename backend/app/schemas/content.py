from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime, date
from typing import Optional, List, Literal


# ─── Media ───────────────────────────────────────────────────────────────────

class MediaFileResponse(BaseModel):
    id: UUID
    client_id: UUID
    original_filename: str
    file_type: str
    mime_type: str
    storage_path: str
    thumbnail_path: Optional[str]
    file_size: int
    url: str  # computed by service
    uploaded_at: datetime

    model_config = {"from_attributes": True}


# ─── Content ─────────────────────────────────────────────────────────────────

PLATFORMS = ["instagram", "facebook", "tiktok", "telegram", "linkedin"]
STATUSES = [
    "new", "needs_review", "needs_caption", "rejected",
    "draft", "ready", "ready_for_approval", "approved", "scheduled",
    "publishing", "published", "partial_failed", "failed", "changes_requested",
]


class ContentCreate(BaseModel):
    client_id: UUID
    media_file_id: Optional[UUID] = None
    platforms: List[str] = Field(default_factory=list)
    internal_notes: Optional[str] = None
    source: str = "manual"
    scheduled_for: Optional[datetime] = None


class ContentUpdate(BaseModel):
    media_file_id: Optional[UUID] = None
    platforms: Optional[List[str]] = None
    status: Optional[str] = None
    caption_short_ru: Optional[str] = None
    caption_short_uz: Optional[str] = None
    caption_short_en: Optional[str] = None
    caption_long_ru: Optional[str] = None
    caption_long_uz: Optional[str] = None
    caption_long_en: Optional[str] = None
    hashtags: Optional[str] = None
    internal_notes: Optional[str] = None
    context_ai_override: Optional[str] = None
    content_classification: Optional[str] = None
    telegram_original_caption: Optional[str] = None
    telegram_forward_from: Optional[str] = None
    suggestions_json: Optional[str] = None
    quality_warnings_json: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    linked_sales_lead_id: Optional[UUID] = None
    linked_buyer_id: Optional[UUID] = None
    linked_sales_deal_id: Optional[UUID] = None


class SelectedMediaItem(BaseModel):
    ordinal: int
    media_file_id: str
    media_type: str
    url: str
    text: Optional[str] = None


class ContentPlanContext(BaseModel):
    plan_item_id: UUID
    plan_id: UUID
    plan_title: str
    theme: str
    goal: str
    content_type: str
    planned_date: date
    ai_generated: bool = False


class ContentResponse(BaseModel):
    id: UUID
    client_id: UUID
    media_file_id: Optional[UUID]
    platforms: List[str]
    status: str
    source: str = "manual"
    telegram_group_title: Optional[str] = None
    telegram_message_id: Optional[int] = None
    telegram_excluded: bool = False
    telegram_instructions: Optional[str] = None
    context_ai_override: Optional[str] = None
    context_ai_detected: Optional[str] = None
    context_ai_confidence: Optional[float] = None
    content_classification: Optional[str] = None
    telegram_original_caption: Optional[str] = None
    telegram_forward_from: Optional[str] = None
    suggestions: Optional[dict] = None
    quality_warnings: Optional[List[dict]] = None
    source_badge: Optional[str] = None
    telegram_buffer_refs: Optional[str] = None
    selected_media: Optional[List[SelectedMediaItem]] = None
    caption_short_ru: Optional[str]
    caption_short_uz: Optional[str]
    caption_short_en: Optional[str]
    caption_long_ru: Optional[str]
    caption_long_uz: Optional[str]
    caption_long_en: Optional[str]
    hashtags: Optional[str]
    internal_notes: Optional[str]
    scheduled_for: Optional[datetime]
    approved_at: Optional[datetime]
    published_at: Optional[datetime]
    client_approved_at: Optional[datetime] = None
    client_review_feedback: Optional[str] = None
    client_review_status: Optional[Literal["pending", "approved", "changes_requested"]] = None
    client_review_preview_sent_at: Optional[datetime] = None
    client_review_preview_error: Optional[str] = None
    review_token: Optional[str] = None
    campaign_id: Optional[UUID] = None
    parent_content_id: Optional[UUID] = None
    parent_media_asset_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    media_url: Optional[str] = None
    media_file_type: Optional[str] = None  # image | video
    subtitle_url: Optional[str] = None
    subtitle_url_cn: Optional[str] = None
    subtitle_url_ru: Optional[str] = None
    subtitle_url_uz: Optional[str] = None
    subtitle_url_en: Optional[str] = None
    subtitled_video_url_cn: Optional[str] = None
    subtitled_video_url_ru: Optional[str] = None
    subtitled_video_url_uz: Optional[str] = None
    subtitled_video_url_en: Optional[str] = None
    dubbed_video_url_ru: Optional[str] = None
    dubbed_video_url_uz: Optional[str] = None
    dubbed_video_url_en: Optional[str] = None
    dubbed_video_extended_url_ru: Optional[str] = None
    dubbed_video_extended_url_uz: Optional[str] = None
    dubbed_video_extended_url_en: Optional[str] = None
    final_video_url_cn: Optional[str] = None
    final_video_url_ru: Optional[str] = None
    final_video_url_uz: Optional[str] = None
    final_video_url_en: Optional[str] = None
    final_export_urls: Optional[dict[str, str]] = None
    generated_final_video_url: Optional[str] = None
    content_plan_context: Optional[ContentPlanContext] = None
    media_request_sent_at: Optional[datetime] = None
    media_request_message: Optional[str] = None
    media_request_status: Optional[Literal["requested", "fulfilled", "skipped"]] = None
    media_request_format: Optional[Literal["photo", "video", "carousel", "story", "any"]] = None
    linked_sales_lead_id: Optional[UUID] = None
    linked_buyer_id: Optional[UUID] = None
    linked_sales_deal_id: Optional[UUID] = None

    model_config = {"from_attributes": True}


class MediaRequestBody(BaseModel):
    format: Literal["photo", "video", "carousel", "story", "any"] = "any"


class MediaRequestResponse(BaseModel):
    ok: bool
    message: str
    media_request_status: str
    media_request_sent_at: datetime
    media_request_message: str
    media_request_format: str


class BurnSubtitlesRequest(BaseModel):
    lang: Literal["cn", "ru", "uz", "en"] = "ru"


class VoiceoverRequest(BaseModel):
    lang: Literal["ru", "uz", "en"] = "ru"
    mode: Literal["fitted", "extended"] = "fitted"


class FinalVideoRequest(BaseModel):
    subtitle_lang: Literal["cn", "ru", "uz", "en"] = "ru"
    voice_lang: Literal["ru", "uz", "en"] = "ru"
    voice_mode: Literal["fitted", "extended"] = "fitted"


class ContentListResponse(BaseModel):
    items: List[ContentResponse]
    total: int


class ReadinessItem(BaseModel):
    id: str
    label: str
    ready: bool
    critical: bool
    message: Optional[str] = None


class ContentReadinessResponse(BaseModel):
    ready: bool
    ready_for_approve: bool
    ready_for_schedule: bool
    items: List[ReadinessItem]


class PublishSafetyError(BaseModel):
    id: str
    message: str
    critical: bool = True


class PublishSafetyResponse(BaseModel):
    passed: bool
    errors: List[PublishSafetyError]
    message: Optional[str] = None
    mode: Optional[str] = None


class PlatformPublishResult(BaseModel):
    platform: str
    success: bool
    mock: bool = True
    platform_post_id: Optional[str] = None
    post_url: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None
    account_id: Optional[str] = None
    account_name: Optional[str] = None


class PublishContentResponse(BaseModel):
    content_id: UUID
    status: str
    previous_status: str
    published_at: Optional[datetime] = None
    all_success: bool
    results: List[PlatformPublishResult]
    test: bool = False


class ReviewLinkResponse(BaseModel):
    token: str
    url: str


class ClientReviewPreviewResponse(BaseModel):
    sent: bool
    sent_at: Optional[datetime] = None
    error: Optional[str] = None
    skipped: bool = False
    reason: Optional[str] = None


class PublicReviewCaption(BaseModel):
    lang: str
    short: Optional[str] = None
    long: Optional[str] = None


class PublicReviewResponse(BaseModel):
    company_name: str
    status: str
    media_url: Optional[str] = None
    media_file_type: Optional[str] = None
    selected_media: Optional[List[SelectedMediaItem]] = None
    captions: List[PublicReviewCaption] = Field(default_factory=list)
    hashtags: Optional[str] = None
    final_video_url: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    client_approved_at: Optional[datetime] = None
    client_review_feedback: Optional[str] = None
    can_approve: bool = True
    can_request_changes: bool = True


# ─── Calendar ─────────────────────────────────────────────────────────────────

class CalendarEntryCreate(BaseModel):
    content_item_id: UUID
    scheduled_date: date
    time_slot: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    platforms: List[str] = Field(default_factory=list)
    note: Optional[str] = None


class CalendarEntryUpdate(BaseModel):
    scheduled_date: Optional[date] = None
    time_slot: Optional[str] = None
    scheduled_for: Optional[datetime] = None
    platforms: Optional[List[str]] = None
    note: Optional[str] = None


# Nested content info for rich calendar response
class CalendarContentInfo(BaseModel):
    id: UUID
    client_id: UUID
    status: str
    platforms: List[str]
    caption_short_ru: Optional[str]
    caption_short_en: Optional[str]
    caption_short_uz: Optional[str]
    media_url: Optional[str] = None

    model_config = {"from_attributes": True}


class CalendarClientInfo(BaseModel):
    id: UUID
    company_name: str

    model_config = {"from_attributes": True}


class CalendarEntryResponse(BaseModel):
    id: UUID
    content_item_id: UUID
    scheduled_date: date
    time_slot: Optional[str]
    platforms: List[str]
    note: Optional[str]
    created_at: datetime
    # Rich nested data
    content_item: Optional[CalendarContentInfo] = None
    client: Optional[CalendarClientInfo] = None

    model_config = {"from_attributes": True}


# ─── AI Generation ────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    content_item_id: UUID
    source_language: Optional[str] = Field("zh", description="Language of the source text: zh, en, ru, ko, ja")
    source_text: Optional[str] = Field(None, description="Raw text from client (in source language)")
    context_hint: Optional[str] = Field(None, description="Extra context for AI e.g. 'Ramadan promotion'")


class GeneratedContent(BaseModel):
    caption_short_ru: str
    caption_short_uz: str
    caption_short_en: str
    caption_long_ru: str
    caption_long_uz: str
    caption_long_en: str
    hashtags: str
