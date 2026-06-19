from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
from typing import Optional

from app.utils.telegram_publish_destination import (
    TELEGRAM_PUBLISH_TYPES,
    validate_telegram_publish_chat_id,
    validate_telegram_publish_type,
)


SOURCE_LANGUAGES = ["zh", "en", "ru", "ko", "ja"]
CONTENT_STYLES = ["professional", "casual", "luxury", "educational", "promotional"]
TONE_OF_VOICE = ["formal", "friendly", "premium", "energetic", "technical"]
PREFERRED_OUTPUT_LANGUAGES = ["ru", "uz", "en", "cn"]
BUSINESS_CATEGORIES = [
    "restaurant", "retail", "beauty", "construction", "logistics",
    "technology", "education", "healthcare", "real_estate", "other"
]

DEFAULT_PREFERRED_LANGUAGES = ["ru", "uz", "en"]
TELEGRAM_WORKFLOW_MODES = ["auto_create_from_media", "admin_controlled_buffer"]
TELEGRAM_PUBLISH_TYPE_VALUES = sorted(TELEGRAM_PUBLISH_TYPES)


class ClientBrandFields(BaseModel):
    brand_name: Optional[str] = Field(None, max_length=255)
    business_description: Optional[str] = Field(None, max_length=4000)
    products_services: Optional[str] = Field(None, max_length=4000)
    target_audience: Optional[str] = Field(None, max_length=2000)
    tone_of_voice: str = Field(default="friendly")
    preferred_languages: list[str] = Field(default_factory=lambda: list(DEFAULT_PREFERRED_LANGUAGES))
    cta_phone: Optional[str] = Field(None, max_length=100)
    cta_telegram: Optional[str] = Field(None, max_length=100)
    cta_website: Optional[str] = Field(None, max_length=500)
    cta_address: Optional[str] = Field(None, max_length=500)
    words_to_avoid: Optional[str] = Field(None, max_length=2000)
    hashtag_preferences: Optional[str] = Field(None, max_length=1000)
    logo_url: Optional[str] = Field(None, max_length=500)
    telegram_group_id: Optional[str] = Field(None, max_length=50)
    telegram_group_title: Optional[str] = Field(None, max_length=255)
    telegram_workflow_mode: str = Field(default="auto_create_from_media")
    operator_auto_draft_enabled: bool = Field(default=False)
    telegram_publish_chat_id: Optional[str] = Field(None, max_length=255)
    telegram_publish_title: Optional[str] = Field(None, max_length=255)
    telegram_publish_type: Optional[str] = Field(None, max_length=20)

    @field_validator("telegram_publish_chat_id", mode="before")
    @classmethod
    def _validate_publish_chat_id(cls, value):
        return validate_telegram_publish_chat_id(value)

    @field_validator("telegram_publish_type", mode="before")
    @classmethod
    def _validate_publish_type(cls, value):
        return validate_telegram_publish_type(value)


class ClientCreate(BaseModel):
    company_name: str = Field(..., min_length=1, max_length=255)
    source_language: str = Field(default="zh")
    business_category: str = Field(..., min_length=1)
    content_style: str = Field(default="professional")
    notes: Optional[str] = Field(None, max_length=1000)
    brand_name: Optional[str] = Field(None, max_length=255)
    business_description: Optional[str] = Field(None, max_length=4000)
    products_services: Optional[str] = Field(None, max_length=4000)
    target_audience: Optional[str] = Field(None, max_length=2000)
    tone_of_voice: str = Field(default="friendly")
    preferred_languages: list[str] = Field(default_factory=lambda: list(DEFAULT_PREFERRED_LANGUAGES))
    cta_phone: Optional[str] = Field(None, max_length=100)
    cta_telegram: Optional[str] = Field(None, max_length=100)
    cta_website: Optional[str] = Field(None, max_length=500)
    cta_address: Optional[str] = Field(None, max_length=500)
    words_to_avoid: Optional[str] = Field(None, max_length=2000)
    hashtag_preferences: Optional[str] = Field(None, max_length=1000)
    logo_url: Optional[str] = Field(None, max_length=500)
    telegram_group_id: Optional[str] = Field(None, max_length=50)
    telegram_group_title: Optional[str] = Field(None, max_length=255)
    telegram_workflow_mode: str = Field(default="auto_create_from_media")
    operator_auto_draft_enabled: bool = Field(default=False)
    telegram_publish_chat_id: Optional[str] = Field(None, max_length=255)
    telegram_publish_title: Optional[str] = Field(None, max_length=255)
    telegram_publish_type: Optional[str] = Field(None, max_length=20)

    @field_validator("telegram_publish_chat_id", mode="before")
    @classmethod
    def _validate_publish_chat_id_create(cls, value):
        return validate_telegram_publish_chat_id(value)

    @field_validator("telegram_publish_type", mode="before")
    @classmethod
    def _validate_publish_type_create(cls, value):
        return validate_telegram_publish_type(value)


