"""Auto timeline events for CRM deals."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crm_deal import CrmDeal, CrmDealEvent
from app.models.crm_lead import CrmLead

logger = logging.getLogger(__name__)

DEAL_EVENT_TYPES = frozenset({
    "activity", "proposal", "contract", "invoice", "note", "status_change",
})

DEFAULT_PROBABILITY: dict[str, int] = {
    "new": 10,
    "proposal": 25,
    "contract": 50,
    "invoice": 70,
    "waiting_payment": 85,
    "won": 100,
    "lost": 0,
}


def _deal_title_for_lead(lead: CrmLead) -> str:
    if lead.company:
        return f"{lead.name} — {lead.company}"
    return lead.name


class DealEventService:
    @staticmethod
    async def ensure_deal_for_lead(
        db: AsyncSession,
        lead_id: UUID,
        *,
        lead: CrmLead | None = None,
    ) -> CrmDeal:
        result = await db.execute(
            select(CrmDeal)
            .where(CrmDeal.lead_id == lead_id)
            .order_by(CrmDeal.created_at.desc())
            .limit(1)
        )
        deal = result.scalar_one_or_none()
        if deal:
            return deal

        if lead is None:
            result = await db.execute(select(CrmLead).where(CrmLead.id == lead_id))
            lead = result.scalar_one_or_none()
            if not lead:
                raise ValueError(f"Lead not found: {lead_id}")

        deal = CrmDeal(
            lead_id=lead.id,
            client_id=lead.client_id,
            title=_deal_title_for_lead(lead),
            status="new",
            expected_value=lead.estimated_value,
            probability=DEFAULT_PROBABILITY["new"],
        )
        db.add(deal)
        await db.flush()
        logger.info("[Deal] auto-created: id=%s lead=%s", deal.id, lead_id)
        return deal

    @staticmethod
    async def record_event(
        db: AsyncSession,
        deal_id: UUID,
        event_type: str,
        title: str,
        payload: dict[str, Any] | None = None,
    ) -> CrmDealEvent:
        if event_type not in DEAL_EVENT_TYPES:
            event_type = "note"
        event = CrmDealEvent(
            deal_id=deal_id,
            event_type=event_type,
            title=title.strip()[:255],
            payload_json=payload or {},
        )
        db.add(event)
        await db.flush()
        logger.info("[Deal] event: deal=%s type=%s title=%s", deal_id, event_type, title[:80])
        return event

    @staticmethod
    async def record_for_lead(
        db: AsyncSession,
        lead_id: UUID,
        event_type: str,
        title: str,
        payload: dict[str, Any] | None = None,
        *,
        lead: CrmLead | None = None,
    ) -> CrmDealEvent:
        deal = await DealEventService.ensure_deal_for_lead(db, lead_id, lead=lead)
        return await DealEventService.record_event(db, deal.id, event_type, title, payload)
