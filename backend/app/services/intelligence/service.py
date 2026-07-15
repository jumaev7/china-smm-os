"""Read-only Marketing Intelligence service facade."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.intelligence import (
    SCORE_CATEGORIES,
    TenantMarketingInsight,
    TenantMarketingRecommendation,
    TenantMarketingRecommendationHistory,
    TenantMarketingScore,
    TenantMarketingScoreHistory,
    TenantMarketingSignal,
    TenantMarketingTrend,
)
from app.services.intelligence.recommendation_engine import RecommendationEngine
from app.services.intelligence.scoring_engine import ScoringEngine
from app.services.intelligence.store import IntelligenceStore
from app.services.intelligence.types import (
    RECOMMENDATION_ENGINE_VERSION,
    SCORING_ENGINE_VERSION,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return float(value)


class IntelligenceService:
    """Tenant-scoped read API for the Marketing Intelligence Platform."""

    @staticmethod
    async def get_health(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scores = (
            await db.execute(
                select(TenantMarketingScore).where(TenantMarketingScore.tenant_id == tenant_id)
            )
        ).scalars().all()
        if not scores:
            # Bootstrap neutral scores without waiting for events.
            computed = await ScoringEngine.compute_all(
                db, tenant_id, persist=True, record_history=False,
            )
            await RecommendationEngine.compute_all(
                db, tenant_id, scores=computed, persist=True, record_history=False,
            )
            await db.flush()
            scores = (
                await db.execute(
                    select(TenantMarketingScore).where(TenantMarketingScore.tenant_id == tenant_id)
                )
            ).scalars().all()

        score_map = {s.category: s for s in scores}
        overall = score_map.get("overall")
        open_recs = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantMarketingRecommendation).where(
                        TenantMarketingRecommendation.tenant_id == tenant_id,
                        TenantMarketingRecommendation.status == "open",
                    )
                )
            ).scalar_one()
        )
        since = _utcnow() - timedelta(days=7)
        recent_signals = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantMarketingSignal).where(
                        TenantMarketingSignal.tenant_id == tenant_id,
                        TenantMarketingSignal.occurred_at >= since,
                    )
                )
            ).scalar_one()
        )
        categories = []
        for cat in sorted(SCORE_CATEGORIES):
            row = score_map.get(cat)
            if row is None:
                continue
            categories.append({
                "category": cat,
                "score": row.score,
                "weight": _dec(row.weight),
                "scoring_version": row.scoring_version,
            })

        return {
            "overall_score": overall.score if overall else 70,
            "scoring_version": overall.scoring_version if overall else SCORING_ENGINE_VERSION,
            "recommendation_engine_version": RECOMMENDATION_ENGINE_VERSION,
            "open_recommendations": open_recs,
            "recent_signals_7d": recent_signals,
            "categories": categories,
            "computed_at": (overall.computed_at if overall else _utcnow()).isoformat(),
            "status": (
                "critical" if (overall and overall.score < 40)
                else "warning" if (overall and overall.score < 60)
                else "healthy"
            ),
        }

    @staticmethod
    async def list_signals(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        signal_type: str | None = None,
        source: str | None = None,
        severity: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        rows, total = await IntelligenceStore.list_signals(
            db,
            tenant_id,
            signal_type=signal_type,
            source=source,
            severity=severity,
            page=page,
            page_size=page_size,
        )
        return {
            "items": [IntelligenceService._serialize_signal(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    async def list_scores(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        rows = (
            await db.execute(
                select(TenantMarketingScore)
                .where(TenantMarketingScore.tenant_id == tenant_id)
                .order_by(TenantMarketingScore.category.asc())
            )
        ).scalars().all()
        if not rows:
            await ScoringEngine.compute_all(db, tenant_id, persist=True, record_history=False)
            rows = (
                await db.execute(
                    select(TenantMarketingScore)
                    .where(TenantMarketingScore.tenant_id == tenant_id)
                    .order_by(TenantMarketingScore.category.asc())
                )
            ).scalars().all()
        return {
            "scoring_version": SCORING_ENGINE_VERSION,
            "items": [IntelligenceService._serialize_score(r) for r in rows],
        }

    @staticmethod
    async def list_recommendations(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        status: str | None = "open",
        category: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        filters = [TenantMarketingRecommendation.tenant_id == tenant_id]
        if status:
            filters.append(TenantMarketingRecommendation.status == status)
        if category:
            filters.append(TenantMarketingRecommendation.category == category)

        total = int(
            (await db.execute(
                select(func.count()).select_from(TenantMarketingRecommendation).where(*filters)
            )).scalar_one()
        )
        rows = list(
            (
                await db.execute(
                    select(TenantMarketingRecommendation)
                    .where(*filters)
                    .order_by(TenantMarketingRecommendation.updated_at.desc())
                    .offset(max(page - 1, 0) * page_size)
                    .limit(page_size)
                )
            ).scalars().all()
        )
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        rows.sort(key=lambda r: (priority_order.get(r.priority, 9), r.recommendation_key))
        return {
            "items": [IntelligenceService._serialize_recommendation(r) for r in rows],
            "total": total,
            "page": page,
            "page_size": page_size,
            "engine_version": RECOMMENDATION_ENGINE_VERSION,
        }

    @staticmethod
    async def list_insights(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        filters = [TenantMarketingInsight.tenant_id == tenant_id]
        total = int(
            (await db.execute(
                select(func.count()).select_from(TenantMarketingInsight).where(*filters)
            )).scalar_one()
        )
        rows = (
            await db.execute(
                select(TenantMarketingInsight)
                .where(*filters)
                .order_by(TenantMarketingInsight.created_at.desc())
                .offset(max(page - 1, 0) * page_size)
                .limit(page_size)
            )
        ).scalars().all()
        return {
            "items": [
                {
                    "id": str(r.id),
                    "kind": r.kind,
                    "title": r.title,
                    "summary": r.summary,
                    "category": r.category,
                    "severity": r.severity,
                    "explanation": r.explanation,
                    "evidence": r.evidence,
                    "related_signal_ids": r.related_signal_ids,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ],
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    @staticmethod
    async def get_history(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        days: int = 30,
    ) -> dict[str, Any]:
        since = _utcnow() - timedelta(days=max(1, min(days, 365)))
        score_hist = (
            await db.execute(
                select(TenantMarketingScoreHistory)
                .where(
                    TenantMarketingScoreHistory.tenant_id == tenant_id,
                    TenantMarketingScoreHistory.recorded_at >= since,
                )
                .order_by(TenantMarketingScoreHistory.recorded_at.asc())
                .limit(500)
            )
        ).scalars().all()
        rec_hist = (
            await db.execute(
                select(TenantMarketingRecommendationHistory)
                .where(
                    TenantMarketingRecommendationHistory.tenant_id == tenant_id,
                    TenantMarketingRecommendationHistory.recorded_at >= since,
                )
                .order_by(TenantMarketingRecommendationHistory.recorded_at.asc())
                .limit(500)
            )
        ).scalars().all()
        trends = (
            await db.execute(
                select(TenantMarketingTrend)
                .where(
                    TenantMarketingTrend.tenant_id == tenant_id,
                    TenantMarketingTrend.bucket_start >= since,
                )
                .order_by(TenantMarketingTrend.bucket_start.asc())
                .limit(500)
            )
        ).scalars().all()
        return {
            "days": days,
            "scores": [
                {
                    "category": r.category,
                    "score": r.score,
                    "scoring_version": r.scoring_version,
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                    "explanation": r.explanation,
                }
                for r in score_hist
            ],
            "recommendations": [
                {
                    "recommendation_key": r.recommendation_key,
                    "category": r.category,
                    "title": r.title,
                    "priority": r.priority,
                    "status": r.status,
                    "rule_id": r.rule_id,
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                }
                for r in rec_hist
            ],
            "trends": [
                {
                    "metric_key": r.metric_key,
                    "bucket_start": r.bucket_start.isoformat() if r.bucket_start else None,
                    "bucket_end": r.bucket_end.isoformat() if r.bucket_end else None,
                    "value": _dec(r.value),
                    "sample_count": r.sample_count,
                }
                for r in trends
            ],
        }

    @staticmethod
    def _serialize_signal(row: TenantMarketingSignal) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "signal_id": str(row.signal_id),
            "tenant_id": str(row.tenant_id),
            "signal_type": row.signal_type,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "occurred_at": row.occurred_at.isoformat() if row.occurred_at else None,
            "metadata": row.metadata_json,
            "source": row.source,
            "severity": row.severity,
            "confidence": _dec(row.confidence),
            "platform_event_id": str(row.platform_event_id) if row.platform_event_id else None,
            "platform_event_type": row.platform_event_type,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _serialize_score(row: TenantMarketingScore) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "category": row.category,
            "score": row.score,
            "weight": _dec(row.weight),
            "scoring_version": row.scoring_version,
            "explanation": row.explanation,
            "evidence": row.evidence,
            "computed_at": row.computed_at.isoformat() if row.computed_at else None,
        }

    @staticmethod
    def _serialize_recommendation(row: TenantMarketingRecommendation) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "recommendation_key": row.recommendation_key,
            "category": row.category,
            "title": row.title,
            "reason": row.reason,
            "evidence": row.evidence,
            "explanation": row.explanation,
            "confidence": _dec(row.confidence),
            "priority": row.priority,
            "status": row.status,
            "rule_id": row.rule_id,
            "rule_version": row.rule_version,
            "action_url": row.action_url,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
