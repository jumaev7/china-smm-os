"""CRM Deal Room — workspace and AI health for sales opportunities."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.crm_deal import CrmDeal, CrmDealEvent
from app.models.crm_document import CrmDocument
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.crm_proposal import CrmProposal
from app.schemas.crm import CrmDealCreate, CrmDealEventCreate, CrmDealUpdate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.services.client_service import ClientService
from app.services.crm_service import CrmService
from app.services.deal_event_service import DEFAULT_PROBABILITY, DEAL_EVENT_TYPES, DealEventService
from app.services.document_service import _serialize_document
from app.services.proposal_service import _serialize_proposal

logger = logging.getLogger(__name__)

DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment", "won", "lost",
})

_STATUS_LABELS: dict[str, str] = {
    "new": "New",
    "proposal": "Proposal",
    "contract": "Contract",
    "invoice": "Invoice",
    "waiting_payment": "Waiting payment",
    "won": "Won",
    "lost": "Lost",
}

_HEALTH_SYSTEM = """\
You assess B2B sales deal health for operators in Uzbekistan.
Return ONLY JSON:
{
  "deal_score": 0-100 integer,
  "risk_level": "low|medium|high",
  "recommended_action": "single imperative next step for operator",
  "reasoning": "2-4 sentences explaining score and risk"
}

