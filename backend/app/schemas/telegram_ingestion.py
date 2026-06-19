from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID


class TelegramIngestionSettingsResponse(BaseModel):
    enabled: bool = True
    allowed_group_ids: List[str] = Field(default_factory=list)
    default_tenant_id: Optional[str] = None
    default_status: str = "needs_review"
    default_target_languages: List[str] = Field(default_factory=lambda: ["ru", "uz", "en", "zh"])
    auto_classification: bool = True
    auto_enrichment: bool = True
    quality_checks_enabled: bool = True
    updated_at: Optional[str] = None
    env_bot_configured: bool = False


class TelegramIngestionSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    allowed_group_ids: Optional[List[str]] = None
    default_tenant_id: Optional[UUID] = None
    default_status: Optional[str] = None
    default_target_languages: Optional[List[str]] = None
    auto_classification: Optional[bool] = None
    auto_enrichment: Optional[bool] = None
    quality_checks_enabled: Optional[bool] = None


class ContentSuggestionCaptions(BaseModel):
    ru: Optional[str] = None
    uz: Optional[str] = None
    en: Optional[str] = None
    zh: Optional[str] = None


class ContentSuggestions(BaseModel):
    title: Optional[str] = None
    short_description: Optional[str] = None
    captions: Optional[ContentSuggestionCaptions] = None
    hashtags: Optional[str] = None
    cta: Optional[str] = None
    target_platforms: Optional[List[str]] = None
    price_detected: Optional[str] = None
    method: Optional[str] = None


class ContentQualityWarning(BaseModel):
    id: str
    message: str
    critical: bool = False
