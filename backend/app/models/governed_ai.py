"""Governed AI Content Adaptation — tenant AI policies, requests, generations, brand profiles."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

AI_REQUEST_STATUSES = frozenset({
    "queued",
    "running",
    "completed",
    "validation_failed",
    "provider_failed",
    "quota_exceeded",
    "policy_blocked",
    "cancelled",
})
BRAND_PROFILE_STATUSES = frozenset({"draft", "published", "archived"})
GENERATION_METHODS = frozenset({"deterministic", "ai_assisted"})


class TenantAIPolicy(Base):
    __tablename__ = "tenant_ai_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_tenant_ai_policies_tenant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false")
    allowed_task_types: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    allowed_locales: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    allowed_platforms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    allow_provider_processing: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    allow_fallback_provider: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="false")
    store_redacted_inputs: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    store_redacted_outputs: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    hourly_request_limit: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    daily_token_limit: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    monthly_cost_limit_minor: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantAIRequest(Base):
    __tablename__ = "tenant_ai_requests"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "idempotency_key",
            name="uq_tenant_ai_requests_tenant_idempotency",
        ),
        Index("ix_tenant_ai_requests_tenant_content_created", "tenant_id", "entity_id", "requested_at"),
        Index("ix_tenant_ai_requests_tenant_status_requested", "tenant_id", "request_status", "requested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, server_default="content")
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    request_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="queued")
    model_alias: Mapped[str] = mapped_column(String(40), nullable=False)
    resolved_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolved_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    routing_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    prompt_key: Mapped[str] = mapped_column(String(120), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(20), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    brand_profile_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    optimization_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_content_optimization_runs.id", ondelete="SET NULL"),
        nullable=True,
    )
    configuration: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_metadata: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)


class TenantAIGeneration(Base):
    __tablename__ = "tenant_ai_generations"
    __table_args__ = (
        UniqueConstraint(
            "ai_request_id", "generation_version",
            name="uq_tenant_ai_generations_request_version",
        ),
        Index("ix_tenant_ai_generations_tenant_request", "tenant_id", "ai_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ai_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_ai_requests.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    generation_version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    length_profile: Mapped[str | None] = mapped_column(String(20), nullable=True)
    structured_output: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    redacted_input_snapshot: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    redacted_output_snapshot: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    output_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    estimated_cost_minor: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="USD")
    latency_ms: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(40), nullable=True)
    validation_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    safety_status: Mapped[str] = mapped_column(String(40), nullable=False, server_default="pending")
    factual_validation: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    protected_fact_summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    content_variant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_content_variants.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantAIUsageDaily(Base):
    __tablename__ = "tenant_ai_usage_daily"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "usage_date", "provider", "model", "task_type",
            name="uq_tenant_ai_usage_daily_dims",
        ),
        Index("ix_tenant_ai_usage_daily_tenant_date", "tenant_id", "usage_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    usage_date: Mapped[date] = mapped_column(Date(), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    task_type: Mapped[str] = mapped_column(String(80), nullable=False)
    request_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    successful_request_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    failed_request_count: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    input_tokens: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    total_tokens: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    estimated_cost_minor: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="USD")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantBrandProfile(Base):
    __tablename__ = "tenant_brand_profiles"
    __table_args__ = (
        Index("ix_tenant_brand_profiles_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="draft")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    draft_payload: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    draft_version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantBrandProfileVersion(Base):
    """Immutable published brand profile snapshot."""

    __tablename__ = "tenant_brand_profile_versions"
    __table_args__ = (
        UniqueConstraint(
            "brand_profile_id", "version",
            name="uq_tenant_brand_profile_versions_profile_version",
        ),
        Index("ix_tenant_brand_profile_versions_tenant_profile", "tenant_id", "brand_profile_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    brand_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenant_brand_profiles.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    version: Mapped[int] = mapped_column(Integer(), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, server_default="en")
    company_name: Mapped[str] = mapped_column(String(200), nullable=False, server_default="")
    company_description: Mapped[str] = mapped_column(Text(), nullable=False, server_default="")
    audience_description: Mapped[str] = mapped_column(Text(), nullable=False, server_default="")
    tone_traits: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    preferred_terms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    forbidden_terms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    approved_claims: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    prohibited_claims: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    cta_preferences: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    emoji_policy: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    formatting_preferences: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    platform_guidance: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    source_references: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