Rules:
- Operator acts manually — never suggest auto-send or auto status change
- Consider deal stage, proposal/document status, activity recency, lead priority
- High risk if stale follow-up, rejected proposal, or no recent activity
- Be practical for SMM/agency B2B sales
"""


def _serialize_deal(deal: CrmDeal) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    created = deal.created_at
    if created and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    days_in_pipeline = (now - created).days if created else 0

    return {
        "id": deal.id,
        "lead_id": deal.lead_id,
        "client_id": deal.client_id,
        "lead_name": deal.lead.name if deal.lead else None,
        "client_name": deal.client.company_name if deal.client else None,
        "title": deal.title,
        "status": deal.status,
        "expected_value": deal.expected_value,
        "probability": deal.probability,
        "expected_close_date": deal.expected_close_date,
        "deal_amount": deal.deal_amount,
        "currency": deal.currency or "UZS",
        "commission_percent": deal.commission_percent,
        "commission_amount": deal.commission_amount,
        "commission_status": deal.commission_status,
        "partner_commission_percent": deal.partner_commission_percent,
        "partner_commission_amount": deal.partner_commission_amount,
        "days_in_pipeline": days_in_pipeline,
        "created_at": deal.created_at,
        "updated_at": deal.updated_at,
    }


def _serialize_event(event: CrmDealEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "deal_id": event.deal_id,
        "event_type": event.event_type,
        "title": event.title,
        "payload_json": event.payload_json or {},
        "created_at": event.created_at,
    }


def _heuristic_health(deal: CrmDeal, lead: CrmLead, events: list[CrmDealEvent]) -> dict[str, Any]:
    score = deal.probability or DEFAULT_PROBABILITY.get(deal.status, 20)
    if lead.priority == "high":
        score = min(100, score + 10)
    if lead.status == "lost":
        score = max(0, score - 40)
    elif lead.status == "won":
        score = min(100, score + 15)

    now = datetime.now(timezone.utc)
    if events:
        last = events[0].created_at
        if last and last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_since = (now - last).days if last else 99
        if days_since > 14:
            score = max(0, score - 20)
        elif days_since > 7:
            score = max(0, score - 10)
    else:
        score = max(0, score - 5)

    if score >= 65:
        risk = "low"
    elif score >= 35:
        risk = "medium"
    else:
        risk = "high"

    actions = {
        "new": "Send first contact and qualify the lead.",
        "proposal": "Follow up on the proposal and address open questions.",
        "contract": "Review contract draft with client and schedule signing.",
        "invoice": "Confirm invoice details and send for payment.",
        "waiting_payment": "Follow up on payment status politely.",
        "won": "Begin onboarding and thank the client.",
        "lost": "Log reason and schedule re-engagement in 90 days.",
    }
    return {
        "deal_score": max(0, min(100, score)),
        "risk_level": risk,
        "recommended_action": actions.get(deal.status, "Review deal and plan next step."),
        "reasoning": (
            f"Deal is in '{deal.status}' stage with {deal.probability}% probability. "
            f"Lead pipeline status is '{lead.status}'. "
            "Review timeline and follow up manually as needed."
        ),
        "source": "fallback",
    }


class DealService:
    @staticmethod
    async def list_deals(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        query = (
            select(CrmDeal)
            .options(selectinload(CrmDeal.lead), selectinload(CrmDeal.client))
            .order_by(CrmDeal.updated_at.desc())
        )
        if client_id:
            query = query.where(CrmDeal.client_id == client_id)
        if status:
            query = query.where(CrmDeal.status == status)

        count_q = select(func.count()).select_from(CrmDeal)
        if client_id:
            count_q = count_q.where(CrmDeal.client_id == client_id)
        if status:
            count_q = count_q.where(CrmDeal.status == status)
        total = (await db.execute(count_q)).scalar_one()

        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize_deal(d) for d in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def create_deal(db: AsyncSession, data: CrmDealCreate) -> dict[str, Any]:
        await ClientService.get(db, data.client_id)
        lead = await CrmService._load_lead(db, data.lead_id)
        if lead.client_id != data.client_id:
            raise HTTPException(status_code=400, detail="Lead does not belong to client")

        status = data.status or "new"
        if status not in DEAL_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid deal status")

        deal = CrmDeal(
            lead_id=data.lead_id,
            client_id=data.client_id,
            title=data.title.strip()[:255],
            status=status,
            expected_value=data.expected_value or lead.estimated_value,
            probability=data.probability if data.probability is not None else DEFAULT_PROBABILITY.get(status, 10),
            expected_close_date=data.expected_close_date,
        )
        db.add(deal)
        await db.flush()
        await DealEventService.record_event(
            db, deal.id, "activity", "Deal created", {"status": status},
        )
        await db.commit()
        await db.refresh(deal, attribute_names=["lead", "client"])
        logger.info("[Deal] created: id=%s lead=%s", deal.id, data.lead_id)
        return _serialize_deal(deal)

    @staticmethod
    async def get_deal(db: AsyncSession, deal_id: UUID) -> dict[str, Any]:
        deal = await DealService._load_deal(db, deal_id)
        return await DealService._build_detail(db, deal)

    @staticmethod
    async def get_deal_by_lead(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        await CrmService._load_lead(db, lead_id)
        deal = await DealEventService.ensure_deal_for_lead(db, lead_id)
        await db.commit()
        deal = await DealService._load_deal(db, deal.id)
        return await DealService._build_detail(db, deal)

    @staticmethod
    async def update_deal(
        db: AsyncSession,
        deal_id: UUID,
        data: CrmDealUpdate,
    ) -> dict[str, Any]:
        deal = await DealService._load_deal(db, deal_id)
        old_status = deal.status
        payload = data.model_dump(exclude_unset=True)

        if "status" in payload and payload["status"] not in DEAL_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid deal status")
        if "title" in payload:
            payload["title"] = payload["title"].strip()[:255]
        if "probability" in payload and payload["probability"] is not None:
            payload["probability"] = max(0, min(100, int(payload["probability"])))

        for key, value in payload.items():
            setattr(deal, key, value)
        deal.updated_at = datetime.now(timezone.utc)

        if old_status != deal.status:
            label = _STATUS_LABELS.get(deal.status, deal.status)
            await DealEventService.record_event(
                db,
                deal.id,
                "status_change",
                f"Deal status changed to {label}",
                {"from": old_status, "to": deal.status},
            )

        await db.commit()
        await db.refresh(deal, attribute_names=["lead", "client"])
        return _serialize_deal(deal)

    @staticmethod
    async def add_event(
        db: AsyncSession,
        deal_id: UUID,
        data: CrmDealEventCreate,
    ) -> dict[str, Any]:
        deal = await DealService._load_deal(db, deal_id)
        event_type = data.event_type
        if event_type not in DEAL_EVENT_TYPES:
            raise HTTPException(status_code=400, detail="Invalid event type")

        event = await DealEventService.record_event(
            db,
            deal.id,
            event_type,
            data.title,
            data.payload_json,
        )
        await db.commit()
        await db.refresh(event)
        return _serialize_event(event)

    @staticmethod
    async def assess_health(db: AsyncSession, deal_id: UUID) -> dict[str, Any]:
        deal = await DealService._load_deal(db, deal_id, with_events=True)
        lead = deal.lead
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        events = sorted(deal.events or [], key=lambda e: e.created_at or datetime.min, reverse=True)
        proposals_r = await db.execute(
            select(CrmProposal).where(CrmProposal.lead_id == deal.lead_id).order_by(CrmProposal.created_at.desc())
        )
        proposals = proposals_r.scalars().all()
        docs_r = await db.execute(
            select(CrmDocument).where(CrmDocument.lead_id == deal.lead_id).order_by(CrmDocument.created_at.desc())
        )
        documents = docs_r.scalars().all()

        timeline_summary = "\n".join(
            f"- {e.created_at.strftime('%Y-%m-%d') if e.created_at else '?'}: {e.title}"
            for e in events[:15]
        ) or "No timeline events yet."

        kb_block = await ClientKnowledgeBaseService.build_prompt_block(
            db, deal.client_id, max_chars=1500, context="deal_health",
        )

        context = (
            f"DEAL: {deal.title} | status={deal.status} | probability={deal.probability}% | "
            f"expected_value={deal.expected_value or 'TBD'}\n"
            f"LEAD: {lead.name} | pipeline={lead.status} | priority={lead.priority} | "
            f"interest={lead.interest or 'n/a'}\n"
            f"PROPOSALS: {len(proposals)} (latest status: {proposals[0].status if proposals else 'none'})\n"
            f"DOCUMENTS: {len(documents)} "
            f"(contracts={sum(1 for d in documents if d.document_type == 'contract')}, "
            f"invoices={sum(1 for d in documents if d.document_type == 'invoice')})\n"
            f"TIMELINE:\n{timeline_summary}\n"
            f"{kb_block or ''}"
        )

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                result = _heuristic_health(deal, lead, events)
            else:
                _validate_api_key()
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _HEALTH_SYSTEM},
                        {"role": "user", "content": context[:10000]},
                    ],
                    temperature=0.35,
                    max_tokens=600,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                score = int(parsed.get("deal_score") or deal.probability or 50)
                risk = str(parsed.get("risk_level") or "medium").lower()
                if risk not in {"low", "medium", "high"}:
                    risk = "medium"
                result = {
                    "deal_score": max(0, min(100, score)),
                    "risk_level": risk,
                    "recommended_action": str(parsed.get("recommended_action") or "Review deal manually.")[:500],
                    "reasoning": str(parsed.get("reasoning") or "")[:1500],
                    "source": "ai",
                }
        except Exception as exc:
            logger.warning("[Deal] health AI fallback: deal=%s error=%s", deal_id, exc)
            result = _heuristic_health(deal, lead, events)

        logger.info(
            "[Deal] health: id=%s score=%s risk=%s source=%s",
            deal_id,
            result["deal_score"],
            result["risk_level"],
            result["source"],
        )
        return result

    @staticmethod
    async def _build_detail(db: AsyncSession, deal: CrmDeal) -> dict[str, Any]:
        lead = deal.lead
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        activities_r = await db.execute(
            select(CrmActivity)
            .where(CrmActivity.lead_id == deal.lead_id)
            .order_by(CrmActivity.created_at.desc())
        )
        activities = activities_r.scalars().all()

        proposals_r = await db.execute(
            select(CrmProposal)
            .options(selectinload(CrmProposal.lead))
            .where(CrmProposal.lead_id == deal.lead_id)
            .order_by(CrmProposal.created_at.desc())
        )
        proposals = proposals_r.scalars().all()

        docs_r = await db.execute(
            select(CrmDocument)
            .options(selectinload(CrmDocument.lead), selectinload(CrmDocument.proposal))
            .where(CrmDocument.lead_id == deal.lead_id)
            .order_by(CrmDocument.created_at.desc())
        )
        documents = docs_r.scalars().all()

        events_r = await db.execute(
            select(CrmDealEvent)
            .where(CrmDealEvent.deal_id == deal.id)
            .order_by(CrmDealEvent.created_at.desc())
        )
        events = events_r.scalars().all()

        from app.services.crm_service import _serialize_activity, _serialize_lead

        base = _serialize_deal(deal)
        base["lead"] = _serialize_lead(lead)
        base["proposals"] = [_serialize_proposal(p) for p in proposals]
        base["contracts"] = [_serialize_document(d) for d in documents if d.document_type == "contract"]
        base["invoices"] = [_serialize_document(d) for d in documents if d.document_type == "invoice"]
        base["activities"] = [_serialize_activity(a) for a in activities]
        base["events"] = [_serialize_event(e) for e in events]
        return base

    @staticmethod
    async def _load_deal(
        db: AsyncSession,
        deal_id: UUID,
        *,
        with_events: bool = False,
    ) -> CrmDeal:
        opts = [selectinload(CrmDeal.lead), selectinload(CrmDeal.client)]
        if with_events:
            opts.append(selectinload(CrmDeal.events))
        result = await db.execute(
            select(CrmDeal).options(*opts).where(CrmDeal.id == deal_id)
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")
        return deal
