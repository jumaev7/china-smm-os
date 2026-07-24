"""Shared helper: latest normalized metric values for an advertising entity.

Reads the most recent immutable ``TenantAdMetricSnapshot`` for an entity and
returns its ``TenantAdMetricValue`` rows as a ``{metric_key: {...}}`` map. Used
by the diagnostics / pacing / recommendation engines so they observe exactly
what was ingested (never fabricated).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdMetricSnapshot, TenantAdMetricValue


async def latest_snapshot(
    db: AsyncSession,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> TenantAdMetricSnapshot | None:
    return (
        await db.execute(
            select(TenantAdMetricSnapshot)
            .where(
                TenantAdMetricSnapshot.tenant_id == tenant_id,
                TenantAdMetricSnapshot.entity_type == entity_type,
                TenantAdMetricSnapshot.entity_id == entity_id,
            )
            .order_by(TenantAdMetricSnapshot.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def latest_metric_map(
    db: AsyncSession,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
) -> dict[str, dict[str, Any]]:
    """Return ``{metric_key: {"value": Decimal, "currency", "value_type"}}``.

    Empty dict when there is no snapshot yet.
    """
    snapshot = await latest_snapshot(db, tenant_id, entity_type, entity_id)
    if snapshot is None:
        return {}
    rows = list(
        (
            await db.execute(
                select(TenantAdMetricValue).where(
                    TenantAdMetricValue.metric_snapshot_id == snapshot.id
                )
            )
        ).scalars().all()
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        out[row.metric_key] = {
            "value": row.metric_value,
            "currency": row.currency,
            "value_type": row.value_type,
            "provider_metric_key": row.provider_metric_key,
        }
    out["__observed_at__"] = {"value": snapshot.observed_at}  # type: ignore[dict-item]
    return out


def metric_decimal(metric_map: dict[str, dict[str, Any]], key: str) -> Decimal | None:
    entry = metric_map.get(key)
    if not entry:
        return None
    value = entry.get("value")
    return value if isinstance(value, Decimal) else (Decimal(str(value)) if value is not None else None)


__all__ = ["latest_snapshot", "latest_metric_map", "metric_decimal"]