class ClientUpdate(BaseModel):
    company_name: Optional[str] = Field(None, min_length=1, max_length=255)
    source_language: Optional[str] = None
    business_category: Optional[str] = None
    content_style: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = Field(None, max_length=1000)
    brand_name: Optional[str] = Field(None, max_length=255)
    business_description: Optional[str] = Field(None, max_length=4000)
    products_services: Optional[str] = Field(None, max_length=4000)
    target_audience: Optional[str] = Field(None, max_length=2000)
    tone_of_voice: Optional[str] = None
    preferred_languages: Optional[list[str]] = None
    cta_phone: Optional[str] = Field(None, max_length=100)
    cta_telegram: Optional[str] = Field(None, max_length=100)
    cta_website: Optional[str] = Field(None, max_length=500)
    cta_address: Optional[str] = Field(None, max_length=500)
    words_to_avoid: Optional[str] = Field(None, max_length=2000)
    hashtag_preferences: Optional[str] = Field(None, max_length=1000)
    logo_url: Optional[str] = Field(None, max_length=500)
    telegram_group_id: Optional[str] = Field(None, max_length=50)
    telegram_group_title: Optional[str] = Field(None, max_length=255)
    telegram_workflow_mode: Optional[str] = None
    operator_auto_draft_enabled: Optional[bool] = None
    telegram_publish_chat_id: Optional[str] = Field(None, max_length=255)
    telegram_publish_title: Optional[str] = Field(None, max_length=255)
    telegram_publish_type: Optional[str] = Field(None, max_length=20)

    @field_validator("telegram_publish_chat_id", mode="before")
    @classmethod
    def _validate_publish_chat_id_update(cls, value):
        return validate_telegram_publish_chat_id(value)

    @field_validator("telegram_publish_type", mode="before")
    @classmethod
    def _validate_publish_type_update(cls, value):
        return validate_telegram_publish_type(value)


class ClientResponse(BaseModel):
    id: UUID
    company_name: str
    source_language: str
    business_category: str
    content_style: str
    status: str
    notes: Optional[str]
    brand_name: Optional[str] = None
    business_description: Optional[str] = None
    products_services: Optional[str] = None
    target_audience: Optional[str] = None
    tone_of_voice: str = "friendly"
    preferred_languages: list[str] = Field(default_factory=lambda: list(DEFAULT_PREFERRED_LANGUAGES))
    cta_phone: Optional[str] = None
    cta_telegram: Optional[str] = None
    cta_website: Optional[str] = None
    cta_address: Optional[str] = None
    words_to_avoid: Optional[str] = None
    hashtag_preferences: Optional[str] = None
    logo_url: Optional[str] = None
    telegram_group_id: Optional[str] = None
    telegram_group_title: Optional[str] = None
    telegram_workflow_mode: str = "auto_create_from_media"
    operator_auto_draft_enabled: bool = False
    telegram_publish_chat_id: Optional[str] = None
    telegram_publish_title: Optional[str] = None
    telegram_publish_type: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @field_validator("preferred_languages", mode="before")
    @classmethod
    def _default_preferred_languages(cls, value):
        if not value:
            return list(DEFAULT_PREFERRED_LANGUAGES)
        return value

    @field_validator("tone_of_voice", mode="before")
    @classmethod
    def _default_tone(cls, value):
        if not value:
            return "friendly"
        return value

    @field_validator("telegram_workflow_mode", mode="before")
    @classmethod
    def _default_telegram_workflow_mode(cls, value):
        if not value:
            return "auto_create_from_media"
        return value

    model_config = {"from_attributes": True}


class ClientListResponse(BaseModel):
    items: list[ClientResponse]
    total: int
