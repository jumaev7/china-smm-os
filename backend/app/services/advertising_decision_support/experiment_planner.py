"""Internal advertising experiment planner (observation only).

Plans experiments and observes externally executed entities. NEVER creates
experiments on providers and NEVER calls provider write methods.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAd,
    TenantAdCampaign,
    TenantAdCreative,
    TenantAdGroup,
)
from app.models.advertising_decision_support import (
    COMPARABLE_ENTITY_TYPES,
    EXPERIMENT_PLANNER_ENGINE_VERSION,
    EXPERIMENT_STATUSES,
    EXPERIMENT_TYPES,
    TenantAdExperiment,
    TenantAdExperimentVariant,
)
from app.services.advertising_decision_support.errors import (
    AdEntityNotFoundError,
    AdExperimentNotFoundError,
    AdExperimentStateError,
    AdExperimentValidationError,
)
from app.services.advertising_decision_support.limits import (
    MAX_EXPERIMENTS_PER_TENANT,
    enforce_variant_count,
)
from app.services.advertising_intelligence.errors import AdReadOnlyOperationError
from app.services.automation_domain_events import emit_domain_event

_ENTITY_MODELS = {
    "campaign": TenantAdCampaign,
    "ad_group": TenantAdGroup,
    "ad": TenantAd,
    "creative": TenantAdCreative,
}

_PATCHABLE_STATUSES = frozenset({"draft", "ready"})
_TERMINAL = frozenset({"completed", "cancelled", "archived"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_variant(v: TenantAdExperimentVariant) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "variant_key": v.variant_key,
        "label": v.label,
        "entity_type": v.entity_type,
        "entity_id": str(v.entity_id),
        "notes": v.notes,
        "metadata_json": v.metadata_json,
    }


def _serialize_experiment(
    exp: TenantAdExperiment,
    variants: list[TenantAdExperimentVariant],
) -> dict[str, Any]:
    return {
        "id": str(exp.id),
        "tenant_id": str(exp.tenant_id),
        "name": exp.name,
        "experiment_type": exp.experiment_type,
        "status": exp.status,
        "hypothesis": exp.hypothesis,
        "primary_metric_key": exp.primary_metric_key,
        "secondary_metric_keys": exp.secondary_metric_keys,
        "observation_start": exp.observation_start.isoformat() if exp.observation_start else None,
        "observation_end": exp.observation_end.isoformat() if exp.observation_end else None,
        "minimum_observations": exp.minimum_observations,
        "minimum_spend_minor": exp.minimum_spend_minor,
        "minimum_conversions": exp.minimum_conversions,
        "currency": exp.currency,
        "attribution_method": exp.attribution_method,
        "notes": exp.notes,
        "result_status": exp.result_status,
        "engine_version": exp.engine_version,
        "metadata_json": exp.metadata_json,
        "created_by_user_id": str(exp.created_by_user_id) if exp.created_by_user_id else None,
        "created_at": exp.created_at.isoformat() if exp.created_at else None,
        "updated_at": exp.updated_at.isoformat() if exp.updated_at else None,
        "observation_started_at": (
            exp.observation_started_at.isoformat() if exp.observation_started_at else None
        ),
        "completed_at": exp.completed_at.isoformat() if exp.completed_at else None,
        "cancelled_at": exp.cancelled_at.isoformat() if exp.cancelled_at else None,
        "variants": [_serialize_variant(v) for v in variants],
        "read_only_toward_providers": True,
        "provider_launch": False,
    }


async def _load_entity(db: AsyncSession, tenant_id: UUID, entity_type: str, entity_id: UUID) -> Any:
    if entity_type not in COMPARABLE_ENTITY_TYPES:
        raise AdExperimentValidationError(
            "unsupported entity type for experiment variant",
            details={"entity_type": entity_type},
        )
    model = _ENTITY_MODELS[entity_type]
    row = (
        await db.execute(
            select(model).where(model.tenant_id == tenant_id, model.id == entity_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AdEntityNotFoundError(
            "advertising entity not found",
            details={"entity_type": entity_type, "entity_id": str(entity_id)},
        )
    return row


async def _get_experiment_row(
    db: AsyncSession, tenant_id: UUID, experiment_id: UUID,
) -> TenantAdExperiment:
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
    return exp


async def _variants_for(
    db: AsyncSession, tenant_id: UUID, experiment_id: UUID,
) -> list[TenantAdExperimentVariant]:
    return list(
        (
            await db.execute(
                select(TenantAdExperimentVariant)
                .where(
                    TenantAdExperimentVariant.tenant_id == tenant_id,
                    TenantAdExperimentVariant.experiment_id == experiment_id,
                )
                .order_by(TenantAdExperimentVariant.created_at.asc())
            )
        ).scalars().all()
    )


async def create_experiment(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    name: str,
    experiment_type: str,
    hypothesis: str,
    primary_metric_key: str,
    variants: list[dict[str, Any]],
    secondary_metric_keys: list[str] | None = None,
    observation_start: date | None = None,
    observation_end: date | None = None,
    minimum_observations: int = 100,
    minimum_spend_minor: int | None = None,
    minimum_conversions: int | None = None,
    currency: str | None = None,
    attribution_method: str | None = None,
    notes: str | None = None,
    metadata_json: dict[str, Any] | None = None,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    if experiment_type not in EXPERIMENT_TYPES:
        raise AdExperimentValidationError(
            "unsupported experiment type",
            details={"experiment_type": experiment_type, "allowed": sorted(EXPERIMENT_TYPES)},
        )
    enforce_variant_count(len(variants))

    total = (
        await db.execute(
            select(func.count())
            .select_from(TenantAdExperiment)
            .where(TenantAdExperiment.tenant_id == tenant_id)
        )
    ).scalar_one()
    if int(total or 0) >= MAX_EXPERIMENTS_PER_TENANT:
        raise AdExperimentValidationError(
            "experiment limit reached for tenant",
            details={"max": MAX_EXPERIMENTS_PER_TENANT},
        )

    keys = [str(v["variant_key"]) for v in variants]
    if len(set(keys)) != len(keys):
        raise AdExperimentValidationError("duplicate variant_key")

    for raw in variants:
        await _load_entity(
            db, tenant_id, str(raw["entity_type"]), UUID(str(raw["entity_id"])),
        )

    exp = TenantAdExperiment(
        tenant_id=tenant_id,
        name=name,
        experiment_type=experiment_type,
        status="draft",
        hypothesis=hypothesis,
        primary_metric_key=primary_metric_key,
        secondary_metric_keys={"keys": secondary_metric_keys} if secondary_metric_keys else None,
        observation_start=observation_start,
        observation_end=observation_end,
        minimum_observations=minimum_observations,
        minimum_spend_minor=minimum_spend_minor,
        minimum_conversions=minimum_conversions,
        currency=(currency.upper() if currency else None),
        attribution_method=attribution_method,
        notes=notes,
        engine_version=EXPERIMENT_PLANNER_ENGINE_VERSION,
        metadata_json=metadata_json,
        created_by_user_id=user_id,
    )
    db.add(exp)
    await db.flush()

    variant_rows: list[TenantAdExperimentVariant] = []
    for raw in variants:
        row = TenantAdExperimentVariant(
            tenant_id=tenant_id,
            experiment_id=exp.id,
            variant_key=str(raw["variant_key"]),
            label=str(raw["label"]),
            entity_type=str(raw["entity_type"]),
            entity_id=UUID(str(raw["entity_id"])),
            notes=raw.get("notes"),
            metadata_json=raw.get("metadata_json"),
        )
        db.add(row)
        variant_rows.append(row)
    await db.flush()

    await emit_domain_event(
        db,
        "advertising.experiment_created",
        tenant_id,
        payload={
            "experiment_id": str(exp.id),
            "experiment_type": experiment_type,
            "status": exp.status,
            "variant_count": len(variant_rows),
            "primary_metric_key": primary_metric_key,
        },
        actor_type="user" if user_id else "system",
        actor_id=user_id,
        resource_type="advertising_experiment",
        resource_id=str(exp.id),
        title="Advertising experiment plan created",
    )
    return _serialize_experiment(exp, variant_rows)


async def list_experiments(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [TenantAdExperiment.tenant_id == tenant_id]
    if status is not None:
        if status not in EXPERIMENT_STATUSES:
            raise AdExperimentValidationError("invalid experiment status filter")
        filters.append(TenantAdExperiment.status == status)
    total = (
        await db.execute(
            select(func.count()).select_from(TenantAdExperiment).where(*filters)
        )
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(TenantAdExperiment)
                .where(*filters)
                .order_by(TenantAdExperiment.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
    )
    out: list[dict[str, Any]] = []
    for exp in rows:
        variants = await _variants_for(db, tenant_id, exp.id)
        out.append(_serialize_experiment(exp, variants))
    return out, int(total or 0)


async def get_experiment(
    db: AsyncSession, tenant_id: UUID, experiment_id: UUID,
) -> dict[str, Any]:
    exp = await _get_experiment_row(db, tenant_id, experiment_id)
    variants = await _variants_for(db, tenant_id, experiment_id)
    return _serialize_experiment(exp, variants)


async def patch_experiment(
    db: AsyncSession,
    tenant_id: UUID,
    experiment_id: UUID,
    *,
    patch: dict[str, Any],
) -> dict[str, Any]:
    exp = await _get_experiment_row(db, tenant_id, experiment_id)
    if exp.status not in _PATCHABLE_STATUSES:
        raise AdExperimentStateError(
            "experiment can only be patched in draft or ready status",
            details={"status": exp.status},
        )

    # Hard ban any provider-mutation keys.
    for banned in ("provider_payload", "execute", "launch_on_provider", "apply_to_meta"):
        if banned in patch:
            raise AdReadOnlyOperationError(
                "provider mutation fields are not allowed on experiments",
                details={"field": banned},
            )

    allowed = {
        "name", "hypothesis", "primary_metric_key", "secondary_metric_keys",
        "observation_start", "observation_end", "minimum_observations",
        "minimum_spend_minor", "minimum_conversions", "currency",
        "attribution_method", "notes", "metadata_json", "status",
    }
    unknown = set(patch) - allowed
    if unknown:
        raise AdExperimentValidationError(
            "unknown patch fields",
            details={"fields": sorted(unknown)},
        )

    if "status" in patch:
        new_status = patch["status"]
        if new_status not in {"draft", "ready"}:
            raise AdExperimentStateError(
                "status patch limited to draft/ready; use lifecycle endpoints otherwise",
                details={"requested": new_status},
            )
        if exp.status == "ready" and new_status == "draft":
            exp.status = "draft"
        elif exp.status == "draft" and new_status == "ready":
            exp.status = "ready"
        elif new_status != exp.status:
            raise AdExperimentStateError(
                "invalid status transition via patch",
                details={"from": exp.status, "to": new_status},
            )

    for key in (
        "name", "hypothesis", "primary_metric_key", "observation_start",
        "observation_end", "minimum_observations", "minimum_spend_minor",
        "minimum_conversions", "attribution_method", "notes", "metadata_json",
    ):
        if key in patch:
            setattr(exp, key, patch[key])
    if "secondary_metric_keys" in patch:
        keys = patch["secondary_metric_keys"]
        exp.secondary_metric_keys = {"keys": keys} if keys else None
    if "currency" in patch and patch["currency"]:
        exp.currency = str(patch["currency"]).upper()

    await db.flush()
    variants = await _variants_for(db, tenant_id, experiment_id)
    return _serialize_experiment(exp, variants)


async def start_observation(
    db: AsyncSession, tenant_id: UUID, experiment_id: UUID,
) -> dict[str, Any]:
    exp = await _get_experiment_row(db, tenant_id, experiment_id)
    if exp.status not in {"draft", "ready"}:
        raise AdExperimentStateError(
            "observation can only start from draft or ready",
            details={"status": exp.status},
        )
    variants = await _variants_for(db, tenant_id, experiment_id)
    if len(variants) < 2:
        raise AdExperimentValidationError("at least two variants are required to start observation")
    exp.status = "running_observation"
    exp.observation_started_at = _utcnow()
    exp.result_status = "collecting"
    await db.flush()
    return _serialize_experiment(exp, variants)


async def complete_experiment(
    db: AsyncSession, tenant_id: UUID, experiment_id: UUID,
) -> dict[str, Any]:
    exp = await _get_experiment_row(db, tenant_id, experiment_id)
    if exp.status != "running_observation":
        raise AdExperimentStateError(
            "only running_observation experiments can be completed",
            details={"status": exp.status},
        )
    exp.status = "completed"
    exp.completed_at = _utcnow()
    if not exp.result_status:
        exp.result_status = "completed"
    await db.flush()
    variants = await _variants_for(db, tenant_id, experiment_id)
    return _serialize_experiment(exp, variants)


async def cancel_experiment(
    db: AsyncSession, tenant_id: UUID, experiment_id: UUID,
) -> dict[str, Any]:
    exp = await _get_experiment_row(db, tenant_id, experiment_id)
    if exp.status in _TERMINAL:
        raise AdExperimentStateError(
            "experiment is already terminal",
            details={"status": exp.status},
        )
    exp.status = "cancelled"
    exp.cancelled_at = _utcnow()
    await db.flush()
    variants = await _variants_for(db, tenant_id, experiment_id)
    return _serialize_experiment(exp, variants)


async def archive_experiment(
    db: AsyncSession, tenant_id: UUID, experiment_id: UUID,
) -> dict[str, Any]:
    exp = await _get_experiment_row(db, tenant_id, experiment_id)
    if exp.status not in {"completed", "cancelled"}:
        raise AdExperimentStateError(
            "only completed or cancelled experiments can be archived",
            details={"status": exp.status},
        )
    exp.status = "archived"
    await db.flush()
    variants = await _variants_for(db, tenant_id, experiment_id)
    return _serialize_experiment(exp, variants)


__all__ = [
    "create_experiment",
    "list_experiments",
    "get_experiment",
    "patch_experiment",
    "start_observation",
    "complete_experiment",
    "cancel_experiment",
    "archive_experiment",
]
