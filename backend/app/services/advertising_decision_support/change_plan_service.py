"""Reviewable proposed change plans — recommendations ONLY, never executable.

Lifecycle: draft → reviewed | dismissed → archived.
No provider_payload / executable_command fields are ever stored.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising_decision_support import (
    CHANGE_PLAN_ITEM_TYPES,
    CHANGE_PLAN_STATUSES,
    RECOMMENDATION_ENGINE_VERSION,
    TenantAdChangePlan,
    TenantAdChangePlanItem,
)
from app.services.advertising_decision_support.errors import (
    AdChangePlanNotFoundError,
    AdChangePlanStateError,
    AdDecisionSupportError,
)
from app.services.advertising_decision_support.limits import MAX_CHANGE_PLAN_ITEMS
from app.services.advertising_intelligence.errors import AdReadOnlyOperationError
from app.services.automation_domain_events import emit_domain_event

_FORBIDDEN_ITEM_KEYS = frozenset({
    "provider_payload",
    "executable_command",
    "provider_command",
    "apply_to_meta",
    "api_payload",
})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_item(item: TenantAdChangePlanItem) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "item_type": item.item_type,
        "entity_type": item.entity_type,
        "entity_id": str(item.entity_id) if item.entity_id else None,
        "observation": item.observation,
        "evidence_json": item.evidence_json,
        "reasoning": item.reasoning,
        "suggested_human_action": item.suggested_human_action,
        "risk": item.risk,
        "confidence": str(item.confidence) if item.confidence is not None else None,
        "supporting_metrics": item.supporting_metrics,
        # Explicitly absent: provider_payload
    }


def _serialize_plan(
    plan: TenantAdChangePlan,
    items: list[TenantAdChangePlanItem],
) -> dict[str, Any]:
    return {
        "id": str(plan.id),
        "tenant_id": str(plan.tenant_id),
        "title": plan.title,
        "status": plan.status,
        "source": plan.source,
        "summary": plan.summary,
        "engine_version": plan.engine_version,
        "evidence_json": plan.evidence_json,
        "metadata_json": plan.metadata_json,
        "created_by_user_id": str(plan.created_by_user_id) if plan.created_by_user_id else None,
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
        "reviewed_at": plan.reviewed_at.isoformat() if plan.reviewed_at else None,
        "dismissed_at": plan.dismissed_at.isoformat() if plan.dismissed_at else None,
        "items": [_serialize_item(i) for i in items],
        "executable": False,
        "read_only": True,
    }


def _validate_items(items: list[dict[str, Any]]) -> None:
    if not items:
        raise AdDecisionSupportError(
            "at least one change-plan item is required",
            details={"limit_key": "change_plan_items", "min": 1},
        )
    if len(items) > MAX_CHANGE_PLAN_ITEMS:
        raise AdDecisionSupportError(
            "too many change-plan items",
            details={"max": MAX_CHANGE_PLAN_ITEMS, "requested": len(items)},
        )
    for raw in items:
        for banned in _FORBIDDEN_ITEM_KEYS:
            if banned in raw:
                raise AdReadOnlyOperationError(
                    "change-plan items must not contain provider payloads",
                    details={"field": banned},
                )
        item_type = raw.get("item_type")
        if item_type not in CHANGE_PLAN_ITEM_TYPES:
            raise AdDecisionSupportError(
                "unsupported change-plan item type",
                details={"item_type": item_type, "allowed": sorted(CHANGE_PLAN_ITEM_TYPES)},
            )
        for required in ("observation", "reasoning", "suggested_human_action"):
            if not raw.get(required):
                raise AdDecisionSupportError(
                    f"change-plan item missing {required}",
                    details={"field": required},
                )


async def _items_for(
    db: AsyncSession, tenant_id: UUID, plan_id: UUID,
) -> list[TenantAdChangePlanItem]:
    return list(
        (
            await db.execute(
                select(TenantAdChangePlanItem)
                .where(
                    TenantAdChangePlanItem.tenant_id == tenant_id,
                    TenantAdChangePlanItem.change_plan_id == plan_id,
                )
                .order_by(TenantAdChangePlanItem.created_at.asc())
            )
        ).scalars().all()
    )


async def _get_plan_row(
    db: AsyncSession, tenant_id: UUID, plan_id: UUID,
) -> TenantAdChangePlan:
    plan = (
        await db.execute(
            select(TenantAdChangePlan).where(
                TenantAdChangePlan.tenant_id == tenant_id,
                TenantAdChangePlan.id == plan_id,
            )
        )
    ).scalar_one_or_none()
    if plan is None:
        raise AdChangePlanNotFoundError(
            "change plan not found",
            details={"change_plan_id": str(plan_id)},
        )
    return plan


async def create_change_plan(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    title: str,
    items: list[dict[str, Any]],
    source: str | None = "recommendation_engine",
    summary: str | None = None,
    evidence_json: dict[str, Any] | None = None,
    metadata_json: dict[str, Any] | None = None,
    user_id: UUID | None = None,
) -> dict[str, Any]:
    _validate_items(items)
    plan = TenantAdChangePlan(
        tenant_id=tenant_id,
        title=title,
        status="draft",
        source=source,
        summary=summary,
        engine_version=RECOMMENDATION_ENGINE_VERSION,
        evidence_json=evidence_json,
        metadata_json=metadata_json,
        created_by_user_id=user_id,
    )
    db.add(plan)
    await db.flush()

    item_rows: list[TenantAdChangePlanItem] = []
    for raw in items:
        conf = raw.get("confidence")
        confidence = Decimal(str(conf)) if conf is not None else None
        row = TenantAdChangePlanItem(
            tenant_id=tenant_id,
            change_plan_id=plan.id,
            item_type=str(raw["item_type"]),
            entity_type=raw.get("entity_type"),
            entity_id=UUID(str(raw["entity_id"])) if raw.get("entity_id") else None,
            observation=str(raw["observation"]),
            evidence_json=raw.get("evidence_json") or raw.get("evidence"),
            reasoning=str(raw["reasoning"]),
            suggested_human_action=str(raw["suggested_human_action"]),
            risk=raw.get("risk"),
            confidence=confidence,
            supporting_metrics=raw.get("supporting_metrics"),
        )
        db.add(row)
        item_rows.append(row)
    await db.flush()

    await emit_domain_event(
        db,
        "advertising.change_plan_created",
        tenant_id,
        payload={
            "change_plan_id": str(plan.id),
            "title": title,
            "item_count": len(item_rows),
            "source": source,
            "status": plan.status,
        },
        actor_type="user" if user_id else "system",
        actor_id=user_id,
        resource_type="advertising_change_plan",
        resource_id=str(plan.id),
        title="Advertising change plan created",
    )
    return _serialize_plan(plan, item_rows)


async def list_change_plans(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [TenantAdChangePlan.tenant_id == tenant_id]
    if status is not None:
        if status not in CHANGE_PLAN_STATUSES:
            raise AdChangePlanStateError("invalid change-plan status filter")
        filters.append(TenantAdChangePlan.status == status)
    total = (
        await db.execute(
            select(func.count()).select_from(TenantAdChangePlan).where(*filters)
        )
    ).scalar_one()
    rows = list(
        (
            await db.execute(
                select(TenantAdChangePlan)
                .where(*filters)
                .order_by(TenantAdChangePlan.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).scalars().all()
    )
    out: list[dict[str, Any]] = []
    for plan in rows:
        items = await _items_for(db, tenant_id, plan.id)
        out.append(_serialize_plan(plan, items))
    return out, int(total or 0)


async def get_change_plan(
    db: AsyncSession, tenant_id: UUID, plan_id: UUID,
) -> dict[str, Any]:
    plan = await _get_plan_row(db, tenant_id, plan_id)
    items = await _items_for(db, tenant_id, plan_id)
    return _serialize_plan(plan, items)


async def review_change_plan(
    db: AsyncSession, tenant_id: UUID, plan_id: UUID,
) -> dict[str, Any]:
    plan = await _get_plan_row(db, tenant_id, plan_id)
    if plan.status != "draft":
        raise AdChangePlanStateError(
            "only draft change plans can be marked reviewed",
            details={"status": plan.status},
        )
    plan.status = "reviewed"
    plan.reviewed_at = _utcnow()
    await db.flush()
    items = await _items_for(db, tenant_id, plan_id)
    return _serialize_plan(plan, items)


async def dismiss_change_plan(
    db: AsyncSession, tenant_id: UUID, plan_id: UUID,
) -> dict[str, Any]:
    plan = await _get_plan_row(db, tenant_id, plan_id)
    if plan.status not in {"draft", "reviewed"}:
        raise AdChangePlanStateError(
            "only draft or reviewed change plans can be dismissed",
            details={"status": plan.status},
        )
    plan.status = "dismissed"
    plan.dismissed_at = _utcnow()
    await db.flush()
    items = await _items_for(db, tenant_id, plan_id)
    return _serialize_plan(plan, items)


async def archive_change_plan(
    db: AsyncSession, tenant_id: UUID, plan_id: UUID,
) -> dict[str, Any]:
    plan = await _get_plan_row(db, tenant_id, plan_id)
    if plan.status not in {"reviewed", "dismissed"}:
        raise AdChangePlanStateError(
            "only reviewed or dismissed change plans can be archived",
            details={"status": plan.status},
        )
    plan.status = "archived"
    await db.flush()
    items = await _items_for(db, tenant_id, plan_id)
    return _serialize_plan(plan, items)


__all__ = [
    "create_change_plan",
    "list_change_plans",
    "get_change_plan",
    "review_change_plan",
    "dismiss_change_plan",
    "archive_change_plan",
]
