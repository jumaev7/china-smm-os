"""Insights / metric ingestion lifecycle (read-only).

Fetches provider-native insights per entity level, normalizes them, and persists
**immutable** metric snapshots plus their metric values and conversion
breakdowns. Recomputes per-entity ``lifetime`` aggregates that the read layer
serves from. Snapshots are idempotent via a content fingerprint.

After metric aggregates land, this orchestrator triggers the pacing, delivery,
and creative-fatigue evaluators (best-effort) and refreshes account freshness.

Emits ``advertising.insights_ingested`` / ``advertising.insights_failed``.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    AD_CALCULATION_VERSION,
    TenantAd,
    TenantAdCampaign,
    TenantAdConversionBreakdown,
    TenantAdGroup,
    TenantAdMetricAggregate,
    TenantAdMetricIngestionRun,
    TenantAdMetricSnapshot,
    TenantAdMetricValue,
    TenantAdvertisingAccount,
)
from app.services.advertising_intelligence import metric_normalizer
from app.services.advertising_intelligence.errors import (
    AdAccountNotFoundError,
    AdMetricsUnsupportedError,
)
from app.services.advertising_intelligence.limits import (
    MAX_CONVERSION_BREAKDOWNS_PER_SNAPSHOT,
    MAX_METRIC_VALUES_PER_SNAPSHOT,
)
from app.services.advertising_intelligence.providers import get_adapter
from app.services.advertising_intelligence.schemas import (
    EntityInsightResult,
    InsightsFetchRequest,
)
from app.services.automation_domain_events import emit_domain_event

_LEVELS = ("campaign", "ad_group", "ad")
_LIFETIME_WINDOW = "lifetime"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _connection_status(account: TenantAdvertisingAccount) -> str:
    if account.is_mock or account.provider == "mock":
        return "mock"
    return account.connection_status or "unknown"


async def _load_account(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> TenantAdvertisingAccount:
    account = (
        await db.execute(
            select(TenantAdvertisingAccount).where(
                TenantAdvertisingAccount.id == account_id,
                TenantAdvertisingAccount.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise AdAccountNotFoundError("advertising account not found")
    return account


async def _entity_index(db: AsyncSession, tenant_id: UUID, account_id: UUID, level: str) -> dict[str, UUID]:
    """provider_entity_id -> internal id for a given level."""
    if level == "campaign":
        model, prov_col = TenantAdCampaign, TenantAdCampaign.provider_campaign_id
    elif level == "ad_group":
        model, prov_col = TenantAdGroup, TenantAdGroup.provider_ad_group_id
    else:
        model, prov_col = TenantAd, TenantAd.provider_ad_id
    rows = list(
        (
            await db.execute(
                select(model).where(
                    model.tenant_id == tenant_id,
                    model.advertising_account_id == account_id,
                )
            )
        ).scalars().all()
    )
    provider_attr = {
        "campaign": "provider_campaign_id",
        "ad_group": "provider_ad_group_id",
        "ad": "provider_ad_id",
    }[level]
    return {getattr(r, provider_attr): r.id for r in rows}


def _snapshot_fingerprint(entity_type: str, entity_id: UUID, result: EntityInsightResult) -> str:
    metric_part = sorted((m.provider_metric_key, str(m.value)) for m in result.metrics)
    payload = json.dumps(
        {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "date_start": result.date_start,
            "date_stop": result.date_stop,
            "metrics": metric_part,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def _snapshot_exists(db: AsyncSession, tenant_id: UUID, entity_type: str, entity_id: UUID, fingerprint: str) -> bool:
    existing = (
        await db.execute(
            select(TenantAdMetricSnapshot.id).where(
                TenantAdMetricSnapshot.tenant_id == tenant_id,
                TenantAdMetricSnapshot.entity_type == entity_type,
                TenantAdMetricSnapshot.entity_id == entity_id,
                TenantAdMetricSnapshot.snapshot_fingerprint == fingerprint,
            )
        )
    ).scalar_one_or_none()
    return existing is not None


async def _upsert_aggregate(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    entity_type: str,
    entity_id: UUID,
    metric_key: str,
    value: Decimal,
    value_type: str,
    currency: str | None,
    calculation_method: str,
    observed_at: datetime,
    source_snapshot_id: UUID | None,
) -> None:
    row = (
        await db.execute(
            select(TenantAdMetricAggregate).where(
                TenantAdMetricAggregate.tenant_id == tenant_id,
                TenantAdMetricAggregate.entity_type == entity_type,
                TenantAdMetricAggregate.entity_id == entity_id,
                TenantAdMetricAggregate.window_key == _LIFETIME_WINDOW,
                TenantAdMetricAggregate.metric_key == metric_key,
                TenantAdMetricAggregate.calculation_version == AD_CALCULATION_VERSION,
            )
        )
    ).scalar_one_or_none()
    snapshot_ids = [str(source_snapshot_id)] if source_snapshot_id else []
    if row is None:
        db.add(
            TenantAdMetricAggregate(
                tenant_id=tenant_id,
                advertising_account_id=account_id,
                entity_type=entity_type,
                entity_id=entity_id,
                window_key=_LIFETIME_WINDOW,
                window_end=observed_at,
                metric_key=metric_key,
                metric_value=value,
                value_type=value_type,
                currency=currency,
                calculation_method=calculation_method,
                calculation_version=AD_CALCULATION_VERSION,
                freshness_status="fresh",
                confidence=Decimal("1.000"),
                source_snapshot_ids=snapshot_ids,
                calculated_at=observed_at,
            )
        )
    else:
        row.metric_value = value
        row.value_type = value_type
        row.currency = currency
        row.calculation_method = calculation_method
        row.freshness_status = "fresh"
        row.window_end = observed_at
        row.source_snapshot_ids = snapshot_ids
        row.calculated_at = observed_at


async def _persist_result(
    db: AsyncSession,
    *,
    account: TenantAdvertisingAccount,
    tenant_id: UUID,
    entity_type: str,
    entity_id: UUID,
    result: EntityInsightResult,
    ingestion_run_id: UUID,
    observed_at: datetime,
) -> bool:
    """Persist a single entity's insights. Returns True if a new snapshot landed."""
    fingerprint = _snapshot_fingerprint(entity_type, entity_id, result)
    if await _snapshot_exists(db, tenant_id, entity_type, entity_id, fingerprint):
        return False

    currency = result.currency or account.currency
    snapshot = TenantAdMetricSnapshot(
        tenant_id=tenant_id,
        advertising_account_id=account.id,
        entity_type=entity_type,
        entity_id=entity_id,
        provider_entity_id=result.provider_entity_id,
        level=result.level,
        observed_at=observed_at,
        provider_data_timestamp=result.provider_data_timestamp,
        date_start=result.date_start,
        date_stop=result.date_stop,
        snapshot_fingerprint=fingerprint,
        ingestion_run_id=ingestion_run_id,
        status="complete" if result.status == "ok" else "partial",
        source="mock" if account.is_mock else "provider",
        currency=currency,
        raw_metric_summary=result.raw_summary or None,
    )
    db.add(snapshot)
    await db.flush()

    normalized = metric_normalizer.normalize_provider_metrics(
        result.metrics, account.provider, default_currency=currency,
    )[:MAX_METRIC_VALUES_PER_SNAPSHOT]

    for value in normalized:
        db.add(
            TenantAdMetricValue(
                tenant_id=tenant_id,
                metric_snapshot_id=snapshot.id,
                advertising_account_id=account.id,
                entity_type=entity_type,
                entity_id=entity_id,
                metric_key=value.metric_key,
                provider_metric_key=value.provider_metric_key,
                metric_value=value.value,
                value_type=value.value_type,
                aggregation_type=value.aggregation_type,
                currency=value.currency,
                normalization_status=value.normalization_status,
                metadata_json=value.metadata or None,
            )
        )
        await _upsert_aggregate(
            db, tenant_id=tenant_id, account_id=account.id,
            entity_type=entity_type, entity_id=entity_id,
            metric_key=value.metric_key, value=value.value,
            value_type=value.value_type, currency=value.currency,
            calculation_method="derived" if value.normalization_status == "derived" else "latest_snapshot",
            observed_at=observed_at, source_snapshot_id=snapshot.id,
        )

    conversions = metric_normalizer.normalize_conversions(
        result.conversions, default_currency=currency,
    )[:MAX_CONVERSION_BREAKDOWNS_PER_SNAPSHOT]
    for conv in conversions:
        db.add(
            TenantAdConversionBreakdown(
                tenant_id=tenant_id,
                advertising_account_id=account.id,
                metric_snapshot_id=snapshot.id,
                entity_type=entity_type,
                entity_id=entity_id,
                action_type=conv["action_type"],
                action_destination=conv["action_destination"],
                attribution_setting=conv["attribution_setting"],
                conversion_window=conv["conversion_window"],
                value=conv["value"],
                value_type=conv["value_type"],
                currency=conv["currency"],
                date_start=result.date_start,
                date_stop=result.date_stop,
                metadata_json={"action_category": conv["action_category"]},
            )
        )
    await db.flush()
    return True


