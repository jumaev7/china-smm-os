"""Intelligence knowledge store — persist immutable signals and intelligence rows."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import (
    TenantMarketingInsight,
    TenantMarketingRecommendation,
    TenantMarketingRecommendationHistory,
    TenantMarketingScore,
    TenantMarketingScoreHistory,
    TenantMarketingSignal,
    TenantMarketingTrend,
)
from app.services.intelligence.types import (
    NormalizedSignal,
    RecommendationResult,
    ScoreResult,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class IntelligenceStore:
    """Append/update intelligence data with tenant isolation."""

    @staticmethod
    async def insert_signal(
        db: AsyncSession,
        signal: NormalizedSignal,
    ) -> TenantMarketingSignal | None:
        """Insert an immutable signal. Returns None if duplicate (idempotent)."""
        if await IntelligenceStore.signal_exists(db, signal.tenant_id, signal.signal_id):
            return None
        row = TenantMarketingSignal(
            signal_id=signal.signal_id,
            tenant_id=signal.tenant_id,
            signal_type=signal.signal_type,
            entity_type=signal.entity_type,
            entity_id=signal.entity_id,
            occurred_at=signal.occurred_at,
            metadata_json=signal.metadata or None,
            source=signal.source,
            severity=signal.severity,
            confidence=signal.confidence,
            platform_event_id=signal.platform_event_id,
            platform_event_type=signal.platform_event_type,
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def signal_exists(db: AsyncSession, tenant_id: UUID, signal_id: UUID) -> bool:
        result = await db.execute(
            select(TenantMarketingSignal.id).where(
                TenantMarketingSignal.tenant_id == tenant_id,
                TenantMarketingSignal.signal_id == signal_id,
            ).limit(1)
        )
        return result.scalar_one_or_none() is not None

    @staticmethod
    async def list_signals(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        signal_type: str | None = None,
        source: str | None = None,
        severity: str | None = None,
        since: datetime | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[TenantMarketingSignal], int]:
        filters = [TenantMarketingSignal.tenant_id == tenant_id]
        if signal_type:
            filters.append(TenantMarketingSignal.signal_type == signal_type)
        if source:
            filters.append(TenantMarketingSignal.source == source)
        if severity:
            filters.append(TenantMarketingSignal.severity == severity)
        if since:
            filters.append(TenantMarketingSignal.occurred_at >= since)

        count_q = select(func.count()).select_from(TenantMarketingSignal).where(*filters)
        total = int((await db.execute(count_q)).scalar_one())

        q: Select = (
            select(TenantMarketingSignal)
            .where(*filters)
            .order_by(TenantMarketingSignal.occurred_at.desc())
            .offset(max(page - 1, 0) * page_size)
            .limit(page_size)
        )
        rows = list((await db.execute(q)).scalars().all())
        return rows, total

    @staticmethod
    async def count_signals_by_type(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        since: datetime,
        signal_types: list[str] | None = None,
    ) -> dict[str, int]:
        filters = [
            TenantMarketingSignal.tenant_id == tenant_id,
            TenantMarketingSignal.occurred_at >= since,
        ]
        if signal_types:
            filters.append(TenantMarketingSignal.signal_type.in_(signal_types))
        q = (
            select(TenantMarketingSignal.signal_type, func.count())
            .where(*filters)
            .group_by(TenantMarketingSignal.signal_type)
        )
        rows = (await db.execute(q)).all()
        return {str(signal_type): int(count) for signal_type, count in rows}

    @staticmethod
    async def upsert_score(
        db: AsyncSession,
        tenant_id: UUID,
        result: ScoreResult,
        *,
        record_history: bool = True,
    ) -> TenantMarketingScore:
        existing = (
            await db.execute(
                select(TenantMarketingScore).where(
                    TenantMarketingScore.tenant_id == tenant_id,
                    TenantMarketingScore.category == result.category,
                )
            )
        ).scalar_one_or_none()

        now = _utcnow()
        if existing is None:
            existing = TenantMarketingScore(
                tenant_id=tenant_id,
                category=result.category,
                score=result.score,
                weight=result.weight,
                scoring_version=result.scoring_version,
                explanation=result.explanation,
                evidence=result.evidence,
                computed_at=now,
            )
            db.add(existing)
        else:
            existing.score = result.score
            existing.weight = result.weight
            existing.scoring_version = result.scoring_version
            existing.explanation = result.explanation
            existing.evidence = result.evidence
            existing.computed_at = now

        await db.flush()

        if record_history:
            db.add(
                TenantMarketingScoreHistory(
                    tenant_id=tenant_id,
                    category=result.category,
                    score=result.score,
                    weight=result.weight,
                    scoring_version=result.scoring_version,
                    explanation=result.explanation,
                    evidence=result.evidence,
                    recorded_at=now,
                )
            )
            await db.flush()
        return existing

    @staticmethod
    async def upsert_recommendation(
        db: AsyncSession,
        tenant_id: UUID,
        result: RecommendationResult,
        *,
        record_history: bool = True,
    ) -> TenantMarketingRecommendation:
        existing = (
            await db.execute(
                select(TenantMarketingRecommendation).where(
                    TenantMarketingRecommendation.tenant_id == tenant_id,
                    TenantMarketingRecommendation.recommendation_key == result.recommendation_key,
                )
            )
        ).scalar_one_or_none()

        now = _utcnow()
        if existing is None:
            existing = TenantMarketingRecommendation(
                tenant_id=tenant_id,
                recommendation_key=result.recommendation_key,
                category=result.category,
                title=result.title,
                reason=result.reason,
                evidence=result.evidence,
                explanation=result.explanation,
                confidence=result.confidence,
                priority=result.priority,
                status="open",
                rule_id=result.rule_id,
                rule_version=result.rule_version,
                action_url=result.action_url,
            )
            db.add(existing)
        else:
            existing.category = result.category
            existing.title = result.title
            existing.reason = result.reason
            existing.evidence = result.evidence
            existing.explanation = result.explanation
            existing.confidence = result.confidence
            existing.priority = result.priority
            existing.rule_id = result.rule_id
            existing.rule_version = result.rule_version
            existing.action_url = result.action_url
            if existing.status == "resolved":
                existing.status = "open"

        await db.flush()

        if record_history:
            db.add(
                TenantMarketingRecommendationHistory(
                    tenant_id=tenant_id,
                    recommendation_key=result.recommendation_key,
                    category=result.category,
                    title=result.title,
                    reason=result.reason,
                    evidence=result.evidence,
                    explanation=result.explanation,
                    confidence=result.confidence,
                    priority=result.priority,
                    status=existing.status,
                    rule_id=result.rule_id,
                    rule_version=result.rule_version,
                    recorded_at=now,
                )
            )
            await db.flush()
        return existing

    @staticmethod
    async def resolve_stale_recommendations(
        db: AsyncSession,
        tenant_id: UUID,
        active_keys: set[str],
    ) -> None:
        rows = (
            await db.execute(
                select(TenantMarketingRecommendation).where(
                    TenantMarketingRecommendation.tenant_id == tenant_id,
                    TenantMarketingRecommendation.status == "open",
                )
            )
        ).scalars().all()
        for row in rows:
            if row.recommendation_key not in active_keys:
                row.status = "resolved"
        await db.flush()

    @staticmethod
    async def add_insight(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        kind: str,
        title: str,
        summary: str,
        category: str | None = None,
        severity: str = "info",
        explanation: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        related_signal_ids: list[str] | None = None,
    ) -> TenantMarketingInsight:
        row = TenantMarketingInsight(
            tenant_id=tenant_id,
            kind=kind,
            title=title,
            summary=summary,
            category=category,
            severity=severity,
            explanation=explanation,
            evidence=evidence,
            related_signal_ids=related_signal_ids,
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    async def upsert_trend(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        metric_key: str,
        bucket_start: datetime,
        bucket_end: datetime,
        value: Decimal | float | int,
        sample_count: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> TenantMarketingTrend:
        existing = (
            await db.execute(
                select(TenantMarketingTrend).where(
                    TenantMarketingTrend.tenant_id == tenant_id,
                    TenantMarketingTrend.metric_key == metric_key,
                    TenantMarketingTrend.bucket_start == bucket_start,
                )
            )
        ).scalar_one_or_none()
        dec_value = Decimal(str(value))
        if existing is None:
            existing = TenantMarketingTrend(
                tenant_id=tenant_id,
                metric_key=metric_key,
                bucket_start=bucket_start,
                bucket_end=bucket_end,
                value=dec_value,
                sample_count=sample_count,
                metadata_json=metadata,
            )
            db.add(existing)
        else:
            existing.bucket_end = bucket_end
            existing.value = dec_value
            existing.sample_count = sample_count
            existing.metadata_json = metadata
        await db.flush()
        return existing
