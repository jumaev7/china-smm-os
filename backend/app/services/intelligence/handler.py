"""Intelligence event bus handler — converts platform events into marketing signals."""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events.types import PlatformEvent, SubscriberResult
from app.services.event_handlers.base import IntegrationHandler
from app.services.intelligence.collectors import collect_signals
from app.services.intelligence.recommendation_engine import RecommendationEngine
from app.services.intelligence.scoring_engine import ScoringEngine
from app.services.intelligence.store import IntelligenceStore

logger = logging.getLogger(__name__)


class IntelligenceEventHandler(IntegrationHandler):
    """Subscribe to platform events and persist normalized marketing intelligence."""

    name = "intelligence"
    integration_key = "intelligence"

    async def handle(self, db: AsyncSession, event: PlatformEvent) -> SubscriberResult:
        if not self._is_enabled(event):
            return self._skip("integration disabled for event type")

        try:
            tenant_id = event.require_tenant_id()
        except ValueError as exc:
            return self._skip(str(exc))

        signals = collect_signals(event)
        if not signals:
            return self._skip("no collector matched")

        inserted = 0
        for signal in signals:
            row = await IntelligenceStore.insert_signal(db, signal)
            if row is not None:
                inserted += 1

        if inserted == 0:
            return self._handled(detail="duplicate_signals")

        # Recompute scores + recommendations after new intelligence arrives.
        scores = await ScoringEngine.compute_all(db, tenant_id, persist=True, record_history=True)
        recommendations = await RecommendationEngine.compute_all(
            db, tenant_id, scores=scores, persist=True, record_history=True,
        )

        # Capture a concise insight for the dashboard.
        overall = next((s for s in scores if s.category == "overall"), None)
        top_rec = recommendations[0] if recommendations else None
        await IntelligenceStore.add_insight(
            db,
            tenant_id=tenant_id,
            kind="signal_summary",
            title=f"Processed {inserted} marketing signal(s)",
            summary=(
                f"Event {event.event_type} produced {inserted} new signal(s). "
                f"Overall score={overall.score if overall else 'n/a'}."
            ),
            category=signals[0].source,
            severity=signals[0].severity,
            explanation=overall.explanation if overall else None,
            evidence={
                "event_type": event.event_type,
                "inserted": inserted,
                "top_recommendation": top_rec.recommendation_key if top_rec else None,
                "signal_types": [s.signal_type for s in signals],
            },
            related_signal_ids=[str(s.signal_id) for s in signals],
        )

        logger.debug(
            "[Intelligence] tenant=%s event=%s inserted=%s score=%s recs=%s",
            tenant_id,
            event.event_type,
            inserted,
            overall.score if overall else None,
            len(recommendations),
        )
        return self._handled(detail=f"inserted={inserted}")
