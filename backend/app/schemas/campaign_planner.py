"""API schemas for Campaign Planner (tenant-scoped).

Clients cannot inject tenant_id, publish/schedule side effects, raw AI prompts,
provider/model selection beyond quality_mode, or secrets.
"""
from __future__ import annotations

from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Content pillars
# ---------------------------------------------------------------------------


class ContentPillarCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=160)
    slug: str | None = Field(default=None, max_length=160)
    description: str | None = None
    color: str | None = Field(default=None, max_length=20)
    default_weight: int = Field(default=1, ge=1, le=100)
    is_active: bool = True


class ContentPillarUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = None
    color: str | None = None
    default_weight: int | None = Field(default=None, ge=1, le=100)
    is_active: bool | None = None


class ContentPillarResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    name: str
    slug: str
    description: str | None = None
    color: str | None = None
    default_weight: int = 1
    is_active: bool = True
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None


class ContentPillarListResponse(BaseModel):
    items: list[ContentPillarResponse]
    total: int


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


class CampaignCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    objective: str | None = Field(default=None, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    primary_locale: str = Field(default="en", max_length=10)
    locales: list[str] | None = Field(default=None, max_length=4)
    platforms: list[str] | None = Field(default=None, max_length=5)
    start_date: date | str | None = None
    end_date: date | str | None = None
    blackout_dates: list[date | str] | None = None
    cadence: dict[str, Any] | None = None
    brand_profile_id: UUID | None = None
    brand_profile_version_id: UUID | None = None
    metadata: dict[str, Any] | None = None


class CampaignUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    objective: str | None = None
    status: str | None = None
    timezone: str | None = None
    primary_locale: str | None = None
    locales: list[str] | None = None
    platforms: list[str] | None = None
    start_date: date | str | None = None
    end_date: date | str | None = None
    blackout_dates: list[date | str] | None = None
    cadence: dict[str, Any] | None = None
    brand_profile_id: UUID | None = None
    brand_profile_version_id: UUID | None = None
    metadata: dict[str, Any] | None = None
    expected_updated_at: datetime | None = None


class CampaignResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    name: str
    description: str | None = None
    status: str
    objective: str | None = None
    timezone: str = "UTC"
    primary_locale: str = "en"
    locales: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    start_date: date | str | None = None
    end_date: date | str | None = None
    blackout_dates: list[Any] = Field(default_factory=list)
    cadence: dict[str, Any] = Field(default_factory=dict)
    brand_profile_id: UUID | str | None = None
    brand_profile_version_id: UUID | str | None = None
    current_plan_version_id: UUID | str | None = None
    published_plan_version_id: UUID | str | None = None
    planner_version: str | None = None
    policy_version: str | None = None
    created_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    archived_at: datetime | str | None = None


class CampaignListResponse(BaseModel):
    items: list[CampaignResponse]
    total: int


# ---------------------------------------------------------------------------
# Nested children
# ---------------------------------------------------------------------------


class GoalCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_type: str = "other"
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    priority: str = "medium"
    target_metric: str | None = None
    sort_order: int = 0


class GoalUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal_type: str | None = None
    title: str | None = None
    description: str | None = None
    priority: str | None = None
    target_metric: str | None = None
    sort_order: int | None = None


class GoalResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    campaign_id: UUID | str
    goal_type: str
    title: str
    description: str | None = None
    priority: str = "medium"
    target_metric: str | None = None
    sort_order: int = 0
    created_at: datetime | str | None = None


class KpiCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    metric_key: str = Field(..., min_length=1, max_length=120)
    target_value: float | None = None
    unit: str | None = None
    comparator: str = ">="
    timeframe: str | None = None
    sort_order: int = 0


class KpiUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    metric_key: str | None = None
    target_value: float | None = None
    unit: str | None = None
    comparator: str | None = None
    timeframe: str | None = None
    sort_order: int | None = None


class KpiResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    campaign_id: UUID | str
    name: str
    metric_key: str
    target_value: float | None = None
    unit: str | None = None
    comparator: str = ">="
    timeframe: str | None = None
    sort_order: int = 0


class AudienceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    locale: str | None = None
    platforms: list[str] | None = None
    segment: dict[str, Any] | None = None
    sort_order: int = 0


class AudienceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    locale: str | None = None
    platforms: list[str] | None = None
    segment: dict[str, Any] | None = None
    sort_order: int | None = None


class AudienceResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    campaign_id: UUID | str
    name: str
    description: str | None = None
    locale: str | None = None
    platforms: list[str] = Field(default_factory=list)
    segment: dict[str, Any] | None = None
    sort_order: int = 0


class PhaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=160)
    phase_type: str = "custom"
    description: str | None = None
    start_date: date | str | None = None
    end_date: date | str | None = None
    weight: int = Field(default=1, ge=1, le=100)
    sort_order: int = 0


class PhaseUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    phase_type: str | None = None
    description: str | None = None
    start_date: date | str | None = None
    end_date: date | str | None = None
    weight: int | None = None
    sort_order: int | None = None


class PhaseResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    campaign_id: UUID | str
    name: str
    phase_type: str
    description: str | None = None
    start_date: date | str | None = None
    end_date: date | str | None = None
    weight: int = 1
    sort_order: int = 0


class CampaignPillarCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pillar_id: UUID
    weight: int | None = Field(default=None, ge=1, le=100)
    sort_order: int = 0


class CampaignPillarUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weight: int | None = Field(default=None, ge=1, le=100)
    sort_order: int | None = None


class CampaignPillarResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    campaign_id: UUID | str
    pillar_id: UUID | str
    weight: int = 1
    sort_order: int = 0


class NestedListResponse(BaseModel):
    items: list[Any]
    total: int


# ---------------------------------------------------------------------------
# Plans / slots / assignments
# ---------------------------------------------------------------------------


class PlanGenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cadence: dict[str, Any] | None = None
    notes: str | None = None


class PlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    campaign_id: UUID | str
    version: int
    status: str
    generation_method: str
    plan_fingerprint: str
    planner_version: str | None = None
    policy_version: str | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = None
    source_ai_request_id: UUID | str | None = None
    parent_version_id: UUID | str | None = None
    slot_count: int = 0
    created_at: datetime | str | None = None
    reviewed_at: datetime | str | None = None
    published_at: datetime | str | None = None


class PlanListResponse(BaseModel):
    items: list[PlanResponse]
    total: int


class SlotCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str
    locale: str = "en"
    scheduled_date: date | str
    scheduled_time: time | str
    pillar_id: UUID | None = None
    phase_id: UUID | None = None
    suggested_time_label: str | None = None
    notes: str | None = None


class SlotUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: str | None = None
    locale: str | None = None
    scheduled_date: date | str | None = None
    scheduled_time: time | str | None = None
    pillar_id: UUID | None = None
    phase_id: UUID | None = None
    notes: str | None = None


class SlotResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    plan_version_id: UUID | str
    campaign_id: UUID | str
    slot_index: int = 0
    platform: str
    locale: str
    pillar_id: UUID | str | None = None
    phase_id: UUID | str | None = None
    scheduled_date: date | str
    scheduled_time: time | str
    suggested_time_label: str | None = None
    status: str
    slot_fingerprint: str | None = None
    notes: str | None = None


class SlotListResponse(BaseModel):
    items: list[SlotResponse]
    total: int


class SlotAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content_id: UUID
    content_variant_id: UUID | None = None
    platform: str | None = None
    locale: str | None = None
    allow_warnings: bool = True


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    slot_id: UUID | str
    content_id: UUID | str | None = None
    content_variant_id: UUID | str | None = None
    assignment_type: str = "content"
    assigned_platform: str | None = None
    assigned_locale: str | None = None
    assignment_status: str
    readiness_status: str
    readiness_score: int | None = None
    publishing_review_id: UUID | str | None = None
    warnings: dict[str, Any] | list[Any] | None = None
    assigned_at: datetime | str | None = None


class AutoAssignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allow_warnings: bool = True
    run_publish_safety: bool = False


class AutoAssignResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    assigned: int
    skipped: int
    total_open: int
    results: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Reviews / inventory / AI
# ---------------------------------------------------------------------------


class ReviewResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID | str
    campaign_id: UUID | str
    plan_version_id: UUID | str | None = None
    review_type: str
    coverage_score: int | None = None
    readiness_score: int | None = None
    total_slots: int = 0
    assigned_slots: int = 0
    blocked_slots: int = 0
    unassigned_slots: int = 0
    conflict_count: int = 0
    gap_count: int = 0
    summary: dict[str, Any] = Field(default_factory=dict)
    engine_version: str | None = None
    created_at: datetime | str | None = None


class ReviewListResponse(BaseModel):
    items: list[ReviewResponse]
    total: int


class InventoryResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    returned: int = 0


class AIPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand_profile_version_id: UUID | None = None
    quality_mode: str | None = Field(default=None, max_length=40)
    idempotency_key: str | None = Field(default=None, max_length=128)


class AIPlanRequestResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    request_id: UUID | str
    status: str
    campaign_id: UUID | str | None = None
    source_fingerprint: str | None = None
    brand_profile_version_id: UUID | str | None = None
    prompt_key: str | None = None
    prompt_version: str | None = None
    model_alias: str | None = None
    routing_version: str | None = None
    proposal: dict[str, Any] | None = None
    apply_status: str | None = None
    applied_plan_version_id: UUID | str | None = None
    usage: dict[str, Any] | None = None
    failure_code: str | None = None
    created_at: datetime | str | None = None
    completed_at: datetime | str | None = None


class AIPlanRequestListItem(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    request_id: UUID | str
    status: str
    model_alias: str | None = None
    prompt_version: str | None = None
    apply_status: str | None = None
    created_at: datetime | str | None = None
    completed_at: datetime | str | None = None
    failure_code: str | None = None


class AIPlanRequestListResponse(BaseModel):
    items: list[AIPlanRequestListItem]
    total: int
