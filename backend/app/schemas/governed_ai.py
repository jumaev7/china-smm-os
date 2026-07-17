"""API schemas for Governed AI Content Adaptation.

Clients cannot submit provider name, raw model, system prompt, temperature,
max tokens, tenant_id, output content, usage, cost, score, or validation result.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Brand profiles
# ---------------------------------------------------------------------------


class BrandProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=160)
    draft: dict[str, Any] | None = None


class BrandProfileDraftUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    draft: dict[str, Any]
    expected_draft_version: int | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)


class BrandProfileResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    name: str
    status: str
    current_version_id: UUID | str | None = None
    draft_payload: dict[str, Any] = Field(default_factory=dict)
    draft_version: int | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class BrandProfileVersionResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    brand_profile_id: UUID | str
    version: int
    locale: str
    company_name: str = ""
    company_description: str = ""
    audience_description: str = ""
    tone_traits: list[str] = Field(default_factory=list)
    preferred_terms: list[str] = Field(default_factory=list)
    forbidden_terms: list[str] = Field(default_factory=list)
    approved_claims: list[str] = Field(default_factory=list)
    prohibited_claims: list[str] = Field(default_factory=list)
    cta_preferences: dict[str, Any] = Field(default_factory=dict)
    emoji_policy: dict[str, Any] = Field(default_factory=dict)
    formatting_preferences: dict[str, Any] = Field(default_factory=dict)
    platform_guidance: dict[str, Any] = Field(default_factory=dict)
    source_references: list[str] = Field(default_factory=list)
    published_at: datetime | str | None = None
    created_at: datetime | str | None = None


class BrandProfileListResponse(BaseModel):
    items: list[BrandProfileResponse]
    total: int


class BrandProfileVersionListResponse(BaseModel):
    items: list[BrandProfileVersionResponse]
    total: int


# ---------------------------------------------------------------------------
# AI content adaptation
# ---------------------------------------------------------------------------


class AdaptContentRequest(BaseModel):
    """Client adapt request — no provider, model, prompts, tenant, or scores."""

    model_config = ConfigDict(extra="forbid")

    platforms: list[str] | None = Field(default=None, max_length=5)
    locales: list[str] | None = Field(default=None, max_length=5)
    length_profiles: list[str] | None = Field(default=None, max_length=3)
    brand_profile_version_id: UUID | None = None
    approved_template_ids: list[UUID] | None = Field(default=None, max_length=50)
    quality_mode: str | None = Field(default=None, max_length=40)
    idempotency_key: str | None = Field(default=None, max_length=128)


class AIVariantResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    variant_id: UUID | str | None = None
    id: UUID | str | None = None
    generation_method: str | None = None
    platform: str
    locale: str
    length_profile: str
    caption: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    cta: str | None = None
    link: str | None = None
    status: str
    is_stale: bool = False
    ai_request_id: UUID | str | None = None
    ai_generation_id: UUID | str | None = None
    model_alias: str | None = None
    brand_profile_version_id: UUID | str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    factual_validation_status: str | None = None
    safety_validation_status: str | None = None
    factual_validation: dict[str, Any] | None = None
    protected_fact_summary: dict[str, Any] | None = None
    source_score: int | None = None
    variant_score: int | None = None
    score_delta: int | None = None
    category_deltas: dict[str, Any] = Field(default_factory=dict)
    publish_readiness: str | None = None
    publishing_review_id: UUID | str | None = None
    source_fingerprint: str | None = None
    created_at: datetime | str | None = None
    warnings: list[str] = Field(default_factory=list)


class AIGenerationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    generation_id: UUID | str
    ai_request_id: UUID | str | None = None
    generation_version: int | None = None
    platform: str | None = None
    locale: str | None = None
    length_profile: str | None = None
    validation_status: str | None = None
    safety_status: str | None = None
    factual_validation: dict[str, Any] | None = None
    protected_fact_summary: dict[str, Any] | None = None
    content_variant_id: UUID | str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    estimated_cost_minor: int | None = None
    currency: str | None = None
    created_at: datetime | str | None = None


class AIUsageSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_minor: int = 0
    currency: str = "USD"
    note: str | None = None


class AIRequestResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    request_id: UUID | str
    status: str
    content_id: UUID | str | None = None
    source_fingerprint: str | None = None
    brand_profile_version: int | None = None
    brand_profile_version_id: UUID | str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    model_alias: str | None = None
    resolved_provider: str | None = None
    routing_version: str | None = None
    variants: list[AIVariantResponse] = Field(default_factory=list)
    generations: list[AIGenerationResponse] = Field(default_factory=list)
    usage: AIUsageSummary | dict[str, Any] | None = None
    validation_summary: dict[str, Any] | None = None
    failure_code: str | None = None
    created_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class AIRequestListItem(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    request_id: UUID | str
    status: str
    model_alias: str | None = None
    prompt_version: str | None = None
    created_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    failure_code: str | None = None


class AIRequestListResponse(BaseModel):
    items: list[AIRequestListItem]
    total: int


class AIConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    ai_enabled: bool
    platform_enabled: bool
    tenant_enabled: bool
    allowed_task_types: list[str] = Field(default_factory=list)
    allowed_locales: list[str] = Field(default_factory=list)
    allowed_platforms: list[str] = Field(default_factory=list)
    quality_modes: list[str] = Field(default_factory=list)
    model_aliases: list[str] = Field(default_factory=list)
    prompt_key: str | None = None
    prompt_version: str | None = None
    hourly_request_limit: int | None = None
    daily_token_limit: int | None = None
    max_variants_per_request: int | None = None
    notes: list[str] = Field(default_factory=list)


class AIUsageDailyRow(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    usage_date: str
    task_type: str | None = None
    model_alias: str | None = None
    request_count: int = 0
    successful_request_count: int = 0
    failed_request_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_minor: int = 0
    currency: str = "USD"


class AIUsageResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    period_days: int
    rows: list[AIUsageDailyRow] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
    note: str | None = None
