"""Deterministic data-quality anomaly checks for metric snapshots.

Anomalies are technical warnings. ``extreme_jump`` is never interpreted as
viral performance — it flags an abrupt numerical change for operator review.
Raw observations are always preserved.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import (
    ANOMALY_KEYS,
    TenantMeasurementAnomaly,
    TenantPublicationMetricSnapshot,
    TenantPublicationMetricValue,
)
from app.services.measurement.metric_catalog import METRIC_CATALOG

# Jump threshold: new cumulative value > previous * factor (and absolute delta).
_EXTREME_JUMP_FACTOR = Decimal("10")
_EXTREME_JUMP_MIN_DELTA = Decimal("1000")


def _ratio_out_of_range(value: Decimal) -> bool:
    return value < Decimal("0") or value > Decimal("1")


async def evaluate_snapshot_anomalies(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    external_publication_id: UUID,
    snapshot: TenantPublicationMetricSnapshot,
    values: list[TenantPublicationMetricValue],
    previous_snapshot: TenantPublicationMetricSnapshot | None,
    previous_values: list[TenantPublicationMetricValue] | None,
) -> list[TenantMeasurementAnomaly]:
    """Run deterministic checks; persist open anomalies; never delete data."""
    created: list[TenantMeasurementAnomaly] = []
    prev_map = {
        v.metric_key: v for v in (previous_values or [])
        if v.normalization_status in {"normalized", "derived", "provider_native"}
    }

    # Timestamp regressions.
    if (
        previous_snapshot is not None
        and snapshot.observed_at < previous_snapshot.observed_at
    ):
        created.append(
            await _open(
                db,
                tenant_id=tenant_id,
                external_publication_id=external_publication_id,
                snapshot_id=snapshot.id,
                anomaly_key="snapshot_time_regressed",
                severity="warning",
                metric_key=None,
                evidence={
                    "previous_observed_at": previous_snapshot.observed_at.isoformat(),
                    "observed_at": snapshot.observed_at.isoformat(),
                },
            )
        )

    if (
        previous_snapshot is not None
        and snapshot.provider_data_timestamp is not None
        and previous_snapshot.provider_data_timestamp is not None
        and snapshot.provider_data_timestamp < previous_snapshot.provider_data_timestamp
    ):
        created.append(
            await _open(
                db,
                tenant_id=tenant_id,
                external_publication_id=external_publication_id,
                snapshot_id=snapshot.id,
                anomaly_key="provider_timestamp_regressed",
                severity="warning",
                metric_key=None,
                evidence={
                    "previous_provider_data_timestamp": previous_snapshot.provider_data_timestamp.isoformat(),
                    "provider_data_timestamp": snapshot.provider_data_timestamp.isoformat(),
                },
            )
        )

    for value in values:
        metric_key = value.metric_key
        definition = METRIC_CATALOG.get(metric_key)

        if value.metric_value < 0:
            created.append(
                await _open(
                    db,
                    tenant_id=tenant_id,
                    external_publication_id=external_publication_id,
                    snapshot_id=snapshot.id,
                    anomaly_key="negative_metric",
                    severity="error",
                    metric_key=metric_key,
                    evidence={"value": str(value.metric_value)},
                )
            )

        if value.value_type == "ratio" and _ratio_out_of_range(value.metric_value):
            created.append(
                await _open(
                    db,
                    tenant_id=tenant_id,
                    external_publication_id=external_publication_id,
                    snapshot_id=snapshot.id,
                    anomaly_key="ratio_out_of_range",
                    severity="warning",
                    metric_key=metric_key,
                    evidence={"value": str(value.metric_value)},
                )
            )

        if definition is not None and value.value_type != definition.value_type:
            created.append(
                await _open(
                    db,
                    tenant_id=tenant_id,
                    external_publication_id=external_publication_id,
                    snapshot_id=snapshot.id,
                    anomaly_key="unexpected_metric_type",
                    severity="warning",
                    metric_key=metric_key,
                    evidence={
                        "expected": definition.value_type,
                        "actual": value.value_type,
                    },
                )
            )

        prev = prev_map.get(metric_key)
        if prev is None:
            continue

        if (
            value.aggregation_type == "cumulative"
            and value.metric_value < prev.metric_value
        ):
            created.append(
                await _open(
                    db,
                    tenant_id=tenant_id,
                    external_publication_id=external_publication_id,
                    snapshot_id=snapshot.id,
                    anomaly_key="cumulative_metric_decreased",
                    severity="warning",
                    metric_key=metric_key,
                    evidence={
                        "previous": str(prev.metric_value),
                        "current": str(value.metric_value),
                        "note": "Raw observation preserved; decrease may indicate provider correction.",
                    },
                )
            )

        if (
            value.aggregation_type == "cumulative"
            and prev.metric_value > 0
            and value.metric_value > prev.metric_value * _EXTREME_JUMP_FACTOR
            and (value.metric_value - prev.metric_value) >= _EXTREME_JUMP_MIN_DELTA
        ):
            created.append(
                await _open(
                    db,
                    tenant_id=tenant_id,
                    external_publication_id=external_publication_id,
                    snapshot_id=snapshot.id,
                    anomaly_key="extreme_jump",
                    severity="info",
                    metric_key=metric_key,
                    evidence={
                        "previous": str(prev.metric_value),
                        "current": str(value.metric_value),
                        "factor_threshold": str(_EXTREME_JUMP_FACTOR),
                        "note": "Technical data-quality warning — not a claim of viral performance.",
                    },
                )
            )

    await db.flush()
    return created


async def _open(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    external_publication_id: UUID,
    snapshot_id: UUID,
    anomaly_key: str,
    severity: str,
    metric_key: str | None,
    evidence: dict[str, Any],
) -> TenantMeasurementAnomaly:
    assert anomaly_key in ANOMALY_KEYS
    # Deduplicate open anomalies of the same key+metric for the same publication.
    existing = (
        await db.execute(
            select(TenantMeasurementAnomaly).where(
                TenantMeasurementAnomaly.tenant_id == tenant_id,
                TenantMeasurementAnomaly.external_publication_id == external_publication_id,
                TenantMeasurementAnomaly.anomaly_key == anomaly_key,
                TenantMeasurementAnomaly.metric_key == metric_key,
                TenantMeasurementAnomaly.status == "open",
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.metric_snapshot_id = snapshot_id
        existing.evidence = evidence
        existing.severity = severity
        return existing

    row = TenantMeasurementAnomaly(
        id=uuid4(),
        tenant_id=tenant_id,
        external_publication_id=external_publication_id,
        metric_snapshot_id=snapshot_id,
        anomaly_key=anomaly_key,
        severity=severity,
        metric_key=metric_key,
        evidence=evidence,
        status="open",
    )
    db.add(row)
    return row


__all__ = ["evaluate_snapshot_anomalies"]