async def _ingest_level(
    db: AsyncSession,
    *,
    account: TenantAdvertisingAccount,
    tenant_id: UUID,
    level: str,
    connection_status: str,
    date_start: str,
    date_stop: str,
    ingestion_run_id: UUID,
    observed_at: datetime,
) -> tuple[int, int, int]:
    """Return (entities_requested, entities_succeeded, snapshots_created)."""
    index = await _entity_index(db, tenant_id, account.id, level)
    if not index:
        return 0, 0, 0
    adapter = get_adapter(account.provider)
    response = await adapter.fetch_insights(
        InsightsFetchRequest(
            tenant_id=tenant_id,
            provider=account.provider,
            connection_status=connection_status,
            provider_account_id=account.provider_account_id,
            level=level,
            date_start=date_start,
            date_stop=date_stop,
            provider_entity_ids=list(index.keys()),
        )
    )
    succeeded = 0
    snapshots = 0
    for result in response.results:
        entity_id = index.get(result.provider_entity_id)
        if entity_id is None or result.status != "ok":
            continue
        created = await _persist_result(
            db, account=account, tenant_id=tenant_id, entity_type=level,
            entity_id=entity_id, result=result, ingestion_run_id=ingestion_run_id,
            observed_at=observed_at,
        )
        succeeded += 1
        if created:
            snapshots += 1
    return len(index), succeeded, snapshots


