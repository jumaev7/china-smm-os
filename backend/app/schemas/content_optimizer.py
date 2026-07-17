"""API schemas for Deterministic Content Optimizer (Phase 2A)."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OptimizeContentRequest(BaseModel):
    """Client request — no versions, scores, tenant IDs, or transformation lists."""

    platforms: list[str] | None = Field(default=None, max_length=5)
    locales: list[str] | None = Field(default=None, max_length=4)
    length_profiles: list[str] | None = Field(default=None, max_length=3)
    include_existing_cta: bool = True
    include_existing_hashtags: bool = True
    approved_template_ids: list[UUID] | None = Field(default=None, max_length=50)


class ApplyVariantRequest(BaseModel):
    expected_source_fingerprint: str = Field(..., min_length=16, max_length=64)


class TransformationResponse(BaseModel):
    sequence: int
    operation_key: str
    category: str
    reason_key: str
    reason_params: dict[str, Any] | None = None
    result_summary: str | None = None
    policy_key: str | None = None
    policy_version: str | None = None


class VariantResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    variant_id: UUID | None = None
    id: UUID | str | None = None
    optimization_run_id: UUID | str | None = None
    content_id: UUID | str | None = None
    platform: str
    locale: str
    length_profile: str
    status: str
    caption: str | None = None
    hashtags: list[str] = Field(default_factory=list)
    cta: str | None = None
    link: str | None = None
    source_fingerprint: str
    variant_fingerprint: str
    source_score: int | None = None
    variant_score: int | None = None
    score_delta: int | None = None
    category_deltas: dict[str, Any] = Field(default_factory=dict)
    publish_readiness: str | None = None
    publishing_review_id: UUID | str | None = None
    unsupported_reason: str | None = None
    is_stale: bool = False
    transformations: list[TransformationResponse] = Field(default_factory=list)
    created_at: datetime | str | None = None
    accepted_at: datetime | str | None = None
    rejected_at: datetime | str | None = None
    applied_at: datetime | str | None = None


class OptimizationRunResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    run_id: UUID | str | None = None
    id: UUID | str | None = None
    content_id: UUID | str
    source_fingerprint: str
    optimizer_version: str
    policy_version: str
    status: str
    requested_platforms: list[str] = Field(default_factory=list)
    requested_locales: list[str] = Field(default_factory=list)
    configuration: dict[str, Any] = Field(default_factory=dict)
    generated_count: int | None = None
    failed_count: int | None = None
    failure_code: str | None = None
    variants: list[VariantResponse] = Field(default_factory=list)
    created_at: datetime | str | None = None
    completed_at: datetime | str | None = None


class OptimizationRunListResponse(BaseModel):
    items: list[OptimizationRunResponse]
    total: int
    page: int
    page_size: int


class OptimizationRunDetailResponse(BaseModel):
    run: OptimizationRunResponse
    variants: list[VariantResponse] = Field(default_factory=list)


class TemplateCreateRequest(BaseModel):
    template_type: str = Field(..., max_length=40)
    name: str = Field(..., min_length=1, max_length=120)
    locale: str = Field(..., max_length=10)
    content: str = Field(..., min_length=1, max_length=500)
    allowed_platforms: list[str] | None = None


class TemplateUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    allowed_platforms: list[str] | None = None
    is_active: bool | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    template_type: str
    name: str
    locale: str
    content: str
    allowed_platforms: list[str] = Field(default_factory=list)
    is_active: bool = True
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class TemplateListResponse(BaseModel):
    items: list[TemplateResponse]
    total: int


class OptimizerConfigurationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    optimizer_version: str
    source_fingerprint_version: str | None = None
    fingerprint_version: str | None = None
    variant_fingerprint_version: str | None = None
    policy_catalog_version: str | None = None
    platform_policy_version: str | None = None
    supported_platforms: list[str] = Field(default_factory=list)
    supported_locales: list[str] = Field(default_factory=list)
    supported_length_profiles: list[str] = Field(default_factory=list)
    length_profiles: list[str] = Field(default_factory=list)
    available_operations: list[dict[str, str]] = Field(default_factory=list)
    maximum_input_length: int | None = None
    maximum_variants_per_run: int | None = None
    limits: dict[str, Any] = Field(default_factory=dict)
    guarantees: list[str] = Field(default_factory=list)
    profiles: dict[str, Any] = Field(default_factory=dict)
    platform_strategies: dict[str, Any] = Field(default_factory=dict)


class OperationsCatalogResponse(BaseModel):
    operations: list[dict[str, str]]
