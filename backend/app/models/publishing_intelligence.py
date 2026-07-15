"""Publishing Intelligence — immutable deterministic pre-publish reviews."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

REVIEW_STATUSES = frozenset({"completed", "stale", "superseded", "failed"})
CHECK_STATUSES = frozenset({"passed", "warning", "failed", "not_applicable"})
CHECK_SEVERITIES = frozenset({"info", "warning", "error", "critical"})

SCORE_CATEGORIES = frozenset({
    "caption_quality",
    "platform_fit",
    "cta_quality",
    "hashtag_quality",
    "keyword_readiness",
    "media_readiness",
    "language_quality",
    "translation_readiness",
    "compliance_readiness",
    "scheduling_readiness",
})


class TenantPublishingReview(Base):
    """Immutable snapshot of a deterministic publishing-quality review."""

    __tablename__ = "tenant_publishing_reviews"
    __table_args__ = (
        UniqueConstraint(
            "content_id",
            "review_version",
            name="uq_tenant_publishing_reviews_content_version",
        ),
        Index(
            "ix_tenant_publishing_reviews_tenant_content_created",
            "tenant_id",
            "content_id",
            "created_at",
        ),
        Index(
            "ix_tenant_publishing_reviews_tenant_status_created",
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
    review_version: Mapped[int] = mapped_column(Integer(), nullable=False)
    review_engine_version: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="1.0.0",
    )
    content_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    overall_score: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="completed",
    )
    primary_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    target_platforms: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    summary: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
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


class TenantPublishingReviewCheck(Base):
    """Individual deterministic check result within a publishing review."""

    __tablename__ = "tenant_publishing_review_checks"
    __table_args__ = (
        Index(
            "ix_tenant_publishing_review_checks_review_category",
            "publishing_review_id",
            "category",
        ),
        Index(
            "ix_tenant_publishing_review_checks_tenant_review",
            "tenant_id",
            "publishing_review_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    publishing_review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_publishing_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    check_key: Mapped[str] = mapped_column(String(80), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="info",
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    weight: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="1")
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    recommendation_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    recommendation_params: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantPublishingPlatformReview(Base):
    """Per-platform score breakdown within a publishing review."""

    __tablename__ = "tenant_publishing_platform_reviews"
    __table_args__ = (
        UniqueConstraint(
            "publishing_review_id",
            "platform",
            name="uq_tenant_publishing_platform_reviews_review_platform",
        ),
        Index(
            "ix_tenant_publishing_platform_reviews_tenant_review",
            "tenant_id",
            "publishing_review_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    publishing_review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenant_publishing_reviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    platform_score: Mapped[int] = mapped_column(Integer(), nullable=False, server_default="0")
    caption_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    media_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    cta_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    hashtag_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    language_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    compliance_score: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    recommendations: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
