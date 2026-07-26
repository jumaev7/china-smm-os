"""Conservative experiment review — directional language only, no significance claims.

Captures measurements from observed entity metrics and compares variants with
cautious wording. Never claims statistical significance.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising_decision_support import (
    EXPERIMENT_PLANNER_ENGINE_VERSION,
    EXPERIMENT_RESULT_STATUSES,
    TenantAdExperiment,
    TenantAdExperimentMeasurement,
    TenantAdExperimentReview,
    TenantAdExperimentVariant,
)
from app.services.advertising_decision_support.errors import (
    AdExperimentNotFoundError,
    AdExperimentStateError,
)
from app.services.advertising_decision_support.experiment_planner import (
    _get_experiment_row,
    _variants_for,
)
from app.services.advertising_intelligence._entity_metrics import (
    latest_metric_map,
    metric_decimal,
)
from app.services.advertising_intelligence.freshness_service import compute_freshness
from app.services.advertising_intelligence.metric_catalog import get_metric_definition
from app.services.advertising_intelligence.spend_service import entity_spend
from app.services.automation_domain_events import emit_domain_event

_CORE_METRICS = ("impressions", "clicks", "conversions", "ctr", "cpa_minor", "roas")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def evaluate_minimum_data(
    *,
    observations: Decimal | None,
    spend_minor: int | None,
    conversions: Decimal | None,
    minimum_observations: int,
    minimum_spend_minor: int | None,
    minimum_conversions: int | None,
    freshness_status: str | None,
) -> dict[str, Any]:
    """Conservative gate checks — insufficient until all configured floors met."""
    failures: list[str] = []
    if observations is None or observations < Decimal(minimum_observations):
        failures.append("minimum_observations")
    if minimum_spend_minor is not None and (
        spend_minor is None or spend_minor < minimum_spend_minor
    ):
        failures.append("minimum_spend_minor")
    if minimum_conversions is not None and (
        conversions is None or conversions < Decimal(minimum_conversions)
    ):
        failures.append("minimum_conversions")
    if freshness_status in {"stale", "unavailable"}:
        failures.append("freshness")
    return {
        "passed": len(failures) == 0,
        "failures": failures,
    }


def compare_variants_directional(
    *,
    primary_metric_key: str,
    variant_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    """Directional comparison only — never claims significance or future performance."""
    definition = get_metric_definition(primary_metric_key)
    direction = definition.direction if definition else "neutral"

    values = []
    for row in variant_metrics:
        raw = row.get("primary_value")
        values.append({
            "variant_id": row["variant_id"],
            "variant_key": row.get("variant_key"),
            "value": Decimal(str(raw)) if raw is not None else None,
            "spend_minor": row.get("spend_minor"),
            "impressions": row.get("impressions"),
        })

    present = [v for v in values if v["value"] is not None]
    if len(present) < 2:
        return {
            "result_status": "insufficient_data",
            "conclusion": "Not enough observed primary-metric values across variants for comparison.",
            "leader_variant_key": None,
            "directional": False,
        }

    # Imbalance check on exposure/spend.
    spends = [v["spend_minor"] for v in present if v.get("spend_minor") is not None]
    imbalanced = False
    if len(spends) >= 2 and min(spends) > 0:
        if max(spends) / min(spends) >= 5:
            imbalanced = True

    if direction == "lower_is_better":
        leader = min(present, key=lambda v: v["value"])
        wording = "lower observed"
    elif direction == "higher_is_better":
        leader = max(present, key=lambda v: v["value"])
        wording = "higher observed"
    else:
        return {
            "result_status": "inconclusive",
            "conclusion": (
                f"Primary metric '{primary_metric_key}' is neutral; "
                "no favorable direction is automatically assigned."
            ),
            "leader_variant_key": None,
            "directional": False,
            "imbalanced_exposure": imbalanced,
        }

    others = [v for v in present if v["variant_id"] != leader["variant_id"]]
    if not others:
        return {
            "result_status": "insufficient_data",
            "conclusion": "Only one variant has a primary metric value.",
            "leader_variant_key": leader.get("variant_key"),
            "directional": False,
        }

    # Require a non-trivial relative gap before calling it directional.
    peer = others[0]["value"]
    if peer == 0:
        gap = None
    else:
        gap = abs(leader["value"] - peer) / abs(peer)

    if gap is None or gap < Decimal("0.05"):
        status = "inconclusive"
        conclusion = (
            "Observed primary-metric differences between variants are small; "
            "no directional conclusion is drawn."
        )
        directional = False
    else:
        status = "directional"
        conclusion = (
            f"Variant {leader.get('variant_key')} currently has a {wording} "
            f"{primary_metric_key}. This is a directional observation only and "
            "does not imply statistical significance or future performance."
        )
        directional = True

    if imbalanced:
        conclusion += " Exposure/spend appears imbalanced across variants."

    assert status in EXPERIMENT_RESULT_STATUSES
    return {
        "result_status": status,
        "conclusion": conclusion,
        "leader_variant_key": leader.get("variant_key"),
        "directional": directional,
        "imbalanced_exposure": imbalanced,
        "direction": direction,
        "values": [
            {
                "variant_id": v["variant_id"],
                "variant_key": v.get("variant_key"),
                "value": str(v["value"]) if v["value"] is not None else None,
            }
            for v in values
        ],
    }


async def _capture_measurements(
    db: AsyncSession,
    tenant_id: UUID,
    exp: TenantAdExperiment,
    variants: list[TenantAdExperimentVariant],
) -> list[TenantAdExperimentMeasurement]:
    now = _utcnow()
    created: list[TenantAdExperimentMeasurement] = []
    for variant in variants:
        metric_map = await latest_metric_map(
            db, tenant_id, variant.entity_type, variant.entity_id,
        )
        observed_at = now
        obs_entry = metric_map.pop("__observed_at__", None) if metric_map else None
        if obs_entry and obs_entry.get("value"):
            observed_at = obs_entry["value"]
        freshness = compute_freshness(observed_at if metric_map else None)
        spend_minor, spend_currency = await entity_spend(
            db, tenant_id, variant.entity_type, variant.entity_id,
        )
        metrics_json: dict[str, Any] = {}
        for key in {exp.primary_metric_key, *_CORE_METRICS}:
            val = metric_decimal(metric_map, key)
            if val is None:
                continue
            entry = metric_map.get(key) or {}
            metrics_json[key] = {
                "value": str(val),
                "currency": entry.get("currency"),
                "kind": "OBSERVED",
            }
        row = TenantAdExperimentMeasurement(
            tenant_id=tenant_id,
            experiment_id=exp.id,
            variant_id=variant.id,
            observed_at=observed_at if isinstance(observed_at, datetime) else now,
            metrics_json=metrics_json or None,
            spend_minor=spend_minor,
            currency=spend_currency or exp.currency,
            impressions=metric_decimal(metric_map, "impressions"),
            clicks=metric_decimal(metric_map, "clicks"),
            conversions=metric_decimal(metric_map, "conversions"),
            freshness_status=freshness.get("status"),
            attribution_method=exp.attribution_method,
            warnings_json=None,
            engine_version=EXPERIMENT_PLANNER_ENGINE_VERSION,
        )
        db.add(row)
        created.append(row)
    await db.flush()
    return created


def _build_review_payload(
    *,
    exp: TenantAdExperiment,
    variants: list[TenantAdExperimentVariant],
    measurements: list[TenantAdExperimentMeasurement],
) -> dict[str, Any]:
    by_variant = {m.variant_id: m for m in measurements}
    variant_metrics: list[dict[str, Any]] = []
    gate_failures: list[str] = []
    all_passed = True

    for variant in variants:
        m = by_variant.get(variant.id)
        primary_val = None
        if m and m.metrics_json and exp.primary_metric_key in m.metrics_json:
            primary_val = m.metrics_json[exp.primary_metric_key].get("value")
        observations = m.impressions if m else None
        gate = evaluate_minimum_data(
            observations=observations,
            spend_minor=m.spend_minor if m else None,
            conversions=m.conversions if m else None,
            minimum_observations=exp.minimum_observations,
            minimum_spend_minor=exp.minimum_spend_minor,
            minimum_conversions=exp.minimum_conversions,
            freshness_status=m.freshness_status if m else "unavailable",
        )
        if not gate["passed"]:
            all_passed = False
            gate_failures.extend(gate["failures"])
        variant_metrics.append({
            "variant_id": str(variant.id),
            "variant_key": variant.variant_key,
            "label": variant.label,
            "entity_type": variant.entity_type,
            "entity_id": str(variant.entity_id),
            "primary_value": primary_val,
            "spend_minor": m.spend_minor if m else None,
            "impressions": str(m.impressions) if m and m.impressions is not None else None,
            "clicks": str(m.clicks) if m and m.clicks is not None else None,
            "conversions": str(m.conversions) if m and m.conversions is not None else None,
            "freshness_status": m.freshness_status if m else None,
            "metrics": m.metrics_json if m else None,
            "minimum_data": gate,
        })

    if exp.status == "running_observation" and not all_passed:
        comparison = {
            "result_status": "collecting",
            "conclusion": (
                "Observation is still collecting; minimum-data requirements are not yet met."
            ),
            "leader_variant_key": None,
            "directional": False,
        }
    elif not all_passed:
        comparison = {
            "result_status": "insufficient_data",
            "conclusion": (
                "Minimum observation/spend/conversion/freshness requirements are not met."
            ),
            "leader_variant_key": None,
            "directional": False,
        }
    else:
        comparison = compare_variants_directional(
            primary_metric_key=exp.primary_metric_key,
            variant_metrics=variant_metrics,
        )
        if exp.status == "completed" and comparison["result_status"] == "directional":
            # Keep directional wording even when experiment is marked completed.
            pass
        elif exp.status == "completed" and comparison["result_status"] not in {
            "insufficient_data", "inconclusive", "directional",
        }:
            comparison["result_status"] = "completed"

    limitations = [
        "This review does not claim statistical significance.",
        "Directional language describes observed metrics only, not future performance.",
        "Attribution method is recorded explicitly and is not causal proof.",
    ]
    if gate_failures:
        limitations.append(f"Unmet gates: {', '.join(sorted(set(gate_failures)))}.")

    result_status = comparison["result_status"]
    assert result_status in EXPERIMENT_RESULT_STATUSES

    return {
        "experiment_id": str(exp.id),
        "result_status": result_status,
        "conclusion": comparison["conclusion"],
        "variants": variant_metrics,
        "comparison": comparison,
        "limitations": limitations,
        "evidence": {
            "primary_metric_key": exp.primary_metric_key,
            "attribution_method": exp.attribution_method,
            "minimum_observations": exp.minimum_observations,
            "minimum_spend_minor": exp.minimum_spend_minor,
            "minimum_conversions": exp.minimum_conversions,
            "measurement_count": len(measurements),
        },
        "engine_version": EXPERIMENT_PLANNER_ENGINE_VERSION,
        "read_only": True,
        "kind": "DIRECTIONAL" if comparison.get("directional") else result_status.upper(),
        "statistical_significance_claimed": False,
    }


async def build_review(
    db: AsyncSession,
    tenant_id: UUID,
    experiment_id: UUID,
    *,
    user_id: UUID | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Capture measurements, build conservative review, optionally persist + emit."""
    exp = await _get_experiment_row(db, tenant_id, experiment_id)
    if exp.status not in {"running_observation", "completed"}:
        raise AdExperimentStateError(
            "review requires running_observation or completed status",
            details={"status": exp.status},
        )
    variants = await _variants_for(db, tenant_id, experiment_id)
    measurements = await _capture_measurements(db, tenant_id, exp, variants)
    payload = _build_review_payload(exp=exp, variants=variants, measurements=measurements)

    exp.result_status = payload["result_status"]
    if persist:
        review = TenantAdExperimentReview(
            tenant_id=tenant_id,
            experiment_id=exp.id,
            result_status=payload["result_status"],
            conclusion=payload["conclusion"],
            evidence_json={
                "evidence": payload["evidence"],
                "variants": payload["variants"],
                "comparison": payload["comparison"],
            },
            limitations_json={"limitations": payload["limitations"]},
            reviewed_by_user_id=user_id,
            engine_version=EXPERIMENT_PLANNER_ENGINE_VERSION,
        )
        db.add(review)
        await db.flush()
        payload["review_id"] = str(review.id)
        await emit_domain_event(
            db,
            "advertising.experiment_reviewed",
            tenant_id,
            payload={
                "experiment_id": str(exp.id),
                "review_id": str(review.id),
                "result_status": payload["result_status"],
            },
            actor_type="user" if user_id else "system",
            actor_id=user_id,
            resource_type="advertising_experiment",
            resource_id=str(exp.id),
            title="Advertising experiment reviewed",
        )
    await db.flush()
    return payload


