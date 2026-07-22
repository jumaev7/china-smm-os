"""Immutable metric snapshot ingestion pipeline.

Flow:
  select eligible publications → verify connected account → adapter fetch →
  validate → normalize → create immutable snapshot (+ values) → freshness →
  aggregates → anomalies → safe events

Identical provider payloads (same fingerprint) do not create duplicate
observations. Changed values always create a new snapshot.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import (
    METRIC_SEMANTICS_VERSION,
    TenantExternalPublication,
    TenantMetricIngestionRun,
    TenantPublicationMetricSnapshot,
    TenantPublicationMetricValue,
)
from app.models.publishing_account import PublishingAccount
from app.services.automation_domain_events import emit_domain_event
from app.services.measurement.aggregation_service import calculate_publication_aggregates
from app.services.measurement.anomaly_checks import evaluate_snapshot_anomalies
from app.services.measurement.errors import (
    AccountDisconnectedError,
    LimitExceededError,
    PublicationNotFoundError,
    UnsupportedCapabilityError,
)
from app.services.measurement.freshness_service import (
    compute_freshness,
    next_collection_at,
    refresh_publication_freshness,
)
from app.services.measurement.job_service import schedule_collection_job
from app.services.measurement.limits import (
    MAX_METRIC_VALUES_PER_SNAPSHOT,
    MAX_PUBLICATIONS_PER_INGESTION_RUN,
    MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR,
    MAX_SNAPSHOTS_PER_PUBLICATION_PER_DAY,
    enforce,
    enforce_rate_limit,
)
from app.services.measurement.metric_normalizer import normalize_provider_metrics
from app.services.measurement.providers import get_adapter
from app.services.measurement.providers.base import DISCONNECTED_ACCOUNT_STATUSES
from app.services.measurement.schemas import MetricFetchRequest, NormalizedMetricValue

logger = logging.getLogger(__name__)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def snapshot_fingerprint(
    *,
    provider_metrics: dict[str, Decimal],
    provider_data_timestamp: datetime | None,
    status: str,
) -> str:
    """Stable fingerprint of provider-observed metric payload (not retrieval time)."""
    payload = {
        "metrics": {k: str(provider_metrics[k]) for k in sorted(provider_metrics.keys())},
        "provider_data_timestamp": provider_data_timestamp.isoformat() if provider_data_timestamp else None,
        "status": status,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_summary(provider_metrics: dict[str, Decimal], status: str) -> dict[str, Any]:
    """Redacted summary — keys and counts only, no tokens/captions."""
    return {
        "status": status,
        "metric_keys": sorted(provider_metrics.keys()),
        "metric_count": len(provider_metrics),
    }


async def _snapshots_today_count(
    db: AsyncSession,
    tenant_id: UUID,
    publication_id: UUID,
) -> int:
    day_start = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(TenantPublicationMetricSnapshot)
                .where(
                    TenantPublicationMetricSnapshot.tenant_id == tenant_id,
                    TenantPublicationMetricSnapshot.external_publication_id == publication_id,
                    TenantPublicationMetricSnapshot.created_at >= day_start,
                )
            )
        ).scalar_one()
        or 0
    )


async def _refresh_count_last_hour(db: AsyncSession, tenant_id: UUID) -> int:
    since = utcnow() - timedelta(hours=1)
    return int(
        (
            await db.execute(
                select(func.count())
                .select_from(TenantMetricIngestionRun)
                .where(
                    TenantMetricIngestionRun.tenant_id == tenant_id,
                    TenantMetricIngestionRun.created_at >= since,
                )
            )
        ).scalar_one()
        or 0
    )


async def ingest_publication_metrics(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    publication_ids: list[UUID],
    source: str = "provider",
    manual_refresh: bool = False,
) -> TenantMetricIngestionRun:
    """Ingest metrics for a bounded batch of publications.

    Caller owns the transaction (no commit here). Partial failures preserve
    successful snapshots.
    """
    enforce(len(publication_ids), MAX_PUBLICATIONS_PER_INGESTION_RUN, "max_publications_per_ingestion_run")

    if manual_refresh:
        enforce_rate_limit(
            await _refresh_count_last_hour(db, tenant_id),
            MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR,
            "max_refresh_requests_per_tenant_per_hour",
        )

    pubs = list(
        (
            await db.execute(
                select(TenantExternalPublication).where(
                    TenantExternalPublication.tenant_id == tenant_id,
                    TenantExternalPublication.id.in_(publication_ids),
                )
            )
        ).scalars().all()
    )
    if not pubs:
        raise PublicationNotFoundError("no publications found for tenant")

    # Group by account+platform for adapter batching.
    groups: dict[tuple[UUID | None, str], list[TenantExternalPublication]] = {}
    for pub in pubs:
        groups.setdefault((pub.publishing_account_id, pub.platform), []).append(pub)

    # Use first group's platform for the run header (runs are account-scoped in practice).
    first = pubs[0]
    run = TenantMetricIngestionRun(
        id=uuid4(),
        tenant_id=tenant_id,
        publishing_account_id=first.publishing_account_id,
        platform=first.platform,
        status="running",
        requested_at=utcnow(),
        started_at=utcnow(),
        publications_requested=len(pubs),
        publications_succeeded=0,
        publications_failed=0,
        provider_request_count=0,
    )
    db.add(run)
    await db.flush()

    await emit_domain_event(
        db,
        "publication.metrics_requested",
        tenant_id,
        payload={
            "ingestion_run_id": str(run.id),
            "publication_count": len(pubs),
            "platform": first.platform,
            "manual_refresh": manual_refresh,
        },
        resource_type="metric_ingestion_run",
        resource_id=str(run.id),
        title="Metric ingestion requested",
    )

    any_success = False
    any_failure = False

    for (account_id, platform), group in groups.items():
        account: PublishingAccount | None = None
        account_status = "disconnected"
        provider_account_id = None
        if account_id is not None:
            account = (
                await db.execute(
                    select(PublishingAccount).where(
                        PublishingAccount.id == account_id,
                        PublishingAccount.tenant_id == tenant_id,
                    )
                )
            ).scalar_one_or_none()
            if account is None:
                any_failure = True
                run.publications_failed += len(group)
                continue
            account_status = account.status
            provider_account_id = account.account_id
            if account_status in DISCONNECTED_ACCOUNT_STATUSES:
                any_failure = True
                run.publications_failed += len(group)
                run.failure_code = "account_disconnected"
                continue

        adapter = get_adapter(platform)
        caps = adapter.capabilities(account_status=account_status)
        if not caps.supports_post_level_metrics and account_status != "mock":
            # Record unavailable snapshots are not fabricated — mark freshness.
            for pub in group:
                pub.freshness_status = (
                    "unsupported" if caps.capability_status == "unsupported" else "unavailable"
                )
                any_failure = True
                run.publications_failed += 1
            continue

        request = MetricFetchRequest(
            tenant_id=tenant_id,
            platform=platform,
            account_status=account_status,
            provider_account_id=provider_account_id,
            publication_ids=[p.provider_publication_id for p in group],
        )
        try:
            response = await adapter.fetch_publication_metrics(request)
        except Exception as exc:
            logger.exception("measurement.adapter_fetch_failed")
            any_failure = True
            run.publications_failed += len(group)
            run.failure_code = "adapter_error"
            run.failure_metadata = {"error_type": type(exc).__name__}
            await emit_domain_event(
                db,
                "publication.metrics_failed",
                tenant_id,
                payload={
                    "ingestion_run_id": str(run.id),
                    "platform": platform,
                    "failure_code": "adapter_error",
                },
                resource_type="metric_ingestion_run",
                resource_id=str(run.id),
                title="Metric ingestion failed",
            )
            continue

        run.provider_request_count += int(response.provider_request_count or 0)

        for pub in group:
            result = response.results.get(pub.provider_publication_id)
            if result is None or result.status in {"unsupported", "unavailable", "error"}:
                any_failure = True
                run.publications_failed += 1
                if result and result.status == "unsupported":
                    pub.freshness_status = "unsupported"
                continue

            try:
                created = await _persist_snapshot(
                    db,
                    tenant_id=tenant_id,
                    publication=pub,
                    provider_metrics=result.provider_metrics,
                    provider_data_timestamp=result.provider_data_timestamp,
                    fetch_status=result.status,
                    ingestion_run_id=run.id,
                    source=source,
                    raw_summary=_safe_summary(result.provider_metrics, result.status),
                )
            except LimitExceededError:
                any_failure = True
                run.publications_failed += 1
                continue
            except Exception:
                logger.exception("measurement.persist_snapshot_failed")
                any_failure = True
                run.publications_failed += 1
                continue

            if created is None:
                # Duplicate fingerprint — still a success (idempotent).
                run.publications_succeeded += 1
                any_success = True
                await refresh_publication_freshness(db, tenant_id, pub.id)
                continue

            run.publications_succeeded += 1
            any_success = True

            await emit_domain_event(
                db,
                "publication.metrics_ingested",
                tenant_id,
                payload={
                    "ingestion_run_id": str(run.id),
                    "external_publication_id": str(pub.id),
                    "snapshot_id": str(created.id),
                    "platform": pub.platform,
                    "metric_count": len(result.provider_metrics),
                },
                resource_type="external_publication",
                resource_id=str(pub.id),
                title="Publication metrics ingested",
            )

            # Schedule next collection (best-effort).
            try:
                await schedule_collection_job(
                    db,
                    tenant_id=tenant_id,
                    publication=pub,
                    available_at=next_collection_at(
                        published_at=pub.published_at,
                        last_metric_at=pub.last_metric_at,
                    ),
                    cadence_key="auto",
                )
            except Exception:
                logger.exception("measurement.reschedule_failed")

    if any_success and any_failure:
        run.status = "partial"
    elif any_success:
        run.status = "succeeded"
    else:
        run.status = "failed"
        if not run.failure_code:
            run.failure_code = "all_publications_failed"

    run.completed_at = utcnow()
    await db.flush()
    return run


async def _persist_snapshot(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    publication: TenantExternalPublication,
    provider_metrics: dict[str, Decimal],
    provider_data_timestamp: datetime | None,
    fetch_status: str,
    ingestion_run_id: UUID,
    source: str,
    raw_summary: dict[str, Any],
) -> TenantPublicationMetricSnapshot | None:
    """Create an immutable snapshot or return None if fingerprint already exists."""
    today_count = await _snapshots_today_count(db, tenant_id, publication.id)
    if today_count >= MAX_SNAPSHOTS_PER_PUBLICATION_PER_DAY:
        raise LimitExceededError(
            "max_snapshots_per_publication_per_day limit exceeded",
            details={
                "limit_key": "max_snapshots_per_publication_per_day",
                "max": MAX_SNAPSHOTS_PER_PUBLICATION_PER_DAY,
                "existing": today_count,
            },
        )

    fp = snapshot_fingerprint(
        provider_metrics=provider_metrics,
        provider_data_timestamp=provider_data_timestamp,
        status=fetch_status,
    )
    existing = (
        await db.execute(
            select(TenantPublicationMetricSnapshot).where(
                TenantPublicationMetricSnapshot.tenant_id == tenant_id,
                TenantPublicationMetricSnapshot.external_publication_id == publication.id,
                TenantPublicationMetricSnapshot.snapshot_fingerprint == fp,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return None

    # Previous snapshot for anomaly comparison.
    previous = (
        await db.execute(
            select(TenantPublicationMetricSnapshot)
            .where(
                TenantPublicationMetricSnapshot.tenant_id == tenant_id,
                TenantPublicationMetricSnapshot.external_publication_id == publication.id,
            )
            .order_by(TenantPublicationMetricSnapshot.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    previous_values: list[TenantPublicationMetricValue] = []
    if previous is not None:
        previous_values = list(
            (
                await db.execute(
                    select(TenantPublicationMetricValue).where(
                        TenantPublicationMetricValue.metric_snapshot_id == previous.id,
                    )
                )
            ).scalars().all()
        )

    normalized = normalize_provider_metrics(provider_metrics, platform=publication.platform)
    enforce(len(normalized), MAX_METRIC_VALUES_PER_SNAPSHOT, "max_metric_values_per_snapshot")

    now = utcnow()
    snap_status = "complete" if fetch_status == "ok" and normalized else "partial"
    if fetch_status in {"unavailable", "error"}:
        snap_status = "unavailable"
    if not normalized and fetch_status == "ok":
        snap_status = "invalid"

    snap = TenantPublicationMetricSnapshot(
        id=uuid4(),
        tenant_id=tenant_id,
        external_publication_id=publication.id,
        publishing_account_id=publication.publishing_account_id,
        platform=publication.platform,
        observed_at=now,
        provider_data_timestamp=provider_data_timestamp,
        snapshot_fingerprint=fp,
        ingestion_run_id=ingestion_run_id,
        status=snap_status,
        source=source,
        raw_metric_summary=raw_summary,
    )
    db.add(snap)
    await db.flush()

    value_rows: list[TenantPublicationMetricValue] = []
    for item in normalized:
        row = TenantPublicationMetricValue(
            id=uuid4(),
            tenant_id=tenant_id,
            metric_snapshot_id=snap.id,
            external_publication_id=publication.id,
            metric_key=item.metric_key,
            provider_metric_key=item.provider_metric_key,
            metric_value=item.value,
            value_type=item.value_type,
            aggregation_type=item.aggregation_type,
            metric_semantics_version=METRIC_SEMANTICS_VERSION,
            normalization_status=item.normalization_status,
            metadata_json=item.metadata or None,
        )
        db.add(row)
        value_rows.append(row)
    await db.flush()

    publication.last_metric_at = now
    publication.last_seen_at = now
    freshness = compute_freshness(
        last_metric_at=now,
        published_at=publication.published_at,
        now=now,
    )
    publication.freshness_status = freshness.status

    await calculate_publication_aggregates(
        db,
        tenant_id=tenant_id,
        external_publication_id=publication.id,
        published_at=publication.published_at,
        last_metric_at=publication.last_metric_at,
        freshness_hint=publication.freshness_status,
    )

    anomalies = await evaluate_snapshot_anomalies(
        db,
        tenant_id=tenant_id,
        external_publication_id=publication.id,
        snapshot=snap,
        values=value_rows,
        previous_snapshot=previous,
        previous_values=previous_values,
    )
    if anomalies:
        await emit_domain_event(
            db,
            "publication.measurement_anomaly_detected",
            tenant_id,
            payload={
                "external_publication_id": str(publication.id),
                "snapshot_id": str(snap.id),
                "anomaly_count": len(anomalies),
                "anomaly_keys": [a.anomaly_key for a in anomalies],
            },
            resource_type="external_publication",
            resource_id=str(publication.id),
            title="Measurement anomaly detected",
        )

    await db.flush()
    return snap


async def refresh_publication(
    db: AsyncSession,
    tenant_id: UUID,
    publication_id: UUID,
) -> TenantMetricIngestionRun:
    """Manual rate-limited refresh for a single publication."""
    pub = (
        await db.execute(
            select(TenantExternalPublication).where(
                TenantExternalPublication.id == publication_id,
                TenantExternalPublication.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if pub is None:
        raise PublicationNotFoundError("publication not found")
    return await ingest_publication_metrics(
        db,
        tenant_id=tenant_id,
        publication_ids=[publication_id],
        manual_refresh=True,
    )


__all__ = [
    "snapshot_fingerprint",
    "ingest_publication_metrics",
    "refresh_publication",
]
