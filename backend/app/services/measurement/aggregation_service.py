"""Deterministic publication metric aggregation.

Supports latest cumulative, interval deltas, and first-N-hour windows.
Missing observations are never interpolated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import (
    CALCULATION_VERSION,
    WINDOW_KEYS,
    TenantPublicationMetricAggregate,
    TenantPublicationMetricSnapshot,
    TenantPublicationMetricValue,
)
from app.services.measurement.freshness_service import compute_freshness
from app.services.measurement.metric_catalog import METRIC_CATALOG
from app.services.measurement.schemas import AggregateResult

_WINDOW_DURATIONS = {
    "24h": timedelta(hours=24),
    "72h": timedelta(hours=72),
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "30d": timedelta(days=30),
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def _load_snapshots_with_values(
    db: AsyncSession,
    tenant_id: UUID,
    external_publication_id: UUID,
) -> list[tuple[TenantPublicationMetricSnapshot, list[TenantPublicationMetricValue]]]:
    snapshots = list(
        (
            await db.execute(
                select(TenantPublicationMetricSnapshot)
                .where(
                    TenantPublicationMetricSnapshot.tenant_id == tenant_id,
                    TenantPublicationMetricSnapshot.external_publication_id == external_publication_id,
                    TenantPublicationMetricSnapshot.status.in_(["complete", "partial"]),
                )
                .order_by(TenantPublicationMetricSnapshot.observed_at.asc())
            )
        ).scalars().all()
    )
    result: list[tuple[TenantPublicationMetricSnapshot, list[TenantPublicationMetricValue]]] = []
    for snap in snapshots:
        values = list(
            (
                await db.execute(
                    select(TenantPublicationMetricValue).where(
                        TenantPublicationMetricValue.metric_snapshot_id == snap.id,
                        TenantPublicationMetricValue.tenant_id == tenant_id,
                    )
                )
            ).scalars().all()
        )
        result.append((snap, values))
    return result


def _latest_cumulative(
    series: list[tuple[TenantPublicationMetricSnapshot, list[TenantPublicationMetricValue]]],
    metric_key: str,
) -> AggregateResult | None:
    for snap, values in reversed(series):
        for v in values:
            if v.metric_key == metric_key:
                return AggregateResult(
                    window_key="lifetime",
                    metric_key=metric_key,
                    metric_value=v.metric_value,
                    calculation_method="latest_cumulative",
                    freshness_status="unavailable",
                    confidence=Decimal("1.000"),
                    source_snapshot_ids=[snap.id],
                    window_start=None,
                    window_end=snap.observed_at,
                )
    return None


def _window_growth(
    series: list[tuple[TenantPublicationMetricSnapshot, list[TenantPublicationMetricValue]]],
    metric_key: str,
    window_key: str,
    *,
    published_at: datetime | None,
) -> AggregateResult | None:
    """First-N-hour growth: value at latest snapshot within window after publish.

    Requires at least one observation inside the window. No interpolation.
    """
    duration = _WINDOW_DURATIONS.get(window_key)
    if duration is None or published_at is None:
        return None

    window_end = published_at + duration
    in_window: list[tuple[TenantPublicationMetricSnapshot, TenantPublicationMetricValue]] = []
    for snap, values in series:
        if snap.observed_at < published_at or snap.observed_at > window_end:
            continue
        for v in values:
            if v.metric_key == metric_key:
                in_window.append((snap, v))
                break

    if not in_window:
        return None

    # Prefer the latest observation still inside the window.
    snap, value = in_window[-1]
    # If we have an observation at/near publish, compute delta; else report absolute.
    first_snap, first_value = in_window[0]
    if first_snap.id != snap.id and value.aggregation_type == "cumulative":
        delta = value.metric_value - first_value.metric_value
        method = "window_delta"
        metric_value = delta if delta >= 0 else value.metric_value
        source_ids = [first_snap.id, snap.id]
    else:
        method = "window_latest"
        metric_value = value.metric_value
        source_ids = [snap.id]

    return AggregateResult(
        window_key=window_key,
        metric_key=metric_key,
        metric_value=metric_value,
        calculation_method=method,
        freshness_status="unavailable",
        confidence=Decimal("1.000") if snap.observed_at >= window_end - timedelta(hours=1) else Decimal("0.800"),
        source_snapshot_ids=source_ids,
        window_start=published_at,
        window_end=window_end,
    )


async def calculate_publication_aggregates(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    external_publication_id: UUID,
    published_at: datetime | None,
    last_metric_at: datetime | None,
    freshness_hint: str | None = None,
    metric_keys: list[str] | None = None,
) -> list[TenantPublicationMetricAggregate]:
    """Recompute and upsert aggregates for one publication. No interpolation."""
    series = await _load_snapshots_with_values(db, tenant_id, external_publication_id)
    if not series:
        return []

    keys = metric_keys or sorted({
        v.metric_key
        for _, values in series
        for v in values
        if not v.metric_key.startswith("provider:")
    })

    freshness = freshness_hint or compute_freshness(
        last_metric_at=last_metric_at,
        published_at=published_at,
    ).status

    upserted: list[TenantPublicationMetricAggregate] = []
    for metric_key in keys:
        results: list[AggregateResult] = []
        latest = _latest_cumulative(series, metric_key)
        if latest is not None:
            latest.freshness_status = freshness
            results.append(latest)

        for window_key in ("24h", "72h", "7d", "14d", "30d"):
            growth = _window_growth(series, metric_key, window_key, published_at=published_at)
            if growth is not None:
                growth.freshness_status = freshness
                results.append(growth)

        for agg in results:
            if agg.window_key not in WINDOW_KEYS:
                continue
            if agg.metric_value is None:
                continue
            existing = (
                await db.execute(
                    select(TenantPublicationMetricAggregate).where(
                        TenantPublicationMetricAggregate.tenant_id == tenant_id,
                        TenantPublicationMetricAggregate.external_publication_id == external_publication_id,
                        TenantPublicationMetricAggregate.window_key == agg.window_key,
                        TenantPublicationMetricAggregate.metric_key == metric_key,
                        TenantPublicationMetricAggregate.calculation_version == CALCULATION_VERSION,
                    )
                )
            ).scalar_one_or_none()

            if existing is not None:
                existing.metric_value = agg.metric_value
                existing.calculation_method = agg.calculation_method
                existing.freshness_status = agg.freshness_status
                existing.confidence = agg.confidence
                existing.source_snapshot_ids = [str(i) for i in agg.source_snapshot_ids]
                existing.window_start = agg.window_start
                existing.window_end = agg.window_end
                existing.calculated_at = utcnow()
                upserted.append(existing)
            else:
                row = TenantPublicationMetricAggregate(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    external_publication_id=external_publication_id,
                    window_key=agg.window_key,
                    window_start=agg.window_start,
                    window_end=agg.window_end,
                    metric_key=metric_key,
                    metric_value=agg.metric_value,
                    calculation_method=agg.calculation_method,
                    calculation_version=CALCULATION_VERSION,
                    freshness_status=agg.freshness_status,
                    confidence=agg.confidence,
                    source_snapshot_ids=[str(i) for i in agg.source_snapshot_ids],
                    calculated_at=utcnow(),
                )
                db.add(row)
                upserted.append(row)

    await db.flush()
    return upserted


async def get_publication_aggregates(
    db: AsyncSession,
    tenant_id: UUID,
    external_publication_id: UUID,
    *,
    window_key: str | None = None,
) -> list[TenantPublicationMetricAggregate]:
    filters = [
        TenantPublicationMetricAggregate.tenant_id == tenant_id,
        TenantPublicationMetricAggregate.external_publication_id == external_publication_id,
        TenantPublicationMetricAggregate.calculation_version == CALCULATION_VERSION,
    ]
    if window_key:
        filters.append(TenantPublicationMetricAggregate.window_key == window_key)
    return list(
        (
            await db.execute(
                select(TenantPublicationMetricAggregate)
                .where(*filters)
                .order_by(TenantPublicationMetricAggregate.metric_key.asc())
            )
        ).scalars().all()
    )


def interval_delta(
    earlier: Decimal,
    later: Decimal,
    *,
    aggregation_type: str,
) -> Decimal | None:
    """Delta between two cumulative observations. Never invents missing data."""
    if aggregation_type != "cumulative":
        return None
    return later - earlier


__all__ = [
    "calculate_publication_aggregates",
    "get_publication_aggregates",
    "interval_delta",
]