async def _rollup_creatives(
    db: AsyncSession,
    *,
    account: TenantAdvertisingAccount,
    tenant_id: UUID,
    observed_at: datetime,
) -> None:
    """Aggregate ad-level metrics up to their creative (sum raw, re-derive)."""
    ads = list(
        (
            await db.execute(
                select(TenantAd).where(
                    TenantAd.tenant_id == tenant_id,
                    TenantAd.advertising_account_id == account.id,
                    TenantAd.creative_id.isnot(None),
                )
            )
        ).scalars().all()
    )
    if not ads:
        return
    by_creative: dict[UUID, list[UUID]] = {}
    for ad in ads:
        by_creative.setdefault(ad.creative_id, []).append(ad.id)

    _RAW_KEYS = (
        "impressions", "reach", "clicks", "link_clicks", "video_views",
        "spend_minor", "conversions", "conversion_value_minor",
    )
    for creative_id, ad_ids in by_creative.items():
        agg_rows = list(
            (
                await db.execute(
                    select(TenantAdMetricAggregate).where(
                        TenantAdMetricAggregate.tenant_id == tenant_id,
                        TenantAdMetricAggregate.entity_type == "ad",
                        TenantAdMetricAggregate.entity_id.in_(ad_ids),
                        TenantAdMetricAggregate.window_key == _LIFETIME_WINDOW,
                        TenantAdMetricAggregate.metric_key.in_(_RAW_KEYS),
                    )
                )
            ).scalars().all()
        )
        if not agg_rows:
            continue
        raw: dict[str, Decimal] = {}
        currency: str | None = None
        for row in agg_rows:
            raw[row.metric_key] = raw.get(row.metric_key, Decimal(0)) + (row.metric_value or Decimal(0))
            if row.currency:
                currency = row.currency
        for metric_key, value in raw.items():
            value_type = "currency_minor" if metric_key.endswith("_minor") else "count"
            await _upsert_aggregate(
                db, tenant_id=tenant_id, account_id=account.id,
                entity_type="creative", entity_id=creative_id,
                metric_key=metric_key, value=value, value_type=value_type,
                currency=currency if value_type == "currency_minor" else None,
                calculation_method="rollup_sum", observed_at=observed_at,
                source_snapshot_id=None,
            )
        for derived in metric_normalizer.compute_derived_from_raw(raw, spend_currency=currency):
            await _upsert_aggregate(
                db, tenant_id=tenant_id, account_id=account.id,
                entity_type="creative", entity_id=creative_id,
                metric_key=derived.metric_key, value=derived.value,
                value_type=derived.value_type, currency=derived.currency,
                calculation_method="rollup_derived", observed_at=observed_at,
                source_snapshot_id=None,
            )


