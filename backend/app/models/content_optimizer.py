"""Deterministic Content Optimizer — immutable platform content variants."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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

OPTIMIZATION_RUN_STATUSES = frozenset({
    "generated",
    "partial",
    "failed",
    "superseded",
})
VARIANT_STATUSES = frozenset({
    "generated",
    "accepted",
    "rejected",
    "superseded",
    "failed",
    "applied",
    "stale",
})
LENGTH_PROFILES = frozenset({"short", "standard", "extended"})
TEMPLATE_TYPES = frozenset({
    "cta",
    "disclosure",
    "footer",
    "contact_block",
    "hashtag_set",
})


class TenantContentOptimizationRun(Base):
    """One deterministic optimization request against a source content item."""

    __tablename__ = "tenant_content_optimization_runs"
    __table_args__ = (
        Index(
            "ix_tenant_content_opt_runs_tenant_content_created",
            "tenant_id",
            "content_id",
            "created_at",
        ),
        Index(
            "ix_tenant_content_opt_runs_tenant_status_created",
            "tenant_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    optimizer_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="1.0.0",
    )
    policy_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="1.0.0",
    )
    requested_platforms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    requested_locales: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    configuration: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="generated",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    failure_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    failure_metadata: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)


class TenantContentVariant(Base):
    """Immutable platform/locale/length variant snapshot."""

    __tablename__ = "tenant_content_variants"
    __table_args__ = (
        UniqueConstraint(
            "optimization_run_id",
            "platform",
            "locale",
            "length_profile",
            name="uq_tenant_content_variants_run_platform_locale_profile",
        ),
        Index(
            "ix_tenant_content_variants_tenant_content_created",
            "tenant_id",
            "content_id",
            "created_at",
        ),
        Index(
            "ix_tenant_content_variants_tenant_platform_locale_created",
            "tenant_id",
            "platform",
            "locale",
            "created_at",
        ),
        Index(
            "ix_tenant_content_variants_run_platform_locale_profile",
            "optimization_run_id",
            "platform",
            "locale",
            "length_profile",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    optimization_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_content_optimization_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False)
    length_profile: Mapped[str] = mapped_column(String(20), nullable=False)
    variant_version: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    caption: Mapped[str] = mapped_column(Text(), nullable=False, server_default="")
    hashtags: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    cta: Mapped[str | None] = mapped_column(Text(), nullable=True)
    link: Mapped[str | None] = mapped_column(Text(), nullable=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    variant_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="generated",
    )
    publish_readiness: Mapped[str | None] = mapped_column(String(40), nullable=True)
    publishing_review_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_publishing_reviews.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    variant_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    score_delta: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    category_deltas: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    unsupported_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Governed AI Content Adaptation (Phase 2B) — optional provenance fields
    generation_method: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="deterministic",
    )
    ai_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    ai_generation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    brand_profile_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    prompt_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    model_alias: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolved_provider: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resolved_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    factual_validation_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    safety_validation_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantContentVariantTransformation(Base):
    """Explainable transformation step applied while building a variant."""

    __tablename__ = "tenant_content_variant_transformations"
    __table_args__ = (
        UniqueConstraint(
            "content_variant_id",
            "sequence",
            name="uq_tenant_content_variant_transformations_variant_seq",
        ),
        Index(
            "ix_tenant_content_variant_xf_tenant_variant",
            "tenant_id",
            "content_variant_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    content_variant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_content_variants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer(), nullable=False)
    operation_key: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    source_excerpt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_position: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    result_excerpt_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason_key: Mapped[str] = mapped_column(String(80), nullable=False)
    reason_params: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    policy_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result_summary: Mapped[str | None] = mapped_column(String(240), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantContentTemplate(Base):
    """Tenant-approved plain-text templates for deterministic reuse."""

    __tablename__ = "tenant_content_templates"
    __table_args__ = (
        Index(
            "ix_tenant_content_templates_tenant_type_locale",
            "tenant_id",
            "template_type",
            "locale",
        ),
        Index(
            "ix_tenant_content_templates_tenant_active",
            "tenant_id",
            "is_active",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    template_type: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text(), nullable=False)
    allowed_platforms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean(), nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(),
        onupdate=func.now(), nullable=False,
    )
