"""AI Sales Agent v2 — proactive CRM monitoring and recommendations."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.crm_deal import CrmDeal, CrmDealEvent
from app.models.crm_document import CrmDocument
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.operator_task import OperatorTask
from app.models.partner import Partner
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.sales_agent_recommendation import SalesAgentRecommendation
from app.schemas.operator_task import OperatorTaskCreate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.operator_task_service import OperatorTaskService

logger = logging.getLogger(__name__)

_AI_ENRICH_MAX = 5
PRIORITIES = frozenset({"high", "medium", "low"})
OPEN_STATUSES = frozenset({"new", "accepted"})

_LEAD_STALE_DAYS = 7
_DEAL_STALE_DAYS = 14
_PROPOSAL_STALL_DAYS = 7
_PARTNER_STALE_DAYS = 14
_HIGH_VALUE_THRESHOLD = Decimal("5000000")
_ACTIVE_DEAL = frozenset({"new", "proposal", "contract", "invoice", "waiting_payment"})

_AI_SYSTEM = """\
You enrich a sales agent recommendation for an operator (manual actions only).
Return ONLY JSON:
{
  "title": "short imperative title",
  "description": "2-3 sentences explaining why now",
  "suggested_action": "single imperative next step",
  "suggested_message": "draft message in lead language for operator to review and send manually",
  "priority": "high|medium|low"
}

