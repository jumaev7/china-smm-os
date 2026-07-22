"""Performance Intelligence — baselines, classification, recommendations.

Descriptive only. No predictive or causal language.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from statistics import median
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import (
    TenantExternalPublication,
    TenantMeasurementAnomaly,
    TenantPublicationMetricAggregate,
    TenantPublicationMetricSnapshot,
)
from app.services.measurement.limits import MAX_BASELINE_LOOKBACK_DAYS, MIN_BASELINE_SAMPLE_SIZE
from app.services.measurement.metric_catalog import METRIC_CATALOG
from app.services.measurement.schemas import (
    BaselineResult,
    PerformanceClassification,
    RecommendationEvidence,
)

CALCULATION_VERSION = "1.0.0"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def compute_tenant_baseline(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    metric_key: str,
    platform: str | None = None,
    window_key: str = "lifetime",
    lookback_days: int = 90,
) -> BaselineResult:
    lookback_days = min(max(lookback_days, 1), MAX_BASELINE_LOOKBACK_DAYS)
    since = utcnow() - timedelta(days=lookback_days)

    pub_filters = [
        TenantExternalPublication.tenant_id == tenant_id,
        TenantExternalPublication.published_at >= since,
    ]
    if platform:
        pub_filters.append(TenantExternalPublication.platform == platform)

    pubs = list(
        (await db.execute(select(TenantExternalPublication).where(*pub_filters))).scalars().all()
    )
    values: list[Decimal] = []
    for pub in pubs:
        agg = (
            await db.execute(
                select(TenantPublicationMetricAggregate).where(
                    TenantPublicationMetricAggregate.tenant_id == tenant_id,
                    TenantPublicationMetricAggregate.external_publication_id == pub.id,
                    TenantPublicationMetricAggregate.metric_key == metric_key,
                    TenantPublicationMetricAggregate.window_key == window_key,
                    TenantPublicationMetricAggregate.calculation_version == CALCULATION_VERSION,
                )
            )
        ).scalar_one_or_none()
        if agg is not None:
            values.append(agg.metric_value)

    sufficient = len(values) >= MIN_BASELINE_SAMPLE_SIZE
    if not values:
        return BaselineResult(
            metric_key=metric_key,
            platform=platform,
            sample_size=0,
            median=None,
            mean=None,
            p75=None,
            lookback_days=lookback_days,
            sufficient=False,
        )

    sorted_vals = sorted(values)
    med = Decimal(str(median(sorted_vals)))
    mean = (sum(sorted_vals) / Decimal(len(sorted_vals))).quantize(Decimal("0.0001"))
    p75_idx = min(int(len(sorted_vals) * 0.75), len(sorted_vals) - 1)
    p75 = sorted_vals[p75_idx]

    return BaselineResult(
        metric_key=metric_key,
        platform=platform,
        sample_size=len(values),
        median=med if sufficient else None,
        mean=mean if sufficient else None,
        p75=p75 if sufficient else None,
        lookback_days=lookback_days,
        sufficient=sufficient,
    )


async def classify_relative_performance(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    publication_id: UUID,
    metric_key: str,
    window_key: str = "lifetime",
) -> PerformanceClassification:
    pub = (
        await db.execute(
            select(TenantExternalPublication).where(
                TenantExternalPublication.id == publication_id,
                TenantExternalPublication.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if pub is None:
        return PerformanceClassification(
            entity_type="external_publication",
            entity_id=str(publication_id),
            metric_key=metric_key,
            classification="insufficient_data",
            value=None,
            baseline=None,
            delta_ratio=None,
            evidence={"reason": "publication_not_found"},
        )

    agg = (
        await db.execute(
            select(TenantPublicationMetricAggregate).where(
                TenantPublicationMetricAggregate.tenant_id == tenant_id,
                TenantPublicationMetricAggregate.external_publication_id == publication_id,
                TenantPublicationMetricAggregate.metric_key == metric_key,
                TenantPublicationMetricAggregate.window_key == window_key,
                TenantPublicationMetricAggregate.calculation_version == CALCULATION_VERSION,
            )
        )
    ).scalar_one_or_none()

    baseline = await compute_tenant_baseline(
        db, tenant_id, metric_key=metric_key, platform=pub.platform, window_key=window_key,
    )

    if agg is None or not baseline.sufficient or baseline.median is None:
        return PerformanceClassification(
            entity_type="external_publication",
            entity_id=str(publication_id),
            metric_key=metric_key,
            classification="insufficient_data",
            value=agg.metric_value if agg else None,
            baseline=baseline,
            delta_ratio=None,
            evidence={
                "sample_size": baseline.sample_size,
                "min_sample_size": MIN_BASELINE_SAMPLE_SIZE,
                "window_key": window_key,
                "lookback_days": baseline.lookback_days,
                "classification_rule": "requires_baseline_median_and_publication_value",
            },
        )

    value = agg.metric_value
    med = baseline.median
    if med == 0:
        classification = "above_baseline" if value > 0 else "near_baseline"
        delta = None
    else:
        delta = ((value - med) / med).quantize(Decimal("0.0001"))
        if delta <= Decimal("-0.20"):
            classification = "below_baseline"
        elif delta >= Decimal("0.20"):
            classification = "above_baseline"
        else:
            classification = "near_baseline"

    return PerformanceClassification(
        entity_type="external_publication",
        entity_id=str(publication_id),
        metric_key=metric_key,
        classification=classification,
        value=value,
        baseline=baseline,
        delta_ratio=delta,
        evidence={
            "baseline_median": str(med),
            "sample_size": baseline.sample_size,
            "window_key": window_key,
            "lookback_days": baseline.lookback_days,
            "classification_rule": "±20% of tenant median",
            "confidence": "descriptive_only",
        },
    )


async def generate_recommendations(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    limit: int = 20,
) -> list[RecommendationEvidence]:
    """Deterministic, evidence-backed recommendations — no causal claims."""
    recs: list[RecommendationEvidence] = []

    stale = list(
        (
            await db.execute(
                select(TenantExternalPublication)
                .where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.freshness_status == "stale",
                )
                .limit(10)
            )
        ).scalars().all()
    )
    if stale:
        recs.append(
            RecommendationEvidence(
                recommendation_key="refresh_stale_metrics",
                title="Refresh stale platform metrics",
                reason="One or more publications have observations older than the expected collection cadence.",
                evidence={
                    "stale_count": len(stale),
                    "publication_ids": [str(p.id) for p in stale[:5]],
                    "freshness": "stale",
                },
                confidence=Decimal("1.000"),
                metric_keys=[],
                caveats=["Refreshing collects new observations; it does not change past snapshots."],
            )
        )

    unsupported = list(
        (
            await db.execute(
                select(TenantExternalPublication)
                .where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.freshness_status == "unsupported",
                )
                .limit(5)
            )
        ).scalars().all()
    )
    if unsupported:
        recs.append(
            RecommendationEvidence(
                recommendation_key="unsupported_platform_metrics",
                title="Some platforms cannot supply live post-level metrics",
                reason="Adapter capability reporting indicates live metrics are unsupported for these publications.",
                evidence={
                    "count": len(unsupported),
                    "platforms": sorted({p.platform for p in unsupported}),
                },
                confidence=Decimal("1.000"),
                metric_keys=[],
                caveats=["No fabricated metrics are generated for unsupported platforms."],
            )
        )

    anomalies = list(
        (
            await db.execute(
                select(TenantMeasurementAnomaly)
                .where(
                    TenantMeasurementAnomaly.tenant_id == tenant_id,
                    TenantMeasurementAnomaly.status == "open",
                )
                .limit(10)
            )
        ).scalars().all()
    )
    decreases = [a for a in anomalies if a.anomaly_key == "cumulative_metric_decreased"]
    if decreases:
        recs.append(
            RecommendationEvidence(
                recommendation_key="review_metric_decrease",
                title="Review a publication with an abnormal metric decrease",
                reason="A cumulative metric decreased between immutable snapshots — may indicate provider correction.",
                evidence={
                    "anomaly_count": len(decreases),
                    "anomaly_keys": ["cumulative_metric_decreased"],
                    "metric_keys": list({a.metric_key for a in decreases if a.metric_key}),
                },
                confidence=Decimal("0.900"),
                metric_keys=[a.metric_key for a in decreases if a.metric_key][:5],
                caveats=["Raw observations are preserved; decrease is not deleted."],
            )
        )

    unattributed = list(
        (
            await db.execute(
                select(TenantExternalPublication)
                .where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.campaign_id.is_(None),
                )
                .limit(10)
            )
        ).scalars().all()
    )
    if unattributed:
        recs.append(
            RecommendationEvidence(
                recommendation_key="complete_campaign_attribution",
                title="Complete campaign attribution for unattributed publications",
                reason="Publications without campaign linkage cannot contribute to campaign KPI progress.",
                evidence={
                    "unattributed_count": len(unattributed),
                    "attribution_confidence": "0.0",
                },
                confidence=Decimal("1.000"),
                metric_keys=[],
                caveats=["Manual linking is recorded separately and does not rewrite publish-time freeze."],
            )
        )

    # Below-baseline sample (descriptive).
    sample_pubs = list(
        (
            await db.execute(
                select(TenantExternalPublication)
                .where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.last_metric_at.is_not(None),
                )
                .limit(5)
            )
        ).scalars().all()
    )
    for pub in sample_pubs:
        classification = await classify_relative_performance(
            db, tenant_id, publication_id=pub.id, metric_key="engagements", window_key="lifetime",
        )
        if classification.classification == "below_baseline":
            recs.append(
                RecommendationEvidence(
                    recommendation_key=f"below_baseline_{pub.id}",
                    title="Publication below tenant baseline (descriptive)",
                    reason="Observed engagements are at least 20% below the tenant median for this platform.",
                    evidence={
                        "external_publication_id": str(pub.id),
                        "classification": classification.classification,
                        "metric_key": "engagements",
                        "value": str(classification.value) if classification.value is not None else None,
                        "baseline_median": str(classification.baseline.median) if classification.baseline and classification.baseline.median is not None else None,
                        "sample_size": classification.baseline.sample_size if classification.baseline else 0,
                        "window": "lifetime",
                        "freshness": pub.freshness_status,
                    },
                    confidence=Decimal("0.800"),
                    metric_keys=["engagements"],
                    caveats=[
                        "Descriptive comparison only — not a prediction or causal claim.",
                        "May be confounded by audience size, timing, and creative differences.",
                    ],
                )
            )
            break
        if classification.classification == "insufficient_data":
            recs.append(
                RecommendationEvidence(
                    recommendation_key="collect_more_before_compare",
                    title="Collect more observations before comparing performance",
                    reason="Tenant baseline sample size is below the minimum required for relative classification.",
                    evidence={
                        "sample_size": classification.baseline.sample_size if classification.baseline else 0,
                        "min_sample_size": MIN_BASELINE_SAMPLE_SIZE,
                        "metric_key": "engagements",
                    },
                    confidence=Decimal("1.000"),
                    metric_keys=["engagements"],
                    caveats=["Do not evaluate relative performance until the sample threshold is met."],
                )
            )
            break

    return recs[:limit]


__all__ = [
    "compute_tenant_baseline",
    "classify_relative_performance",
    "generate_recommendations",
]