async def get_review(
    db: AsyncSession,
    tenant_id: UUID,
    experiment_id: UUID,
) -> dict[str, Any]:
    """Return latest persisted review, or build a non-persisting snapshot."""
    exp = (
        await db.execute(
            select(TenantAdExperiment).where(
                TenantAdExperiment.tenant_id == tenant_id,
                TenantAdExperiment.id == experiment_id,
            )
        )
    ).scalar_one_or_none()
    if exp is None:
        raise AdExperimentNotFoundError(
            "experiment not found",
            details={"experiment_id": str(experiment_id)},
        )
    latest = (
        await db.execute(
            select(TenantAdExperimentReview)
            .where(
                TenantAdExperimentReview.tenant_id == tenant_id,
                TenantAdExperimentReview.experiment_id == experiment_id,
            )
            .order_by(TenantAdExperimentReview.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is not None:
        return {
            "review_id": str(latest.id),
            "experiment_id": str(experiment_id),
            "result_status": latest.result_status,
            "conclusion": latest.conclusion,
            "evidence": latest.evidence_json,
            "limitations": (latest.limitations_json or {}).get("limitations"),
            "engine_version": latest.engine_version,
            "created_at": latest.created_at.isoformat() if latest.created_at else None,
            "statistical_significance_claimed": False,
            "read_only": True,
        }
    return await build_review(db, tenant_id, experiment_id, persist=False)


__all__ = [
    "evaluate_minimum_data",
    "compare_variants_directional",
    "build_review",
    "get_review",
]