Rules:
- NEVER imply auto-send or auto status change
- Match lead language (ru/uz/en/zh) in suggested_message
- Be specific to the CRM context provided
"""


@dataclass
class _Candidate:
    recommendation_type: str
    client_id: UUID
    lead_id: UUID | None
    deal_id: UUID | None
    partner_id: UUID | None
    priority: str
    title: str
    description: str
    suggested_action: str
    suggested_message: str
    dedupe_key: str
    context: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _serialize_rec(rec: SalesAgentRecommendation) -> dict[str, Any]:
    return {
        "id": rec.id,
        "client_id": rec.client_id,
        "client_name": rec.client.company_name if rec.client else None,
        "lead_id": rec.lead_id,
        "lead_name": rec.lead.name if rec.lead else None,
        "deal_id": rec.deal_id,
        "deal_title": rec.deal.title if rec.deal else None,
        "partner_id": rec.partner_id,
        "partner_name": getattr(rec, "_partner_name", None),
        "recommendation_type": rec.recommendation_type,
        "title": rec.title,
        "description": rec.description,
        "priority": rec.priority,
        "suggested_message": rec.suggested_message,
        "suggested_action": rec.suggested_action,
        "status": rec.status,
        "linked_task_id": rec.linked_task_id,
        "created_at": rec.created_at,
        "updated_at": rec.updated_at,
    }


async def _last_lead_touch(db: AsyncSession, lead_id: UUID) -> datetime | None:
    act_r = await db.execute(
        select(func.max(CrmActivity.created_at)).where(CrmActivity.lead_id == lead_id)
    )
    last_act = act_r.scalar_one_or_none()
    lead_r = await db.execute(select(CrmLead.updated_at).where(CrmLead.id == lead_id))
    updated = lead_r.scalar_one_or_none()
    candidates = [_aware(last_act), _aware(updated)]
    valid = [c for c in candidates if c]
    return max(valid) if valid else None


async def _last_deal_touch(db: AsyncSession, deal_id: UUID, lead_id: UUID) -> datetime | None:
    ev_r = await db.execute(
        select(func.max(CrmDealEvent.created_at)).where(CrmDealEvent.deal_id == deal_id)
    )
    last_ev = ev_r.scalar_one_or_none()
    last_lead = await _last_lead_touch(db, lead_id)
    candidates = [_aware(last_ev), last_lead]
    valid = [c for c in candidates if c]
    return max(valid) if valid else None


class SalesAgentService:
    @staticmethod
    async def scan(db: AsyncSession) -> dict[str, Any]:
        candidates = await SalesAgentService._collect_candidates(db)
        created = 0
        skipped = 0

        for idx, cand in enumerate(candidates):
            exists = await db.execute(
                select(SalesAgentRecommendation.id).where(
                    SalesAgentRecommendation.dedupe_key == cand.dedupe_key,
                    SalesAgentRecommendation.status.in_(tuple(OPEN_STATUSES)),
                )
            )
            if exists.scalar_one_or_none():
                skipped += 1
                continue

            enriched = await SalesAgentService._enrich_candidate(
                db, cand, allow_ai=idx < _AI_ENRICH_MAX,
            )
            rec = SalesAgentRecommendation(
                client_id=cand.client_id,
                lead_id=cand.lead_id,
                deal_id=cand.deal_id,
                partner_id=cand.partner_id,
                recommendation_type=cand.recommendation_type,
                title=enriched["title"][:255],
                description=enriched["description"],
                priority=enriched["priority"],
                suggested_message=enriched.get("suggested_message"),
                suggested_action=enriched.get("suggested_action"),
                status="new",
                dedupe_key=cand.dedupe_key,
            )
            db.add(rec)
            created += 1

        await db.commit()
        logger.info("[SalesAgent] scan: candidates=%s created=%s skipped=%s", len(candidates), created, skipped)
        return {"scanned": len(candidates), "created": created, "skipped_duplicates": skipped}

    @staticmethod
    async def list_recommendations(
        db: AsyncSession,
        *,
        status: str | None = None,
        priority: str | None = None,
        client_id: UUID | None = None,
        recommendation_type: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        priority_rank = case(
            (SalesAgentRecommendation.priority == "high", 1),
            (SalesAgentRecommendation.priority == "medium", 2),
            else_=3,
        )
        query = (
            select(SalesAgentRecommendation)
            .options(
                selectinload(SalesAgentRecommendation.client),
                selectinload(SalesAgentRecommendation.lead),
                selectinload(SalesAgentRecommendation.deal),
            )
            .order_by(
                priority_rank,
                SalesAgentRecommendation.created_at.desc(),
            )
        )
        if status:
            query = query.where(SalesAgentRecommendation.status == status)
        else:
            query = query.where(SalesAgentRecommendation.status != "dismissed")
        if priority:
            query = query.where(SalesAgentRecommendation.priority == priority)
        if client_id:
            query = query.where(SalesAgentRecommendation.client_id == client_id)
        if recommendation_type:
            query = query.where(SalesAgentRecommendation.recommendation_type == recommendation_type)

        count_q = select(func.count()).select_from(SalesAgentRecommendation)
        if status:
            count_q = count_q.where(SalesAgentRecommendation.status == status)
        else:
            count_q = count_q.where(SalesAgentRecommendation.status != "dismissed")
        if priority:
            count_q = count_q.where(SalesAgentRecommendation.priority == priority)
        if client_id:
            count_q = count_q.where(SalesAgentRecommendation.client_id == client_id)
        if recommendation_type:
            count_q = count_q.where(SalesAgentRecommendation.recommendation_type == recommendation_type)
        total = (await db.execute(count_q)).scalar_one()

        result = await db.execute(query.offset(skip).limit(limit))
        recs = list(result.scalars().unique().all())

        partner_ids = {r.partner_id for r in recs if r.partner_id}
        partner_names: dict[UUID, str] = {}
        if partner_ids:
            pr = await db.execute(select(Partner).where(Partner.id.in_(partner_ids)))
            for p in pr.scalars().all():
                partner_names[p.id] = p.name

        items = []
        for rec in recs:
            if rec.partner_id:
                rec._partner_name = partner_names.get(rec.partner_id)  # noqa: SLF001
            items.append(_serialize_rec(rec))
        return {"items": items, "total": total}

    @staticmethod
    async def summary(db: AsyncSession) -> dict[str, Any]:
        now = _utc_now()
        high = await db.scalar(
            select(func.count()).select_from(SalesAgentRecommendation).where(
                SalesAgentRecommendation.status == "new",
                SalesAgentRecommendation.priority == "high",
            )
        )
        new_count = await db.scalar(
            select(func.count()).select_from(SalesAgentRecommendation).where(
                SalesAgentRecommendation.status == "new",
            )
        )
        overdue = await db.scalar(
            select(func.count()).select_from(CrmLead).where(
                CrmLead.next_follow_up_at.isnot(None),
                CrmLead.next_follow_up_at < now,
                CrmLead.status.notin_(("won", "lost")),
            )
        )
        unpaid = await db.scalar(
            select(func.count()).select_from(CrmDocument).where(
                CrmDocument.document_type == "invoice",
                CrmDocument.status == "sent",
            )
        )
        risky = await db.scalar(
            select(func.count()).select_from(SalesAgentRecommendation).where(
                SalesAgentRecommendation.status == "new",
                SalesAgentRecommendation.recommendation_type == "risk_warning",
            )
        )
        return {
            "high_priority_count": int(high or 0),
            "overdue_followups": int(overdue or 0),
            "unpaid_invoices": int(unpaid or 0),
            "risky_deals": int(risky or 0),
            "new_recommendations": int(new_count or 0),
        }

    @staticmethod
    async def accept(db: AsyncSession, recommendation_id: UUID) -> dict[str, Any]:
        rec = await SalesAgentService._load_rec(db, recommendation_id)
        if rec.status != "new":
            raise HTTPException(status_code=400, detail="Recommendation already handled")

        task_data = OperatorTaskCreate(
            client_id=rec.client_id,
            source_type="sales_agent",
            source_id=rec.id,
            title=rec.title[:255],
            description=(rec.description or "")[:2000],
            priority=rec.priority if rec.priority in PRIORITIES else "medium",
            status="todo",
            created_by="system",
        )
        try:
            task_result = await OperatorTaskService.create_task(db, task_data)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            existing = await db.execute(
                select(OperatorTask).where(
                    OperatorTask.source_type == "sales_agent",
                    OperatorTask.source_id == rec.id,
                )
            )
            task = existing.scalar_one_or_none()
            if not task:
                raise
            task_result = await OperatorTaskService.get_task(db, task.id)

        rec.status = "accepted"
        rec.linked_task_id = task_result["id"]
        rec.updated_at = _utc_now()
        await db.commit()
        await db.refresh(rec, attribute_names=["client", "lead", "deal"])

        logger.info("[SalesAgent] accepted: rec=%s task=%s", rec.id, rec.linked_task_id)
        return {"recommendation": _serialize_rec(rec), "task_id": rec.linked_task_id}

    @staticmethod
    async def dismiss(db: AsyncSession, recommendation_id: UUID) -> dict[str, Any]:
        rec = await SalesAgentService._load_rec(db, recommendation_id)
        if rec.status in ("done", "dismissed"):
            raise HTTPException(status_code=400, detail="Recommendation already closed")
        rec.status = "dismissed"
        rec.updated_at = _utc_now()
        await db.commit()
        await db.refresh(rec, attribute_names=["client", "lead", "deal"])
        return _serialize_rec(rec)

    @staticmethod
    async def mark_done(db: AsyncSession, recommendation_id: UUID) -> dict[str, Any]:
        rec = await SalesAgentService._load_rec(db, recommendation_id)
        if rec.status == "dismissed":
            raise HTTPException(status_code=400, detail="Dismissed recommendation cannot be marked done")
        rec.status = "done"
        rec.updated_at = _utc_now()
        await db.commit()
        await db.refresh(rec, attribute_names=["client", "lead", "deal"])
        return _serialize_rec(rec)

    @staticmethod
    async def _load_rec(db: AsyncSession, rec_id: UUID) -> SalesAgentRecommendation:
        result = await db.execute(
            select(SalesAgentRecommendation)
            .options(
                selectinload(SalesAgentRecommendation.client),
                selectinload(SalesAgentRecommendation.lead),
                selectinload(SalesAgentRecommendation.deal),
            )
            .where(SalesAgentRecommendation.id == rec_id)
        )
        rec = result.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        return rec

    @staticmethod
    async def _collect_candidates(db: AsyncSession) -> list[_Candidate]:
        now = _utc_now()
        candidates: list[_Candidate] = []

        leads_r = await db.execute(
            select(CrmLead)
            .options(selectinload(CrmLead.client))
            .where(CrmLead.status.notin_(("won", "lost")))
        )
        for lead in leads_r.scalars().all():
            lang = lead.language or "ru"

            if lead.next_follow_up_at and _aware(lead.next_follow_up_at) < now:
                candidates.append(_Candidate(
                    recommendation_type="follow_up",
                    client_id=lead.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    partner_id=lead.partner_id,
                    priority="high",
                    title=f"Overdue follow-up: {lead.name}",
                    description=f"Follow-up was due for {lead.name}. Review and contact manually.",
                    suggested_action="Send follow-up message and update next follow-up date",
                    suggested_message=SalesAgentService._template_message(lang, lead.name, "follow_up"),
                    dedupe_key=f"follow_up:lead:{lead.id}",
                    context=f"Lead {lead.name}, overdue follow-up, status={lead.status}",
                ))

            last_touch = await _last_lead_touch(db, lead.id)
            if last_touch and last_touch < now - timedelta(days=_LEAD_STALE_DAYS):
                if not (lead.next_follow_up_at and _aware(lead.next_follow_up_at) < now):
                    candidates.append(_Candidate(
                        recommendation_type="follow_up",
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        partner_id=lead.partner_id,
                        priority="medium",
                        title=f"No activity 7+ days: {lead.name}",
                        description=f"No CRM activity on {lead.name} for {_LEAD_STALE_DAYS}+ days.",
                        suggested_action="Log activity or send check-in message",
                        suggested_message=SalesAgentService._template_message(lang, lead.name, "stale"),
                        dedupe_key=f"stale_lead:lead:{lead.id}",
                        context=f"Lead {lead.name}, stale {_LEAD_STALE_DAYS}d",
                    ))

        deals_r = await db.execute(
            select(CrmDeal)
            .options(selectinload(CrmDeal.lead))
            .where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL)))
        )
        for deal in deals_r.scalars().all():
            lead = deal.lead
            if not lead:
                continue
            lang = lead.language or "ru"
            last_touch = await _last_deal_touch(db, deal.id, lead.id)
            if last_touch and last_touch < now - timedelta(days=_DEAL_STALE_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="risk_warning",
                    client_id=deal.client_id,
                    lead_id=lead.id,
                    deal_id=deal.id,
                    partner_id=lead.partner_id,
                    priority="medium",
                    title=f"Stale deal: {deal.title}",
                    description=f"Deal has no activity for {_DEAL_STALE_DAYS}+ days.",
                    suggested_action="Review deal room and schedule next step",
                    suggested_message=SalesAgentService._template_message(lang, lead.name, "deal_stale"),
                    dedupe_key=f"stale_deal:deal:{deal.id}",
                    context=f"Deal {deal.title}, status={deal.status}",
                ))

            ev = deal.expected_value or lead.estimated_value or Decimal("0")
            if deal.status in ("waiting_payment", "invoice") and ev >= _HIGH_VALUE_THRESHOLD:
                candidates.append(_Candidate(
                    recommendation_type="opportunity",
                    client_id=deal.client_id,
                    lead_id=lead.id,
                    deal_id=deal.id,
                    partner_id=lead.partner_id,
                    priority="high",
                    title=f"High-value deal near close: {deal.title}",
                    description=f"Deal ~{ev} UZS in '{deal.status}'. Push to close manually.",
                    suggested_action="Confirm terms and prepare closing documents",
                    suggested_message=SalesAgentService._template_message(lang, lead.name, "close"),
                    dedupe_key=f"opportunity:deal:{deal.id}",
                    context=f"Deal {deal.title}, value={ev}",
                ))

        props_r = await db.execute(
            select(CrmProposal).options(selectinload(CrmProposal.lead))
        )
        for prop in props_r.scalars().all():
            lead = prop.lead
            if not lead or lead.status in ("won", "lost"):
                continue
            lang = lead.language or "ru"
            updated = _aware(prop.updated_at) or _aware(prop.created_at)
            if prop.status == "sent" and updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="proposal",
                    client_id=prop.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    partner_id=lead.partner_id,
                    priority="high",
                    title=f"Proposal sent, no progress: {lead.name}",
                    description=f"Proposal sent {_PROPOSAL_STALL_DAYS}+ days ago without update.",
                    suggested_action="Follow up on proposal manually",
                    suggested_message=SalesAgentService._template_message(lang, lead.name, "proposal"),
                    dedupe_key=f"proposal_stall:proposal:{prop.id}",
                    context=f"Proposal {prop.title}, sent",
                ))
            elif prop.status == "draft":
                candidates.append(_Candidate(
                    recommendation_type="proposal",
                    client_id=prop.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    partner_id=lead.partner_id,
                    priority="medium",
                    title=f"Proposal draft ready: {lead.name}",
                    description=f"Review draft '{prop.title}' and send manually.",
                    suggested_action="Review proposal in CRM",
                    suggested_message="",
                    dedupe_key=f"proposal_draft:proposal:{prop.id}",
                    context=f"Proposal draft {prop.title}",
                ))

        docs_r = await db.execute(
            select(CrmDocument).options(selectinload(CrmDocument.lead)).where(
                CrmDocument.document_type.in_(("invoice", "contract")),
            )
        )
        for doc in docs_r.scalars().all():
            lead = doc.lead
            if not lead:
                continue
            lang = lead.language or "ru"
            updated = _aware(doc.updated_at) or _aware(doc.created_at)

            if doc.document_type == "invoice" and doc.status == "sent":
                candidates.append(_Candidate(
                    recommendation_type="payment_reminder",
                    client_id=doc.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    partner_id=lead.partner_id,
                    priority="high",
                    title=f"Unpaid invoice: {lead.name}",
                    description="Invoice sent but not paid. Remind client manually.",
                    suggested_action="Send payment reminder — do not mark paid automatically",
                    suggested_message=SalesAgentService._template_message(lang, lead.name, "invoice"),
                    dedupe_key=f"invoice_unpaid:doc:{doc.id}",
                    context=f"Invoice {doc.title}, amount={doc.amount}",
                ))
            elif doc.document_type == "contract" and doc.status == "draft":
                candidates.append(_Candidate(
                    recommendation_type="contract",
                    client_id=doc.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    partner_id=lead.partner_id,
                    priority="medium",
                    title=f"Contract draft ready: {lead.name}",
                    description=f"Review draft '{doc.title}' and send manually.",
                    suggested_action="Review contract in CRM documents",
                    suggested_message="",
                    dedupe_key=f"contract_draft:doc:{doc.id}",
                    context=f"Contract draft {doc.title}",
                ))
            elif (
                doc.document_type == "contract"
                and doc.status == "sent"
                and updated
                and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS)
            ):
                candidates.append(_Candidate(
                    recommendation_type="contract",
                    client_id=doc.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    partner_id=lead.partner_id,
                    priority="high",
                    title=f"Contract sent, no progress: {lead.name}",
                    description=f"Contract sent {_PROPOSAL_STALL_DAYS}+ days ago without update.",
                    suggested_action="Follow up on contract signature manually",
                    suggested_message=SalesAgentService._template_message(lang, lead.name, "deal_stale"),
                    dedupe_key=f"contract_stall:doc:{doc.id}",
                    context=f"Contract {doc.title}, sent",
                ))

        partners_r = await db.execute(select(Partner).where(Partner.status == "active"))
        for partner in partners_r.scalars().all():
            pl_r = await db.execute(
                select(CrmLead).where(
                    CrmLead.partner_id == partner.id,
                    CrmLead.status.notin_(("won", "lost")),
                )
            )
            partner_leads = list(pl_r.scalars().all())
            stale_names: list[str] = []
            client_id: UUID | None = None
            for pl in partner_leads:
                if client_id is None:
                    client_id = pl.client_id
                last = await _last_lead_touch(db, pl.id)
                ref = last or _aware(pl.created_at)
                if ref and ref < now - timedelta(days=_PARTNER_STALE_DAYS):
                    stale_names.append(pl.name)
            if stale_names and client_id:
                candidates.append(_Candidate(
                    recommendation_type="partner_follow_up",
                    client_id=client_id,
                    lead_id=None,
                    deal_id=None,
                    partner_id=partner.id,
                    priority="medium",
                    title=f"Partner inactive leads: {partner.name}",
                    description=f"Inactive referred leads: {', '.join(stale_names[:5])}.",
                    suggested_action="Re-engage partner or referred leads manually",
                    suggested_message="",
                    dedupe_key=f"partner_stale:partner:{partner.id}",
                    context=f"Partner {partner.name}, stale={stale_names}",
                ))

        return candidates

    @staticmethod
    def _template_message(lang: str, name: str, kind: str) -> str:
        templates: dict[str, dict[str, str]] = {
            "ru": {
                "follow_up": f"Здравствуйте, {name}! Актуален ли для вас наш прошлый разговор?",
                "stale": f"Добрый день, {name}! Нужна ли помощь по SMM?",
                "proposal": f"Здравствуйте, {name}! Удалось ознакомиться с предложением?",
                "invoice": f"Добрый день, {name}! Напоминаем об оплате счёта.",
                "deal_stale": f"Здравствуйте, {name}! Обсудим следующие шаги?",
                "close": f"Здравствуйте, {name}! Согласуем финальные детали сделки?",
            },
            "uz": {
                "follow_up": f"Assalomu alaykum, {name}! Suhbatimiz dolzarbmi?",
                "stale": f"Salom, {name}! SMM yordam kerakmi?",
                "proposal": f"Assalomu alaykum, {name}! Taklifni ko'rdingizmi?",
                "invoice": f"Salom, {name}! To'lov eslatmasi.",
                "deal_stale": f"Salom, {name}! Keyingi qadamlarni muhokama qilaylik.",
                "close": f"Assalomu alaykum, {name}! Shartlarni kelishib olaylik.",
            },
            "en": {
                "follow_up": f"Hi {name}, is our previous conversation still relevant?",
                "stale": f"Hi {name}, do you need SMM support?",
                "proposal": f"Hi {name}, did you review our proposal?",
                "invoice": f"Hi {name}, friendly invoice payment reminder.",
                "deal_stale": f"Hi {name}, ready to discuss next steps?",
                "close": f"Hi {name}, let's align on final deal details.",
            },
        }
        L = templates.get(lang, templates["ru"])
        return L.get(kind, L["follow_up"])

    @staticmethod
    async def _enrich_candidate(
        db: AsyncSession,
        cand: _Candidate,
        *,
        allow_ai: bool = True,
    ) -> dict[str, Any]:
        base = {
            "title": cand.title,
            "description": cand.description,
            "suggested_action": cand.suggested_action,
            "suggested_message": cand.suggested_message,
            "priority": cand.priority,
        }
        if not allow_ai:
            return base
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                return base
            _validate_api_key()
            kb = await ClientKnowledgeBaseService.build_prompt_block(
                db, cand.client_id, max_chars=1200, context="sales_agent",
            )
            openai = get_openai()
            user = f"TYPE: {cand.recommendation_type}\nCONTEXT:\n{cand.context}\n{kb or ''}"
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _AI_SYSTEM},
                    {"role": "user", "content": user[:8000]},
                ],
                temperature=0.35,
                max_tokens=600,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            priority = str(parsed.get("priority") or cand.priority).lower()
            if priority not in PRIORITIES:
                priority = cand.priority
            return {
                "title": str(parsed.get("title") or cand.title)[:255],
                "description": str(parsed.get("description") or cand.description)[:2000],
                "suggested_action": str(parsed.get("suggested_action") or cand.suggested_action)[:500],
                "suggested_message": str(parsed.get("suggested_message") or cand.suggested_message)[:2000],
                "priority": priority,
            }
        except Exception as exc:
            logger.warning("[SalesAgent] AI enrich fallback: %s", exc)
            return base
