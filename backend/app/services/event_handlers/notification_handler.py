"""Notification integration — in-app tenant notifications from events."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent, SubscriberResult
from app.models.platform_event import NOTIFICATION_CATEGORIES, TenantEventNotification
from app.services.event_handlers.base import IntegrationHandler

_SEVERITY_BY_CATEGORY = {
    "crm": "info",
    "publishing": "success",
    "onboarding": "info",
    "customer_success": "success",
    "automation": "info",
    "auth": "warning",
    "content": "info",
    "notification": "info",
    "integrations": "warning",
    "billing": "info",
    "security": "warning",
}

_CATEGORY_NORMALIZE = {
    "auth": "security",
    "content": "publishing",
    "onboarding": "platform",
    "customer_success": "journey",
    "notification": "platform",
    "general": "platform",
}

_ACTION_URL_BY_RESOURCE = {
    "deal": "/deals",
    "lead": "/leads",
    "content": "/content",
    "proposal": "/proposals",
    "buyer": "/buyers",
    "integration": "/integrations",
    "publishing": "/publishing",
}


def _humanize_event_type(event_type: str) -> str:
    tail = event_type.rsplit(".", maxsplit=1)[-1]
    return tail.replace("_", " ").strip().title() or event_type


def _normalize_category(raw: str) -> str:
    normalized = _CATEGORY_NORMALIZE.get(raw, raw)
    if normalized in NOTIFICATION_CATEGORIES:
        return normalized
    return "platform"


def _resolve_severity(category: str, event: PlatformEvent) -> str:
    payload = event.payload or {}
    raw = payload.get("severity") if isinstance(payload, dict) else None
    if isinstance(raw, str) and raw in {"info", "success", "warning", "error", "critical"}:
        return raw
    return _SEVERITY_BY_CATEGORY.get(category, "info")


def _resolve_action_url(event: PlatformEvent) -> str | None:
    payload = event.payload or {}
    if isinstance(payload, dict):
        for key in ("action_url", "href", "url"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if event.resource_type:
        mapped = _ACTION_URL_BY_RESOURCE.get(event.resource_type)
        if mapped:
            return mapped
    return None


class NotificationEventHandler(IntegrationHandler):
    name = "notification"
    integration_key = "notification"

    async def handle(self, db: AsyncSession, event: PlatformEvent) -> SubscriberResult:
        if not self._is_enabled(event):
            return self._skip("integration disabled for event type")

        definition = self._definition(event)
        tenant_id = event.require_tenant_id()
        registry_category = definition.category if definition else "platform"
        category = _normalize_category(registry_category)
        title = event.title or _humanize_event_type(event.event_type)
        body = (
            event.description
            or (definition.description if definition else None)
            or title
        )
        severity = _resolve_severity(registry_category, event)
        action_url = _resolve_action_url(event)
        row = TenantEventNotification(
            tenant_id=tenant_id,
            event_id=event.event_id,
            event_type=event.event_type,
            category=category,
            title=title,
            body=body,
            severity=severity,
            is_read=False,
            action_url=action_url,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            payload=event.payload or None,
            status="unread",
        )
        db.add(row)
        await db.flush()
        return self._handled(detail=str(row.id))