async def refresh_account_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    *,
    requested_by: UUID | None = None,
    date_start: str | None = None,
    date_stop: str | None = None,
    lookback_days: int = 30,
) -> TenantAdMetricIngestionRun:
    """Fetch, normalize, and persist insights for one account. Returns the run."""
    account = await _load_account(db, tenant_id, account_id)
    connection_status = _connection_status(account)
    adapter = get_adapter(account.provider)
    capabilities = adapter.capabilities(connection_status=connection_status)

    now = _utcnow()
    if date_stop is None:
        date_stop = now.date().isoformat()
    if date_start is None:
        date_start = (now - timedelta(days=lookback_days)).date().isoformat()

    run = TenantAdMetricIngestionRun(
        tenant_id=tenant_id,
        advertising_account_id=account_id,
        provider=account.provider,
        level="account",
        status="running",
        date_start=date_start,
        date_stop=date_stop,
        started_at=now,
    )
    db.add(run)
    await db.flush()

    if not capabilities.supports_insights:
        run.status = "failed"
        run.failure_code = "metrics_unsupported"
        run.failure_metadata = {"capability_status": capabilities.capability_status}
        run.completed_at = _utcnow()
        await db.flush()
        await emit_domain_event(
            db, "advertising.insights_failed", tenant_id,
            payload={
                "ad_account_id": str(account_id), "provider": account.provider,
                "ingestion_run_id": str(run.id), "failure_code": "metrics_unsupported",
                "capability_status": capabilities.capability_status,
            },
            resource_type="advertising_ingestion_run", resource_id=str(run.id),
            title="Advertising insights unsupported",
        )
        raise AdMetricsUnsupportedError(
            capabilities.unsupported_reason or "Insights are not supported for this account.",
            details={"provider": account.provider, "capability_status": capabilities.capability_status},
        )

    observed_at = _utcnow()
    total_requested = total_succeeded = total_snapshots = 0
    for level in _LEVELS:
        requested, succeeded, snapshots = await _ingest_level(
            db, account=account, tenant_id=tenant_id, level=level,
            connection_status=connection_status, date_start=date_start,
            date_stop=date_stop, ingestion_run_id=run.id, observed_at=observed_at,
        )
        total_requested += requested
        total_succeeded += succeeded
        total_snapshots += snapshots

    await _rollup_creatives(db, account=account, tenant_id=tenant_id, observed_at=observed_at)

    account.last_metrics_sync_at = observed_at
    account.last_successful_sync_at = observed_at

    run.status = "succeeded"
    run.completed_at = _utcnow()
    run.entities_requested = total_requested
    run.entities_succeeded = total_succeeded
    run.snapshots_created = total_snapshots
    await db.flush()

    await emit_domain_event(
        db,
        "advertising.insights_ingested",
        tenant_id,
        payload={
            "ad_account_id": str(account_id),
            "provider": account.provider,
            "ingestion_run_id": str(run.id),
            "entity_count": total_succeeded,
            "snapshot_count": total_snapshots,
            "currency": account.currency,
            "is_mock": bool(account.is_mock),
        },
        actor_id=requested_by,
        resource_type="advertising_ingestion_run",
        resource_id=str(run.id),
        title="Advertising insights ingested",
    )

    # Downstream evaluators (best-effort — never fail the ingestion run).
    await _run_evaluators(db, tenant_id=tenant_id, account=account, observed_at=observed_at)
    return run


async def _run_evaluators(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account: TenantAdvertisingAccount,
    observed_at: datetime,
) -> None:
    try:
        from app.services.advertising_intelligence import pacing_service
        await pacing_service.evaluate_account_pacing(db, tenant_id, account.id, observed_at=observed_at)
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.advertising_intelligence import delivery_diagnostics
        await delivery_diagnostics.evaluate_account_delivery(db, tenant_id, account.id)
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.services.advertising_intelligence import creative_diagnostics
        await creative_diagnostics.evaluate_account_creatives(db, tenant_id, account.id)
    except Exception:  # noqa: BLE001
        pass


# Backwards-compatible alias.
ingest_insights = refresh_account_metrics

__all__ = ["refresh_account_metrics", "ingest_insights"]
