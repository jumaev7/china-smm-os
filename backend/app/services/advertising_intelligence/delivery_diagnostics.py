"""Deterministic, evidence-backed delivery diagnostics.

Examines the latest ingested metrics for campaigns / ad groups / ads and records
``TenantAdDeliveryAnomaly`` rows for well-defined, explainable conditions. All
findings are advisory; nothing here ever mutates a provider object.

``compute_delivery_findings`` is a pure function over an entity's status +
metric map; ``evaluate_account_delivery`` persists new anomalies and emits
``advertising.delivery_issue_detected`` for warning/error findings.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAd,
    TenantAdCampaign,
    TenantAdDeliveryAnomaly,
    TenantAdGroup,
)
from app.services.advertising_intelligence._entity_metrics import (
    latest_metric_map,
    metric_decimal,
)
from app.services.automation_domain_events import emit_domain_event

_ACTIVE_STATUSES = frozenset({"active"})
_WARNING = "warning"
_INFO = "info"


def compute_delivery_findings(effective_status: str | None, metrics: dict) -> list[dict]:
    """Return a list of ``{anomaly_key, severity, metric_key, evidence}`` findings."""
    findings: list[dict] = []
    impressions = metric_decimal(metrics, "impressions")
    spend = metric_decimal(metrics, "spend_minor")
    is_active = effective_status in _ACTIVE_STATUSES

    if is_active and (impressions is None or impressions == 0):
        findings.append({
            "anomaly_key": "zero_delivery_active_entity",
            "severity": _WARNING,
            "metric_key": "impressions",
            "evidence": {"effective_status": effective_status, "impressions": str(impressions or 0)},
        })

    if spend and spend > 0 and (impressions is None or impressions == 0):
        findings.append({
            "anomaly_key": "spend_without_impressions",
            "severity": _WARNING,
            "metric_key": "spend_minor",
            "evidence": {"spend_minor": str(spend), "impressions": str(impressions or 0)},
        })

    if impressions and impressions > 0 and (spend is None or spend == 0) and is_active:
        findings.append({
            "anomaly_key": "impressions_without_spend",
            "severity": _INFO,
            "metric_key": "spend_minor",
            "evidence": {"impressions": str(impressions), "spend_minor": str(spend or 0)},
        })

    return findings


async def _existing_open_keys(db: AsyncSession, tenant_id: UUID, entity_type: str, entity_id: UUID) -> set[str]:
    rows = list(
        (
            await db.execute(
                select(TenantAdDeliveryAnomaly.anomaly_key).where(
                    TenantAdDeliveryAnomaly.tenant_id == tenant_id,
                    TenantAdDeliveryAnomaly.entity_type == entity_type,
                    TenantAdDeliveryAnomaly.entity_id == entity_id,
                    TenantAdDeliveryAnomaly.status == "open",
                )
            )
        ).scalars().all()
    )
    return set(rows)


async def _evaluate_entity(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    entity_type: str,
    entity_id: UUID,
    effective_status: str | None,
) -> int:
    metrics = await latest_metric_map(db, tenant_id, entity_type, entity_id)
    if not metrics:
        return 0
    findings = compute_delivery_findings(effective_status, metrics)
    if not findings:
        return 0
    open_keys = await _existing_open_keys(db, tenant_id, entity_type, entity_id)
    created = 0
    for finding in findings:
        if finding["anomaly_key"] in open_keys:
            continue
        db.add(
            TenantAdDeliveryAnomaly(
                tenant_id=tenant_id,
                advertising_account_id=account_id,
                entity_type=entity_type,
                entity_id=entity_id,
                anomaly_key=finding["anomaly_key"],
                severity=finding["severity"],
                metric_key=finding["metric_key"],
                evidence=finding["evidence"],
                status="open",
            )
        )
        created += 1
        if finding["severity"] in ("warning", "error", "critical"):
            await emit_domain_event(
                db,
                "advertising.delivery_issue_detected",
                tenant_id,
                payload={
                    "ad_account_id": str(account_id),
                    "entity_type": entity_type,
                    "ad_entity_id": str(entity_id),
                    "diagnostic_key": finding["anomaly_key"],
                    "status": "open",
                },
                resource_type=f"advertising_{entity_type}",
                resource_id=str(entity_id),
                title="Advertising delivery issue detected",
            )
    return created


async def evaluate_account_delivery(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> int:
    """Evaluate delivery for all campaigns/ad groups/ads. Returns anomalies created."""
    created = 0
    for model, entity_type in (
        (TenantAdCampaign, "campaign"),
        (TenantAdGroup, "ad_group"),
        (TenantAd, "ad"),
    ):
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
        for row in rows:
            created += await _evaluate_entity(
                db, tenant_id=tenant_id, account_id=account_id,
                entity_type=entity_type, entity_id=row.id,
                effective_status=row.effective_status,
            )
    await db.flush()
    return created


__all__ = ["compute_delivery_findings", "evaluate_account_delivery"]
