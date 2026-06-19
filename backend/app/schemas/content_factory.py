from datetime import datetime
from typing import List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field

FactoryStatus = Literal["draft", "generated", "failed"]
FactoryContentType = Literal[
    "reel", "post", "story", "carousel", "article", "telegram", "linkedin",
]
FactoryReviewStatus = Literal[
    "draft", "generated", "needs_review", "approved", "scheduled", "published", "rejected",
]
FactoryContentCategory = Literal[
    "product_announcement", "factory_news", "production_process", "customer_success",
    "promotion", "exhibition", "educational", "export_opportunity", "corporate_update", "other",
]
FactoryInputType = Literal["image", "video", "document", "text", "mixed"]
SupportedLanguage = Literal["ru", "uz", "en", "zh"]
FactoryPlatform = Literal[
    "telegram", "facebook", "linkedin", "instagram", "wechat", "whatsapp_status",
]


class ContentFactoryGenerateRequest(BaseModel):
    client_id: UUID
    source_media_id: Optional[UUID] = None
    source_content_id: Optional[UUID] = None
    number_of_variations: int = Field(default=4, ge=1, le=12)
    content_category: Optional[FactoryContentCategory] = "other"
    target_languages: Optional[List[SupportedLanguage]] = None
    input_text: Optional[str] = None
    input_type: Optional[FactoryInputType] = None
    target_platforms: Optional[List[FactoryPlatform]] = None


class ContentFactoryTextGenerateRequest(BaseModel):
    client_id: UUID
    input_text: str = Field(min_length=10, max_length=10000)
    source_media_id: Optional[UUID] = None
    source_content_id: Optional[UUID] = None
    number_of_variations: int = Field(default=4, ge=1, le=12)
    content_category: Optional[FactoryContentCategory] = "other"
    target_languages: Optional[List[SupportedLanguage]] = None
    input_type: Optional[FactoryInputType] = "text"
    target_platforms: Optional[List[FactoryPlatform]] = None


class QualityScoresResponse(BaseModel):
    quality_score: int = 0
    readability_score: int = 0
    engagement_score: int = 0
    completeness_score: int = 0
    overall_score: int = 0
    recommendations: List[str] = Field(default_factory=list)


class ContentFactoryItemResponse(BaseModel):
    id: UUID
    content_type: str
    theme: str
    angle: str
    title: str
    headline: Optional[str] = None
    platforms: List[str] = Field(default_factory=list)
    hashtags: Optional[str] = None
    cta_suggestion: Optional[str] = None
    preview_caption: Optional[str] = None
    captions: Optional[dict] = None
    generated_content_id: Optional[UUID] = None
    review_status: FactoryReviewStatus = "generated"
    quality_scores: Optional[QualityScoresResponse] = None
    platform_variants: Optional[dict] = None
    scheduled_for: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContentFactoryResponse(BaseModel):
    id: UUID
    client_id: UUID
    company_name: Optional[str] = None
    source_media_id: Optional[UUID] = None
    source_media_url: Optional[str] = None
    source_media_type: Optional[str] = None
    source_content_id: Optional[UUID] = None
    status: FactoryStatus
    input_type: Optional[str] = None
    input_text: Optional[str] = None
    content_category: Optional[str] = None
    target_languages: List[str] = Field(default_factory=list)
    items: List[ContentFactoryItemResponse] = Field(default_factory=list)
    created_at: datetime


class ContentFactoryCreateDraftRequest(BaseModel):
    generate_ai: bool = True


class ContentFactoryDraftResponse(BaseModel):
    ok: bool
    created: bool
    message: str
    factory_item_id: UUID
    content_id: UUID
    ai_applied: bool = False
    ai_error: Optional[str] = None


class ContentFactoryReviewUpdateRequest(BaseModel):
    review_status: FactoryReviewStatus
    notes: Optional[str] = None


class ContentFactoryScheduleRequest(BaseModel):
    scheduled_for: datetime
    platforms: Optional[List[str]] = None


class ContentFactoryTelegramGenerateRequest(BaseModel):
    number_of_variations: int = Field(default=3, ge=1, le=8)
    target_languages: Optional[List[SupportedLanguage]] = None


class ContentFactoryLibraryQuery(BaseModel):
    client_id: Optional[UUID] = None
    language: Optional[str] = None
    content_type: Optional[str] = None
    content_category: Optional[str] = None
    platform: Optional[str] = None
    status: Optional[FactoryReviewStatus] = None
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
