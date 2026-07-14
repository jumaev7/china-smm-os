"""Fixed automation action executors — allowlisted, tenant-scoped, no dynamic imports."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.automation import AUTOMATION_ACTION_TYPES
from app.models.client import Client
from app.models.customer_success_journey import TenantCustomerSuccessJourney
from app.models.platform_event import TenantActivityEvent, TenantEventNotification
from app.models.tenant_onboarding import TenantOnboardingProgress
from app.schemas.crm import CrmLeadCreate


@dataclass
class ActionResult:
    success: bool
    payload: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _render_template(template: str, context: dict[str, Any]) -> str:
    result = template
    for key, value in context.items():
        if value is not None:
            result = result.replace(f"{{{key}}}", str(value))
    return result


def validate_action_config(action_type: str, config: dict[str, Any] | None) -> dict[str, Any]:
    if action_type not in AUTOMATION_ACTION_TYPES:
        raise ValueError(f"Unsupported action type: {action_type}")
    cfg = dict(config or {})
    if action_type == "create_notification":
        if not cfg.get("title"):
            raise ValueError("create_notification requires title")
        if cfg.get("category") not in {
            "publishing", "crm", "integrations", "automation", "journey", "billing", "security", "platform",
        }:
            cfg.setdefault("category", "automation")
        cfg.setdefault("severity", "info")
    elif action_type == "create_crm_lead":
        cfg.setdefault("source", "other")
        cfg.setdefault("name_template", "Automation lead")
    elif action_type == "record_activity":
        if not cfg.get("title"):
            raise ValueError("record_activity requires title")
        cfg.setdefault("category", "automation")
    elif action_type == "update_customer_success_progress":
        cfg.setdefault("timeline_title", "Automation milestone")
    return cfg


async def _resolve_client_id(db: AsyncSession, tenant_id: UUID) -> UUID | None:
    row = (
        await db.execute(
            select(Client.id).where(Client.tenant_id == tenant_id).limit(1),
        )
    ).scalar_one_or_none()
    return row


async def execute_create_notification(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    event_type: str,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> ActionResult:
    context = {**payload, **(payload.get("test_context") or {})}
    title = _render_template(str(config.get("title", "")), context)
    body = _render_template(str(config.get("body", "")), context) if config.get("body") else None
    row = TenantEventNotification(
        tenant_id=tenant_id,
        event_id=event_id,
        event_type=event_type,
        category=str(config.get("category", "automation")),
        title=title,
        body=body,
        severity=str(config.get("severity", "info")),
        action_url=config.get("action_url"),
        resource_type=config.get("resource_type"),
        resource_id=str(config.get("resource_id")) if config.get("resource_id") else None,
        payload={"automation_action": True, **payload},
        status="unread",
    )
    db.add(row)
    await db.flush()
    return ActionResult(success=True, payload={"notification_id": str(row.id)})


async def execute_create_crm_lead(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> ActionResult:
    from app.services.crm_service import CrmService

    client_id = config.get("client_id")
    if client_id:
        client_uuid = UUID(str(client_id))
    else:
        resolved = await _resolve_client_id(db, tenant_id)
        if resolved is None:
            return ActionResult(
                success=False,
                error_code="no_client",
                error_message="Tenant has no client for CRM lead creation",
            )
        client_uuid = resolved

    context = {**payload, **(payload.get("test_context") or {})}
    name = _render_template(str(config.get("name_template", "Automation lead")), context)
    notes = _render_template(str(config.get("notes_template", "")), context) if config.get("notes_template") else None
    lead_data = CrmLeadCreate(
        client_id=client_uuid,
        name=name[:255],
        source=config.get("source", "other"),
        notes=notes,
        status="new",
        priority=config.get("priority", "medium"),
    )
    try:
        result = await CrmService.create_lead(db, lead_data)
    except Exception as exc:
        return ActionResult(success=False, error_code="crm_error", error_message=str(exc))
    out: dict[str, Any] = {"lead_id": str(result.get("id")) if result.get("id") is not None else None}
    buyer_id = payload.get("buyer_id")
    if buyer_id:
        out["source_buyer_id"] = str(buyer_id)
    return ActionResult(success=True, payload=out)


async def execute_record_activity(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    event_type: str,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> ActionResult:
    context = {**payload, **(payload.get("test_context") or {})}
    title = _render_template(str(config.get("title", "Automation activity")), context)
    description = (
        _render_template(str(config.get("description", "")), context) if config.get("description") else None
    )
    row = TenantActivityEvent(
        tenant_id=tenant_id,
        event_id=event_id,
        event_type=event_type,
        category=str(config.get("category", "automation")),
        title=title,
        description=description,
        resource_type=config.get("resource_type"),
        resource_id=str(config.get("resource_id")) if config.get("resource_id") else None,
        payload={"automation_action": True, **payload},
        occurred_at=_utcnow(),
    )
    db.add(row)
    await db.flush()
    return ActionResult(success=True, payload={"activity_id": str(row.id)})


async def execute_update_customer_success_progress(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    event_type: str,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> ActionResult:
    context = {**payload, **(payload.get("test_context") or {})}
    title = _render_template(str(config.get("timeline_title", "Automation milestone")), context)
    entry = {
        "event_id": str(event_id),
        "event_type": event_type,
        "title": title,
        "occurred_at": _utcnow().isoformat(),
        "payload": payload,
        "source": "automation",
    }
    progress = (
        await db.execute(
            select(TenantOnboardingProgress).where(TenantOnboardingProgress.tenant_id == tenant_id),
        )
    ).scalar_one_or_none()
    if progress is not None:
        progress.last_activity_at = _utcnow()

    journey = (
        await db.execute(
            select(TenantCustomerSuccessJourney).where(
                TenantCustomerSuccessJourney.tenant_id == tenant_id,
            ),
        )
    ).scalar_one_or_none()
    if journey is not None:
        timeline = list(journey.timeline_entries or [])
        timeline.append(entry)
        journey.timeline_entries = timeline[-200:]
        journey.last_refreshed_at = _utcnow()
    await db.flush()
    return ActionResult(
        success=True,
        payload={"journey_updated": journey is not None, "progress_updated": progress is not None},
    )


_ACTION_EXECUTORS = {
    "create_notification": execute_create_notification,
    "create_crm_lead": execute_create_crm_lead,
    "record_activity": execute_record_activity,
    "update_customer_success_progress": execute_update_customer_success_progress,
}


async def execute_action(
    db: AsyncSession,
    *,
    action_type: str,
    tenant_id: UUID,
    event_id: UUID,
    event_type: str,
    config: dict[str, Any],
    payload: dict[str, Any],
) -> ActionResult:
    executor = _ACTION_EXECUTORS.get(action_type)
    if executor is None:
        return ActionResult(
            success=False,
            error_code="unknown_action",
            error_message=f"Unsupported action: {action_type}",
        )
    validated = validate_action_config(action_type, config)
    if action_type == "create_crm_lead":
        return await executor(db, tenant_id=tenant_id, config=validated, payload=payload)
    if action_type in {"create_notification", "record_activity", "update_customer_success_progress"}:
        return await executor(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            event_type=event_type,
            config=validated,
            payload=payload,
        )
    return ActionResult(success=False, error_code="unknown_action", error_message="No executor")


def synthetic_test_event_id() -> UUID:
    return uuid4()
