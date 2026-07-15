"""Marketing Intelligence Platform — immutable signals, scores, and recommendations.

Signals are normalized intelligence data derived from Platform Event Bus events.
They are NOT audit logs and NOT platform_event rows.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

SIGNAL_SEVERITIES = frozenset({"info", "success", "warning", "error", "critical"})
SIGNAL_SOURCES = frozenset({
    "publishing",
    "crm",
    "workflow",
    "automation",
    "notification",
    "customer_success",
    "integration",
    "content",
    "onboarding",
    "system",
})

SCORE_CATEGORIES = frozenset({
    "publishing",
    "advertising",
    "crm",
    "automation",
    "workflow",
    "customer_success",
    "brand",
    "content",
    "overall",
})

RECOMMENDATION_PRIORITIES = frozenset({"low", "medium", "high", "critical"})
RECOMMENDATION_STATUSES = frozenset({"open", "acknowledged", "dismissed", "resolved"})
INSIGHT_KINDS = frozenset({"score", "recommendation", "trend", "signal_summary"})


class TenantMarketingSignal(Base):
    """Immutable normalized marketing signal (append-only intelligence store)."""

    __tablename__ = "tenant_marketing_signals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "signal_id",
            name="uq_tenant_marketing_signals_tenant_signal",
        ),
        Index(
            "ix_tenant_marketing_signals_tenant_occurred",
            "tenant_id",
            "occurred_at",
        ),
        Index(
            "ix_tenant_marketing_signals_tenant_type_occurred",
            "tenant_id",
            "signal_type",
            "occurred_at",
        ),
        Index(
            "ix_tenant_marketing_signals_tenant_source",
            "tenant_id",
            "source",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    # Public immutable identifier (often mirrors platform event_id for idempotency).
    signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    signal_type: Mapped[str] = mapped_column(String(80), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB(), nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="info", server_default="info",
    )
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("1.000"), server_default="1.000",
    )
    platform_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    platform_event_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantMarketingScore(Base):
    """Current scored marketing health by category (versioned, explainable)."""

    __tablename__ = "tenant_marketing_scores"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "category",
            name="uq_tenant_marketing_scores_tenant_category",
        ),
        Index(
            "ix_tenant_marketing_scores_tenant_updated",
            "tenant_id",
            "updated_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[int] = mapped_column(Integer(), nullable=False, default=50, server_default="50")
    weight: Mapped[Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, default=Decimal("0.1000"), server_default="0.1000",
    )
    scoring_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0.0", server_default="1.0.0",
    )
    explanation: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantMarketingScoreHistory(Base):
    """Append-only history of marketing scores for trend analysis."""

    __tablename__ = "tenant_marketing_score_history"
    __table_args__ = (
        Index(
            "ix_tenant_marketing_score_history_tenant_category_at",
            "tenant_id",
            "category",
            "recorded_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[int] = mapped_column(Integer(), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(20), nullable=False)
    explanation: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantMarketingRecommendation(Base):
    """Deterministic, evidence-backed marketing recommendation."""

    __tablename__ = "tenant_marketing_recommendations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "recommendation_key",
            name="uq_tenant_marketing_recommendations_tenant_key",
        ),
        Index(
            "ix_tenant_marketing_recommendations_tenant_priority",
            "tenant_id",
            "priority",
            "updated_at",
        ),
        Index(
            "ix_tenant_marketing_recommendations_tenant_status",
            "tenant_id",
            "status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    recommendation_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(4, 3), nullable=False, default=Decimal("0.800"), server_default="0.800",
    )
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="medium", server_default="medium",
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="open", server_default="open",
    )
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(
        String(20), nullable=False, default="1.0.0", server_default="1.0.0",
    )
    action_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False,
    )


class TenantMarketingRecommendationHistory(Base):
    """Append-only recommendation snapshots for historical intelligence."""

    __tablename__ = "tenant_marketing_recommendation_history"
    __table_args__ = (
        Index(
            "ix_tenant_marketing_rec_history_tenant_recorded",
            "tenant_id",
            "recorded_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    recommendation_key: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    reason: Mapped[str] = mapped_column(Text(), nullable=False)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    explanation: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    confidence: Mapped[Decimal] = mapped_column(Numeric(4, 3), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(80), nullable=False)
    rule_version: Mapped[str] = mapped_column(String(20), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantMarketingInsight(Base):
    """Recent explainable insights derived from scores/recommendations/signals."""

    __tablename__ = "tenant_marketing_insights"
    __table_args__ = (
        Index(
            "ix_tenant_marketing_insights_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_tenant_marketing_insights_tenant_kind",
            "tenant_id",
            "kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text(), nullable=False)
    category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    severity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="info", server_default="info",
    )
    explanation: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    evidence: Mapped[dict | None] = mapped_column(JSONB(), nullable=True)
    related_signal_ids: Mapped[list | None] = mapped_column(JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )


class TenantMarketingTrend(Base):
    """Persisted trend points for marketing intelligence history."""

    __tablename__ = "tenant_marketing_trends"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "metric_key",
            "bucket_start",
            name="uq_tenant_marketing_trends_tenant_metric_bucket",
        ),
        Index(
            "ix_tenant_marketing_trends_tenant_metric_bucket",
            "tenant_id",
            "metric_key",
            "bucket_start",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False)
    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer(), nullable=False, default=0, server_default="0")
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False,
    )
