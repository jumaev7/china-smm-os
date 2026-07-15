"""CRM signal collector."""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID, uuid5, NAMESPACE_URL

from app.core.events.types import PlatformEvent
from app.services.intelligence.collectors.base import SignalCollector
from app.services.intelligence.normalizer import normalize_signal
from app.services.intelligence.types import NormalizedSignal

_WON_STAGES = frozenset({"won", "closed_won", "closed-won", "victory"})
_LOST_STAGES = frozenset({"lost", "closed_lost", "closed-lost", "rejected"})


def _derived_signal_id(event_id: UUID, signal_type: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"mip:{event_id}:{signal_type}")


class CrmCollector(SignalCollector):
    name = "crm"
    source = "crm"
    event_types = frozenset({
        "tenant.crm.lead_created",
        "tenant.crm.deal_stage_changed",
        "tenant.buyer.created",
    })

    def collect(self, event: PlatformEvent) -> list[NormalizedSignal]:
        tenant_id = event.require_tenant_id()
        payload = event.payload or {}
        signals: list[NormalizedSignal] = []

        if event.event_type == "tenant.crm.lead_created":
            signals.append(
                normalize_signal(
                    tenant_id=tenant_id,
                    signal_type="crm.lead_created",
                    source=self.source,
                    severity="success",
                    entity_type=event.resource_type or "lead",
                    entity_id=event.resource_id,
                    occurred_at=event.occurred_at,
                    metadata={"title": event.title, "payload": payload},
                    signal_id=event.event_id,
                    platform_event_id=event.event_id,
                    platform_event_type=event.event_type,
                )
            )
        elif event.event_type == "tenant.buyer.created":
            signals.append(
                normalize_signal(
                    tenant_id=tenant_id,
                    signal_type="crm.buyer_created",
                    source=self.source,
                    severity="success",
                    entity_type=event.resource_type or "buyer",
                    entity_id=event.resource_id,
                    occurred_at=event.occurred_at,
                    metadata={"title": event.title, "payload": payload},
                    signal_id=event.event_id,
                    platform_event_id=event.event_id,
                    platform_event_type=event.event_type,
                )
            )
        elif event.event_type == "tenant.crm.deal_stage_changed":
            signals.append(
                normalize_signal(
                    tenant_id=tenant_id,
                    signal_type="crm.deal_stage_changed",
                    source=self.source,
                    severity="info",
                    entity_type=event.resource_type or "deal",
                    entity_id=event.resource_id,
                    occurred_at=event.occurred_at,
                    metadata={"title": event.title, "payload": payload},
                    signal_id=event.event_id,
                    platform_event_id=event.event_id,
                    platform_event_type=event.event_type,
                )
            )
            to_stage = str(payload.get("to_stage") or payload.get("stage") or "").strip().lower()
            if to_stage in _WON_STAGES:
                signals.append(
                    normalize_signal(
                        tenant_id=tenant_id,
                        signal_type="crm.deal_won",
                        source=self.source,
                        severity="success",
                        confidence=Decimal("0.900"),
                        entity_type=event.resource_type or "deal",
                        entity_id=event.resource_id,
                        occurred_at=event.occurred_at,
                        metadata={"to_stage": to_stage, "payload": payload},
                        signal_id=_derived_signal_id(event.event_id, "crm.deal_won"),
                        platform_event_id=event.event_id,
                        platform_event_type=event.event_type,
                    )
                )
            elif to_stage in _LOST_STAGES:
                signals.append(
                    normalize_signal(
                        tenant_id=tenant_id,
                        signal_type="crm.deal_lost",
                        source=self.source,
                        severity="warning",
                        confidence=Decimal("0.900"),
                        entity_type=event.resource_type or "deal",
                        entity_id=event.resource_id,
                        occurred_at=event.occurred_at,
                        metadata={"to_stage": to_stage, "payload": payload},
                        signal_id=_derived_signal_id(event.event_id, "crm.deal_lost"),
                        platform_event_id=event.event_id,
                        platform_event_type=event.event_type,
                    )
                )
        return signals
