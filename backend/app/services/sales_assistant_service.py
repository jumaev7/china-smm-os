"""AI Sales Assistant v1 — heuristic cross-channel sales recommendations (manual scan only)."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.buyer_outreach import BuyerOutreachMessage
from app.models.communication import CommunicationMessage, CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.operator_task import OperatorTask
from app.models.product import Product
from app.models.proposal_document import ProposalDocument
from app.models.sales_assistant_recommendation import SalesAssistantRecommendation
from app.models.sales_crm import SalesDeal, SalesLead, SalesProposal
from app.models.buyer_crm import Buyer
from app.models.sales_playbook import SalesPlaybook
from app.models.whatsapp import WhatsAppMessage, WhatsAppThread
from app.schemas.operator_task import OperatorTaskCreate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.client_knowledge_base_service import ClientKnowledgeBaseService
from app.services.lead_classification_service import HOT_CLASSIFICATIONS, LeadClassificationService
from app.services.lead_intelligence_service import HOT_LEVELS
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.operator_task_service import OperatorTaskService
from app.services.sales_playbook_service import _score_playbook

logger = logging.getLogger(__name__)

MARKER = "[Sales Assistant]"

OPEN_STATUSES = frozenset({"open"})
TASK_PRIORITIES = frozenset({"high", "medium", "low"})
_ACTIVE_DEAL = frozenset({"new", "proposal", "contract", "invoice", "waiting_payment"})
_STALE_CONVERSATION_DAYS = 3
_STALE_LEAD_DAYS = 7
_STALE_DEAL_DAYS = 14
_PROPOSAL_STALL_DAYS = 7
_HOT_SCORE = 66
_AI_ENRICH_MAX = 3

_AI_SYSTEM = """\
You enrich a sales assistant recommendation for an operator (manual actions only).
Return ONLY JSON:
{
  "title": "short imperative title",
  "summary": "2-3 sentences explaining why now",
  "recommended_action": "single imperative next step",
  "reason": "brief reason for the recommendation",
  "priority": "urgent|high|medium|low"
}

