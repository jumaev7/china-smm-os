"""Platform event registry — canonical catalog with Marketing Intelligence flags."""
from __future__ import annotations

from app.core.events.types import EventDefinition, EventIntegrations


def _def(
    event_type: str,
    *,
    category: str,
    description: str,
    integrations: EventIntegrations | None = None,
    tenant_scoped: bool = True,
) -> EventDefinition:
    return EventDefinition(
        event_type=event_type,
        category=category,
        description=description,
        integrations=integrations or EventIntegrations(),
        tenant_scoped=tenant_scoped,
    )


# Canonical platform event catalog — extend here as domains emit events.
PLATFORM_EVENT_DEFINITIONS: tuple[EventDefinition, ...] = (
    _def(
        "tenant.user.login",
        category="auth",
        description="Tenant user signed in",
        integrations=EventIntegrations(audit=True, activity=True),
    ),
    _def(
        "tenant.content.created",
        category="content",
        description="Content item created",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            customer_success=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.content.published",
        category="publishing",
        description="Content published to a channel",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            customer_success=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.crm.lead_created",
        category="crm",
        description="CRM lead created",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            customer_success=True,
            automation=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.crm.deal_stage_changed",
        category="crm",
        description="Deal moved to a new pipeline stage",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            customer_success=True,
            automation=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.onboarding.step_completed",
        category="onboarding",
        description="Onboarding checklist step completed",
        integrations=EventIntegrations(
            activity=True,
            customer_success=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.onboarding.platform_ready",
        category="onboarding",
        description="Tenant reached platform-ready milestone",
        integrations=EventIntegrations(
            activity=True,
            notification=True,
            customer_success=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.automation.triggered",
        category="automation",
        description="Automation rule or workflow trigger fired",
        integrations=EventIntegrations(activity=True, automation=True, intelligence=True),
    ),
    _def(
        "tenant.notification.sent",
        category="notification",
        description="In-app notification created for tenant users",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.customer_success.milestone",
        category="customer_success",
        description="Customer success journey milestone achieved",
        integrations=EventIntegrations(
            activity=True,
            notification=True,
            customer_success=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.content.publish_failed",
        category="publishing",
        description="Content publish attempt failed",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            automation=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.content.publish_partial_failed",
        category="publishing",
        description="Content publish attempt partially failed across platforms",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            automation=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.integration.disconnected",
        category="integrations",
        description="Platform integration disconnected",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            customer_success=True,
            automation=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.buyer.created",
        category="crm",
        description="Buyer record created",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            customer_success=True,
            automation=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.publishing.review_completed",
        category="publishing",
        description="Deterministic publishing review completed",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.score_low",
        category="publishing",
        description="Publishing quality score below threshold",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.critical_issue_detected",
        category="publishing",
        description="Critical publishing review issue detected",
        integrations=EventIntegrations(
            activity=True,
            notification=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.publishing.platform_fit_low",
        category="publishing",
        description="Platform fit score below threshold",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.review_became_stale",
        category="publishing",
        description="Publishing review became stale after content edit",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.optimization_requested",
        category="publishing",
        description="Deterministic content optimization run requested",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.variant_generated",
        category="publishing",
        description="Content optimization variant generated",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.variant_accepted",
        category="publishing",
        description="Content optimization variant accepted",
        integrations=EventIntegrations(audit=True, activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.variant_rejected",
        category="publishing",
        description="Content optimization variant rejected",
        integrations=EventIntegrations(audit=True, activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.variant_applied",
        category="publishing",
        description="Content optimization variant applied to source content",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            intelligence=True,
        ),
    ),
    _def(
        "tenant.publishing.variant_stale",
        category="publishing",
        description="Content optimization variant became stale after source change",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "tenant.publishing.optimization_failed",
        category="publishing",
        description="Deterministic content optimization run failed",
        integrations=EventIntegrations(
            audit=True,
            activity=True,
            notification=True,
            intelligence=True,
        ),
    ),
    # Governed AI Content Adaptation (Phase 2B)
    _def(
        "ai.content_adaptation_requested",
        category="publishing",
        description="AI content adaptation requested",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "ai.content_adaptation_completed",
        category="publishing",
        description="AI content adaptation completed",
        integrations=EventIntegrations(activity=True, intelligence=True, audit=True),
    ),
    _def(
        "ai.content_adaptation_failed",
        category="publishing",
        description="AI content adaptation failed",
        integrations=EventIntegrations(
            audit=True, activity=True, notification=True, intelligence=True,
        ),
    ),
    _def(
        "ai.content_validation_failed",
        category="publishing",
        description="AI generation failed factual or safety validation",
        integrations=EventIntegrations(activity=True, intelligence=True, audit=True),
    ),
    _def(
        "ai.quota_exceeded",
        category="publishing",
        description="AI quota exceeded for tenant",
        integrations=EventIntegrations(activity=True, intelligence=True, notification=True),
    ),
    _def(
        "ai.variant_generated",
        category="publishing",
        description="AI-assisted content variant generated",
        integrations=EventIntegrations(activity=True, intelligence=True),
    ),
    _def(
        "ai.variant_accepted",
        category="publishing",
        description="AI-assisted content variant accepted",
        integrations=EventIntegrations(audit=True, activity=True, intelligence=True),
    ),
    _def(
        "ai.variant_rejected",
        category="publishing",
        description="AI-assisted content variant rejected",
        integrations=EventIntegrations(audit=True, activity=True, intelligence=True),
    ),
    _def(
        "ai.variant_applied",
        category="publishing",
        description="AI-assisted content variant applied to source",
        integrations=EventIntegrations(
            audit=True, activity=True, notification=True, intelligence=True,
        ),
    ),
    _def(
        "brand.profile_published",
        category="brand",
        description="Tenant brand profile version published",
        integrations=EventIntegrations(audit=True, activity=True, intelligence=True),
    ),
)


class EventRegistry:
    """Read-only catalog and lookup for registered event types."""

    def __init__(self, definitions: tuple[EventDefinition, ...] | None = None) -> None:
        defs = definitions or PLATFORM_EVENT_DEFINITIONS
        self._by_type: dict[str, EventDefinition] = {d.event_type: d for d in defs}

    def get(self, event_type: str) -> EventDefinition | None:
        return self._by_type.get(event_type)

    def require(self, event_type: str) -> EventDefinition:
        definition = self.get(event_type)
        if definition is None:
            raise KeyError(event_type)
        return definition

    def list_all(self) -> list[EventDefinition]:
        return list(self._by_type.values())

    def list_by_category(self, category: str) -> list[EventDefinition]:
        return [d for d in self._by_type.values() if d.category == category]

    def is_registered(self, event_type: str) -> bool:
        return event_type in self._by_type


# Process-wide singleton registry instance.
event_registry = EventRegistry()