Rules:
- NEVER imply auto-send, auto status change, or auto proposal creation
- Be specific to the context provided
"""


@dataclass
class _Candidate:
    recommendation_type: str
    client_id: UUID | None
    lead_id: UUID | None
    deal_id: UUID | None
    conversation_id: str | None
    channel: str | None
    priority: str
    title: str
    summary: str
    recommended_action: str
    reason: str
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


def _task_priority(priority: str) -> str:
    if priority in ("urgent", "high"):
        return "high"
    if priority == "low":
        return "low"
    return "medium"


def _serialize_rec(rec: SalesAssistantRecommendation) -> dict[str, Any]:
    return {
        "id": rec.id,
        "client_id": rec.client_id,
        "client_name": rec.client.company_name if rec.client else None,
        "lead_id": rec.lead_id,
        "lead_name": rec.lead.name if rec.lead else None,
        "deal_id": rec.deal_id,
        "deal_title": rec.deal.title if rec.deal else None,
        "conversation_id": rec.conversation_id,
        "channel": rec.channel,
        "recommendation_type": rec.recommendation_type,
        "priority": rec.priority,
        "title": rec.title,
        "summary": rec.summary,
        "recommended_action": rec.recommended_action,
        "reason": rec.reason,
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


async def _lead_has_proposal(db: AsyncSession, lead_id: UUID) -> bool:
    cr = await db.scalar(
        select(func.count()).select_from(CrmProposal).where(CrmProposal.lead_id == lead_id)
    )
    pr = await db.scalar(
        select(func.count()).select_from(ProposalDocument).where(ProposalDocument.lead_id == lead_id)
    )
    return int(cr or 0) + int(pr or 0) > 0


async def _summary_counts(db: AsyncSession, *, client_id: UUID | None = None) -> dict[str, int]:
    open_count = await db.scalar(
        select(func.count()).select_from(SalesAssistantRecommendation).where(
            SalesAssistantRecommendation.status == "open",
            *([SalesAssistantRecommendation.client_id == client_id] if client_id else []),
        )
    )
    urgent_count = await db.scalar(
        select(func.count()).select_from(SalesAssistantRecommendation).where(
            SalesAssistantRecommendation.status == "open",
            SalesAssistantRecommendation.priority == "urgent",
            *([SalesAssistantRecommendation.client_id == client_id] if client_id else []),
        )
    )
    follow_ups = await db.scalar(
        select(func.count()).select_from(SalesAssistantRecommendation).where(
            SalesAssistantRecommendation.status == "open",
            SalesAssistantRecommendation.recommendation_type.in_(("follow_up_needed", "reply_needed")),
            *([SalesAssistantRecommendation.client_id == client_id] if client_id else []),
        )
    )
    proposals = await db.scalar(
        select(func.count()).select_from(SalesAssistantRecommendation).where(
            SalesAssistantRecommendation.status == "open",
            SalesAssistantRecommendation.recommendation_type == "proposal_needed",
            *([SalesAssistantRecommendation.client_id == client_id] if client_id else []),
        )
    )
    return {
        "open_count": int(open_count or 0),
        "urgent_count": int(urgent_count or 0),
        "follow_ups_needed": int(follow_ups or 0),
        "proposals_needed": int(proposals or 0),
    }


def _format_unified_id(source: str, source_id: UUID) -> str:
    return f"{source}:{source_id}"


class SalesAssistantService:
    @staticmethod
    async def scan(db: AsyncSession, *, use_ai: bool = False) -> dict[str, Any]:
        logger.info("%s scan started: use_ai=%s", MARKER, use_ai)
        candidates = await SalesAssistantService._collect_candidates(db)
        created = 0
        skipped = 0

        for idx, cand in enumerate(candidates):
            exists = await db.execute(
                select(SalesAssistantRecommendation.id).where(
                    SalesAssistantRecommendation.dedupe_key == cand.dedupe_key,
                    SalesAssistantRecommendation.status.in_(tuple(OPEN_STATUSES)),
                )
            )
            if exists.scalar_one_or_none():
                skipped += 1
                continue

            enriched = await SalesAssistantService._enrich_candidate(
                db, cand, allow_ai=use_ai and idx < _AI_ENRICH_MAX,
            )
            rec = SalesAssistantRecommendation(
                client_id=cand.client_id,
                lead_id=cand.lead_id,
                deal_id=cand.deal_id,
                conversation_id=cand.conversation_id,
                channel=cand.channel,
                recommendation_type=cand.recommendation_type,
                title=enriched["title"][:255],
                summary=enriched["summary"],
                recommended_action=enriched["recommended_action"],
                reason=enriched["reason"],
                priority=enriched["priority"],
                status="open",
                dedupe_key=cand.dedupe_key,
            )
            db.add(rec)
            await db.flush()
            created += 1
            logger.info(
                "%s recommendation created: id=%s type=%s priority=%s",
                MARKER, rec.id, rec.recommendation_type, rec.priority,
            )

        await db.commit()
        logger.info("%s scan finished: candidates=%s created=%s skipped=%s", MARKER, len(candidates), created, skipped)
        return {"scanned": len(candidates), "created": created, "skipped_duplicates": skipped}

    @staticmethod
    async def list_recommendations(
        db: AsyncSession,
        *,
        status: str | None = None,
        priority: str | None = None,
        client_id: UUID | None = None,
        lead_id: UUID | None = None,
        deal_id: UUID | None = None,
        conversation_id: str | None = None,
        recommendation_type: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        priority_rank = case(
            (SalesAssistantRecommendation.priority == "urgent", 1),
            (SalesAssistantRecommendation.priority == "high", 2),
            (SalesAssistantRecommendation.priority == "medium", 3),
            else_=4,
        )
        query = (
            select(SalesAssistantRecommendation)
            .options(
                selectinload(SalesAssistantRecommendation.client),
                selectinload(SalesAssistantRecommendation.lead),
                selectinload(SalesAssistantRecommendation.deal),
            )
            .order_by(priority_rank, SalesAssistantRecommendation.created_at.desc())
        )
        count_q = select(func.count()).select_from(SalesAssistantRecommendation)

        filters = []
        if status:
            filters.append(SalesAssistantRecommendation.status == status)
        else:
            filters.append(SalesAssistantRecommendation.status != "dismissed")
        if priority:
            filters.append(SalesAssistantRecommendation.priority == priority)
        if client_id:
            filters.append(SalesAssistantRecommendation.client_id == client_id)
        if lead_id:
            filters.append(SalesAssistantRecommendation.lead_id == lead_id)
        if deal_id:
            filters.append(SalesAssistantRecommendation.deal_id == deal_id)
        if conversation_id:
            filters.append(SalesAssistantRecommendation.conversation_id == conversation_id)
        if recommendation_type:
            filters.append(SalesAssistantRecommendation.recommendation_type == recommendation_type)

        for flt in filters:
            query = query.where(flt)
            count_q = count_q.where(flt)

        total = (await db.execute(count_q)).scalar_one()
        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize_rec(r) for r in result.scalars().unique().all()]
        summary = await _summary_counts(db, client_id=client_id)
        return {"items": items, "total": total, "summary": summary}

    @staticmethod
    async def top_open(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        data = await SalesAssistantService.list_recommendations(
            db, status="open", client_id=client_id, limit=limit,
        )
        return data["items"]

    @staticmethod
    async def dismiss(db: AsyncSession, recommendation_id: UUID) -> dict[str, Any]:
        rec = await SalesAssistantService._load_rec(db, recommendation_id)
        if rec.status != "open":
            raise HTTPException(status_code=400, detail="Recommendation already closed")
        rec.status = "dismissed"
        rec.updated_at = _utc_now()
        await db.commit()
        await db.refresh(rec, attribute_names=["client", "lead", "deal"])
        logger.info("%s dismissed: id=%s", MARKER, rec.id)
        return _serialize_rec(rec)

    @staticmethod
    async def complete(db: AsyncSession, recommendation_id: UUID) -> dict[str, Any]:
        rec = await SalesAssistantService._load_rec(db, recommendation_id)
        if rec.status == "dismissed":
            raise HTTPException(status_code=400, detail="Dismissed recommendation cannot be completed")
        rec.status = "completed"
        rec.updated_at = _utc_now()
        await db.commit()
        await db.refresh(rec, attribute_names=["client", "lead", "deal"])
        logger.info("%s completed: id=%s", MARKER, rec.id)
        return _serialize_rec(rec)

    @staticmethod
    async def create_task(db: AsyncSession, recommendation_id: UUID) -> dict[str, Any]:
        from app.services.operator_task_engine_service import OperatorTaskEngineService

        result = await OperatorTaskEngineService.from_recommendation(db, recommendation_id)
        rec = await SalesAssistantService._load_rec(db, recommendation_id)
        logger.info("%s task created: rec=%s task=%s", MARKER, rec.id, rec.linked_task_id)
        return {
            "recommendation": _serialize_rec(rec),
            "task_id": result["task"]["id"],
        }

    @staticmethod
    async def _load_rec(db: AsyncSession, rec_id: UUID) -> SalesAssistantRecommendation:
        result = await db.execute(
            select(SalesAssistantRecommendation)
            .options(
                selectinload(SalesAssistantRecommendation.client),
                selectinload(SalesAssistantRecommendation.lead),
                selectinload(SalesAssistantRecommendation.deal),
            )
            .where(SalesAssistantRecommendation.id == rec_id)
        )
        rec = result.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        return rec

    @staticmethod
    async def _collect_candidates(db: AsyncSession) -> list[_Candidate]:
        now = _utc_now()
        candidates: list[_Candidate] = []

        await SalesAssistantService._scan_unified_inbox(db, now, candidates)
        await SalesAssistantService._scan_crm_leads(db, now, candidates)
        await SalesAssistantService._scan_tenant_sales_crm(db, now, candidates)
        await SalesAssistantService._scan_proposals(db, now, candidates)
        await SalesAssistantService._scan_outreach(db, now, candidates)
        await SalesAssistantService._scan_deals(db, now, candidates)
        await SalesAssistantService._scan_playbooks(db, candidates)
        return candidates

    @staticmethod
    async def _scan_unified_inbox(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
    ) -> None:
        threads_r = await db.execute(
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .where(CommunicationThread.status.in_(("open", "waiting")))
        )
        for thread in threads_r.scalars().all():
            msgs = list(thread.messages or [])
            conv_id = _format_unified_id("thread", thread.id)
            channel = thread.channel or "manual"
            outbound_times = [m.created_at for m in msgs if m.direction == "outbound"]
            last_out = max(outbound_times) if outbound_times else None
            unanswered = [
                m for m in msgs
                if m.direction == "inbound" and (last_out is None or m.created_at > last_out)
            ]
            if unanswered:
                candidates.append(_Candidate(
                    recommendation_type="reply_needed",
                    client_id=thread.client_id,
                    lead_id=thread.lead_id,
                    deal_id=thread.deal_id,
                    conversation_id=conv_id,
                    channel=channel,
                    priority="urgent" if len(unanswered) > 1 else "high",
                    title=f"Reply needed: {thread.title or 'conversation'}",
                    summary=f"{len(unanswered)} inbound message(s) awaiting operator reply.",
                    recommended_action="Review conversation and send a manual reply",
                    reason="Unanswered inbound messages detected in unified inbox",
                    dedupe_key=f"reply:thread:{thread.id}",
                    context=f"Thread {thread.title}, channel={channel}, unanswered={len(unanswered)}",
                ))

            try:
                intel_item = await CommunicationIntelligenceService._analyze_thread(db, thread)
                intel = intel_item.get("intelligence") or {}
                insights = intel.get("insights") or []
                if "proposal requested" in insights:
                    candidates.append(_Candidate(
                        recommendation_type="proposal_needed",
                        client_id=thread.client_id,
                        lead_id=thread.lead_id,
                        deal_id=thread.deal_id,
                        conversation_id=conv_id,
                        channel=channel,
                        priority="high",
                        title=f"Proposal requested in conversation: {thread.title or 'thread'}",
                        summary="Communication intelligence detected proposal request.",
                        recommended_action=(intel.get("recommended_actions") or ["Prepare proposal manually"])[0],
                        reason="Communication intelligence: proposal requested",
                        dedupe_key=f"comm_proposal:thread:{thread.id}",
                        context=f"Health {intel.get('health_score')}, class={intel.get('classification')}",
                    ))
                elif "hot buyer" in insights:
                    candidates.append(_Candidate(
                        recommendation_type="follow_up_needed",
                        client_id=thread.client_id,
                        lead_id=thread.lead_id,
                        deal_id=thread.deal_id,
                        conversation_id=conv_id,
                        channel=channel,
                        priority=intel.get("urgency") or "high",
                        title=f"Hot buyer conversation: {thread.title or 'thread'}",
                        summary=f"Communication health {intel.get('health_score')}/100.",
                        recommended_action=(intel.get("recommended_actions") or ["Review manually"])[0],
                        reason="Communication intelligence: hot buyer",
                        dedupe_key=f"comm_hot:thread:{thread.id}",
                        context=f"Insights: {', '.join(insights[:3])}",
                    ))
            except Exception as exc:
                logger.debug("[Sales Assistant] comm intel skip thread=%s: %s", thread.id, exc)

            if thread.client_id and not thread.lead_id and not thread.sales_lead_id:
                candidates.append(_Candidate(
                    recommendation_type="lead_link_needed",
                    client_id=thread.client_id,
                    lead_id=None,
                    deal_id=thread.deal_id,
                    conversation_id=conv_id,
                    channel=channel,
                    priority="medium",
                    title=f"Link CRM lead: {thread.title or 'conversation'}",
                    summary="Conversation is not linked to a CRM lead.",
                    recommended_action="Link an existing lead or create a new lead manually",
                    reason="Missing CRM lead link blocks pipeline tracking",
                    dedupe_key=f"lead_link:thread:{thread.id}",
                    context=f"Thread {thread.title}, no lead linked",
                ))

            last_at = _aware(thread.last_message_at or thread.updated_at)
            if last_at and last_at < now - timedelta(days=_STALE_CONVERSATION_DAYS):
                if not unanswered:
                    candidates.append(_Candidate(
                        recommendation_type="follow_up_needed",
                        client_id=thread.client_id,
                        lead_id=thread.lead_id,
                        deal_id=thread.deal_id,
                        conversation_id=conv_id,
                        channel=channel,
                        priority="medium",
                        title=f"Stale conversation: {thread.title or 'conversation'}",
                        summary=f"No activity for {_STALE_CONVERSATION_DAYS}+ days.",
                        recommended_action="Send a manual check-in message",
                        reason="Conversation has gone quiet",
                        dedupe_key=f"stale_conv:thread:{thread.id}",
                        context=f"Thread stale {_STALE_CONVERSATION_DAYS}d",
                    ))

        wa_r = await db.execute(
            select(WhatsAppThread).options(
                selectinload(WhatsAppThread.messages),
                selectinload(WhatsAppThread.contact),
            )
        )
        for wa in wa_r.scalars().all():
            msgs = list(wa.messages or [])
            conv_id = _format_unified_id("whatsapp", wa.id)
            outbound = [m for m in msgs if m.direction == "outgoing" and m.status != "draft"]
            last_out = max((m.created_at for m in outbound), default=None)
            unanswered = [
                m for m in msgs
                if m.direction == "incoming" and (last_out is None or m.created_at > last_out)
            ]
            if unanswered:
                candidates.append(_Candidate(
                    recommendation_type="reply_needed",
                    client_id=wa.contact.crm_client_id if wa.contact else None,
                    lead_id=None,
                    deal_id=None,
                    conversation_id=conv_id,
                    channel="whatsapp",
                    priority="high",
                    title="WhatsApp reply needed",
                    summary=f"{len(unanswered)} WhatsApp message(s) awaiting reply.",
                    recommended_action="Open WhatsApp center and reply manually",
                    reason="Unanswered WhatsApp inbound messages",
                    dedupe_key=f"reply:whatsapp:{wa.id}",
                    context=f"WhatsApp thread {wa.id}, unanswered={len(unanswered)}",
                ))

    @staticmethod
    async def _scan_crm_leads(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
    ) -> None:
        leads_r = await db.execute(
            select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
        )
        for lead in leads_r.scalars().all():
            try:
                cls_item = await LeadClassificationService.classify_lead(db, lead)
                cls = cls_item["classification"]
                cls_score = cls_item["score"]
            except Exception:
                cls = None
                cls_score = lead.lead_score or 0

            is_hot = (
                cls in HOT_CLASSIFICATIONS
                or (lead.qualification_level or "") in HOT_LEVELS
                or (lead.lead_score or 0) >= _HOT_SCORE
            )

            if lead.next_follow_up_at and _aware(lead.next_follow_up_at) < now:
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=lead.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    conversation_id=None,
                    channel=None,
                    priority="urgent",
                    title=f"Overdue follow-up: {lead.name}",
                    summary=f"Follow-up was due for {lead.name}.",
                    recommended_action="Contact lead manually and update next follow-up date",
                    reason="CRM follow-up date is overdue",
                    dedupe_key=f"follow_up:lead:{lead.id}",
                    context=f"Lead {lead.name}, overdue follow-up",
                ))

            if not lead.next_follow_up_at and lead.status in ("new", "contacted", "qualified"):
                last_touch = await _last_lead_touch(db, lead.id)
                ref = last_touch or _aware(lead.created_at)
                if ref and ref < now - timedelta(days=_STALE_LEAD_DAYS):
                    candidates.append(_Candidate(
                        recommendation_type="missing_task",
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        conversation_id=None,
                        channel=None,
                        priority="medium",
                        title=f"No follow-up scheduled: {lead.name}",
                        summary=f"Lead has no next follow-up and no recent activity.",
                        recommended_action="Schedule follow-up or create operator task",
                        reason="Lead lacks follow-up plan",
                        dedupe_key=f"missing_task:lead:{lead.id}",
                        context=f"Lead {lead.name}, no follow-up set",
                    ))

            if is_hot and lead.status not in ("proposal_sent", "negotiation", "won"):
                has_proposal = await _lead_has_proposal(db, lead.id)
                if not has_proposal:
                    candidates.append(_Candidate(
                        recommendation_type="proposal_needed",
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        conversation_id=None,
                        channel=None,
                        priority="high",
                        title=f"Hot lead needs proposal: {lead.name}",
                        summary=(
                            f"Classification {cls or lead.qualification_level or 'hot'}, "
                            f"score {cls_score or lead.lead_score or '—'} — no proposal yet."
                        ),
                        recommended_action="Review lead and create proposal manually",
                        reason="Hot or qualified lead without proposal",
                        dedupe_key=f"proposal_needed:lead:{lead.id}",
                        context=f"Lead {lead.name}, hot, no proposal",
                    ))
                    candidates.append(_Candidate(
                        recommendation_type="hot_lead",
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        conversation_id=None,
                        channel=None,
                        priority="urgent" if (lead.lead_score or 0) >= 80 else "high",
                        title=f"Hot lead: {lead.name}",
                        summary=(
                            f"High-intent lead ({cls or 'hot'}, score {cls_score or lead.lead_score or '—'}) "
                            "requires operator attention."
                        ),
                        recommended_action="Review lead intelligence and plan next step",
                        reason=f"Lead classification indicates high intent ({cls or lead.qualification_level})",
                        dedupe_key=f"hot_lead:lead:{lead.id}",
                        context=(
                            f"Lead {lead.name}, classification={cls}, "
                            f"score={cls_score or lead.lead_score}"
                        ),
                    ))

            last_touch = await _last_lead_touch(db, lead.id)
            if last_touch and last_touch < now - timedelta(days=_STALE_LEAD_DAYS):
                if not (lead.next_follow_up_at and _aware(lead.next_follow_up_at) < now):
                    candidates.append(_Candidate(
                        recommendation_type="follow_up_needed",
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        conversation_id=None,
                        channel=None,
                        priority="medium",
                        title=f"No activity: {lead.name}",
                        summary=f"No CRM activity for {_STALE_LEAD_DAYS}+ days.",
                        recommended_action="Log activity or send check-in manually",
                        reason="Lead has gone stale",
                        dedupe_key=f"stale_lead:lead:{lead.id}",
                        context=f"Lead {lead.name}, stale",
                    ))

    @staticmethod
    async def _scan_proposals(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
    ) -> None:
        props_r = await db.execute(select(CrmProposal).options(selectinload(CrmProposal.lead)))
        for prop in props_r.scalars().all():
            lead = prop.lead
            if not lead or lead.status in ("won", "lost"):
                continue
            updated = _aware(prop.updated_at) or _aware(prop.created_at)
            if prop.status == "sent" and updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=prop.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    conversation_id=None,
                    channel=None,
                    priority="high",
                    title=f"Proposal follow-up: {lead.name}",
                    summary=f"Proposal sent {_PROPOSAL_STALL_DAYS}+ days ago without update.",
                    recommended_action="Follow up on proposal manually",
                    reason="Sent proposal with no recent progress",
                    dedupe_key=f"proposal_follow_up:proposal:{prop.id}",
                    context=f"Proposal {prop.title}, sent",
                ))

        docs_r = await db.execute(
            select(ProposalDocument).options(selectinload(ProposalDocument.lead))
        )
        for doc in docs_r.scalars().all():
            lead = doc.lead
            if not lead or lead.status in ("won", "lost"):
                continue
            updated = _aware(doc.updated_at) or _aware(doc.created_at)
            if doc.status == "sent" and updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=doc.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    conversation_id=None,
                    channel=None,
                    priority="high",
                    title=f"Proposal document follow-up: {lead.name}",
                    summary=f"Proposal document sent {_PROPOSAL_STALL_DAYS}+ days ago.",
                    recommended_action="Follow up on proposal document manually",
                    reason="Sent proposal document stalled",
                    dedupe_key=f"proposal_doc_follow_up:doc:{doc.id}",
                    context=f"Proposal doc {doc.title}",
                ))

    @staticmethod
    async def _scan_outreach(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
    ) -> None:
        outreach_r = await db.execute(select(BuyerOutreachMessage))
        for row in outreach_r.scalars().all():
            conv_id = _format_unified_id("outreach", row.id)
            updated = _aware(row.updated_at) or _aware(row.created_at)
            if row.status in ("draft", "approved") and updated and updated < now - timedelta(days=3):
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=row.client_id,
                    lead_id=row.lead_id,
                    deal_id=None,
                    conversation_id=conv_id,
                    channel="outreach",
                    priority="medium",
                    title="Outreach draft pending send",
                    summary=f"Outreach message in '{row.status}' for 3+ days.",
                    recommended_action="Review outreach draft and send manually",
                    reason="Outreach not sent yet",
                    dedupe_key=f"outreach_pending:outreach:{row.id}",
                    context=f"Outreach status={row.status}",
                ))
            if row.status == "sent" and updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=row.client_id,
                    lead_id=row.lead_id,
                    deal_id=None,
                    conversation_id=conv_id,
                    channel="outreach",
                    priority="medium",
                    title="Outreach follow-up needed",
                    summary=f"Outreach sent {_PROPOSAL_STALL_DAYS}+ days ago.",
                    recommended_action="Follow up on outreach manually",
                    reason="Sent outreach without follow-up",
                    dedupe_key=f"outreach_follow_up:outreach:{row.id}",
                    context=f"Outreach sent, lead={row.lead_id}",
                ))

    @staticmethod
    async def _scan_tenant_sales_crm(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
    ) -> None:
        """Scan tenant-scoped Sales CRM (leads, deals, proposals, buyers)."""
        active_lead_statuses = frozenset({"new", "contacted", "qualified"})
        open_deal_stages = frozenset({
            "lead", "qualified", "contacted", "meeting_scheduled",
            "proposal_sent", "negotiation", "contract_pending",
            "client_active", "publishing_active", "expansion_upsell",
        })

        leads_r = await db.execute(
            select(SalesLead).where(SalesLead.status.in_(tuple(active_lead_statuses)))
        )
        for lead in leads_r.scalars().all():
            updated = _aware(lead.updated_at)
            if updated and updated < now - timedelta(days=_STALE_LEAD_DAYS):
                label = lead.company or lead.name
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=None,
                    lead_id=None,
                    deal_id=None,
                    conversation_id=f"sales_lead:{lead.id}",
                    channel="sales_crm",
                    priority="medium",
                    title=f"Stale sales lead: {label}",
                    summary=f"Lead inactive for {_STALE_LEAD_DAYS}+ days.",
                    recommended_action="Contact lead or update status in Sales CRM",
                    reason="Tenant sales lead needs follow-up",
                    dedupe_key=f"tenant_lead_stale:{lead.id}",
                    context=f"SalesLead {label}, status={lead.status}",
                ))

        deals_r = await db.execute(
            select(SalesDeal).where(SalesDeal.stage.in_(tuple(open_deal_stages)))
        )
        for deal in deals_r.scalars().all():
            updated = _aware(deal.updated_at)
            if updated and updated < now - timedelta(days=_STALE_DEAL_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=None,
                    lead_id=None,
                    deal_id=None,
                    conversation_id=f"sales_deal:{deal.id}",
                    channel="sales_crm",
                    priority="high" if deal.stage == "proposal_sent" else "medium",
                    title=f"Stale deal: {deal.title}",
                    summary=f"Deal in '{deal.stage}' unchanged for {_STALE_DEAL_DAYS}+ days.",
                    recommended_action="Review deal pipeline and send follow-up",
                    reason="Tenant sales deal stalled",
                    dedupe_key=f"tenant_deal_stale:{deal.id}",
                    context=f"SalesDeal {deal.title}, value={deal.value}",
                ))

        proposals_r = await db.execute(
            select(SalesProposal).where(SalesProposal.status.in_(("sent", "viewed")))
        )
        for prop in proposals_r.scalars().all():
            updated = _aware(prop.updated_at)
            if updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=None,
                    lead_id=None,
                    deal_id=None,
                    conversation_id=f"sales_proposal:{prop.id}",
                    channel="sales_crm",
                    priority="high",
                    title=f"Proposal follow-up: {prop.title}",
                    summary=f"Proposal '{prop.status}' for {_PROPOSAL_STALL_DAYS}+ days.",
                    recommended_action="Follow up on commercial proposal manually",
                    reason="Tenant sales proposal awaiting response",
                    dedupe_key=f"tenant_proposal_stale:{prop.id}",
                    context=f"SalesProposal {prop.proposal_number}",
                ))

        buyers_r = await db.execute(
            select(Buyer).where(Buyer.status.in_(("interested", "negotiating")))
        )
        for buyer in buyers_r.scalars().all():
            updated = _aware(buyer.updated_at)
            if updated and updated < now - timedelta(days=_STALE_LEAD_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="follow_up_needed",
                    client_id=None,
                    lead_id=None,
                    deal_id=None,
                    conversation_id=f"buyer:{buyer.id}",
                    channel="buyer_crm",
                    priority="medium",
                    title=f"Buyer follow-up: {buyer.company_name}",
                    summary=f"Active buyer profile inactive for {_STALE_LEAD_DAYS}+ days.",
                    recommended_action="Reach out to buyer or log activity",
                    reason="Buyer CRM profile needs engagement",
                    dedupe_key=f"tenant_buyer_stale:{buyer.id}",
                    context=f"Buyer {buyer.company_name}, status={buyer.status}",
                ))

    @staticmethod
    async def _scan_deals(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
    ) -> None:
        deals_r = await db.execute(
            select(CrmDeal).options(selectinload(CrmDeal.lead)).where(
                CrmDeal.status.in_(tuple(_ACTIVE_DEAL))
            )
        )
        for deal in deals_r.scalars().all():
            lead = deal.lead
            if not lead:
                continue
            updated = _aware(deal.updated_at) or _aware(deal.created_at)
            if updated and updated < now - timedelta(days=_STALE_DEAL_DAYS):
                candidates.append(_Candidate(
                    recommendation_type="stalled_deal",
                    client_id=deal.client_id,
                    lead_id=lead.id,
                    deal_id=deal.id,
                    conversation_id=None,
                    channel=None,
                    priority="high",
                    title=f"Stalled deal: {deal.title}",
                    summary=f"Deal inactive for {_STALE_DEAL_DAYS}+ days.",
                    recommended_action="Review deal room and schedule next step manually",
                    reason="Active deal with no recent updates",
                    dedupe_key=f"stalled_deal:deal:{deal.id}",
                    context=f"Deal {deal.title}, status={deal.status}",
                ))
            if deal.status in ("proposal", "negotiation") and updated and updated < now - timedelta(days=7):
                candidates.append(_Candidate(
                    recommendation_type="deal_update_needed",
                    client_id=deal.client_id,
                    lead_id=lead.id,
                    deal_id=deal.id,
                    conversation_id=None,
                    channel=None,
                    priority="medium",
                    title=f"Deal update needed: {deal.title}",
                    summary=f"Deal in '{deal.status}' needs operator review.",
                    recommended_action="Update deal status or log next step manually",
                    reason="Deal progress may be outdated",
                    dedupe_key=f"deal_update:deal:{deal.id}",
                    context=f"Deal {deal.title}, status={deal.status}",
                ))

    @staticmethod
    async def _scan_playbooks(
        db: AsyncSession,
        candidates: list[_Candidate],
    ) -> None:
        leads_r = await db.execute(
            select(CrmLead).where(
                CrmLead.status.notin_(("won", "lost")),
                CrmLead.status.in_(("new", "contacted", "qualified")),
            )
        )
        playbooks_r = await db.execute(
            select(SalesPlaybook).where(SalesPlaybook.status == "active")
        )
        playbooks = list(playbooks_r.scalars().all())
        if not playbooks:
            return

        products_r = await db.execute(select(Product))
        products_by_client: dict[UUID, list[Product]] = {}
        for p in products_r.scalars().all():
            products_by_client.setdefault(p.client_id, []).append(p)

        for lead in leads_r.scalars().all():
            product_category = None
            client_products = products_by_client.get(lead.client_id, [])
            if client_products and lead.interest:
                for p in client_products:
                    if p.category and p.category.lower() in (lead.interest or "").lower():
                        product_category = p.category
                        break
            if not product_category and client_products:
                product_category = client_products[0].category

            best_score = 0
            best_playbook: SalesPlaybook | None = None
            best_reasons: list[str] = []
            for pb in playbooks:
                score, reasons = _score_playbook(
                    pb,
                    client_id=lead.client_id,
                    product_category=product_category,
                    buyer_type=None,
                    country=None,
                    language=lead.language,
                    channel=None,
                )
                if score > best_score:
                    best_score = score
                    best_playbook = pb
                    best_reasons = reasons

            if best_playbook and best_score >= 4:
                candidates.append(_Candidate(
                    recommendation_type="playbook_recommended",
                    client_id=lead.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    conversation_id=None,
                    channel=None,
                    priority="medium",
                    title=f"Playbook: {best_playbook.name}",
                    summary=f"Playbook matches lead {lead.name}: {', '.join(best_reasons[:3])}.",
                    recommended_action=f"Review playbook '{best_playbook.name}' and apply steps manually",
                    reason="Lead/product/category matches active sales playbook",
                    dedupe_key=f"playbook:lead:{lead.id}:playbook:{best_playbook.id}",
                    context=f"Lead {lead.name}, playbook {best_playbook.name}",
                ))

    @staticmethod
    async def _enrich_candidate(
        db: AsyncSession,
        cand: _Candidate,
        *,
        allow_ai: bool = False,
    ) -> dict[str, Any]:
        base = {
            "title": cand.title,
            "summary": cand.summary,
            "recommended_action": cand.recommended_action,
            "reason": cand.reason,
            "priority": cand.priority,
        }
        if not allow_ai:
            return base
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                return base
            _validate_api_key()
            kb = ""
            if cand.client_id:
                kb = await ClientKnowledgeBaseService.build_prompt_block(
                    db, cand.client_id, max_chars=800, context="sales_assistant",
                )
            openai = get_openai()
            user = f"TYPE: {cand.recommendation_type}\nCONTEXT:\n{cand.context}\n{kb or ''}"
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _AI_SYSTEM},
                    {"role": "user", "content": user[:6000]},
                ],
                temperature=0.35,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            priority = str(parsed.get("priority") or cand.priority).lower()
            if priority not in ("urgent", "high", "medium", "low"):
                priority = cand.priority
            return {
                "title": str(parsed.get("title") or cand.title)[:255],
                "summary": str(parsed.get("summary") or cand.summary)[:2000],
                "recommended_action": str(parsed.get("recommended_action") or cand.recommended_action)[:500],
                "reason": str(parsed.get("reason") or cand.reason)[:1000],
                "priority": priority,
            }
        except Exception as exc:
            logger.warning("%s AI enrich fallback: %s", MARKER, exc)
            return base
