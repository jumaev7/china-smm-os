"""AI Operator Task Engine v1 — convert sales signals into structured operator tasks (manual only)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.operator_task import OperatorTask
from app.models.proposal_document import ProposalDocument
from app.models.sales_assistant_recommendation import SalesAssistantRecommendation
from app.services.operator_task_service import TERMINAL_STATUSES
from app.services.sales_assistant_service import SalesAssistantService, _Candidate
from app.services.unified_inbox_service import UnifiedInboxService, parse_unified_id

logger = logging.getLogger(__name__)

MARKER = "[Operator Task Engine]"

ACTION_TYPES = frozenset({
    "reply_to_message",
    "follow_up",
    "create_proposal",
    "review_proposal",
    "link_lead",
    "update_deal",
    "check_payment",
    "review_hot_lead",
    "manual_sales_action",
})

OPEN_STATUSES = frozenset({"todo", "in_progress", "waiting_client"})

_REC_TYPE_TO_ACTION: dict[str, str] = {
    "reply_needed": "reply_to_message",
    "follow_up_needed": "follow_up",
    "proposal_needed": "create_proposal",
    "lead_link_needed": "link_lead",
    "deal_update_needed": "update_deal",
    "hot_lead": "review_hot_lead",
    "stalled_deal": "update_deal",
    "missing_task": "follow_up",
    "playbook_recommended": "manual_sales_action",
}

_FOLLOW_UP_DAYS = 3
_STALE_PROPOSAL_DAYS = 7


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _engine_priority(priority: str) -> str:
    p = (priority or "medium").lower()
    if p in ("urgent", "high"):
        return "high"
    if p == "low":
        return "low"
    return "medium"


def _is_urgent(priority: str, due_at: datetime | None, now: datetime) -> bool:
    if priority in ("urgent", "high"):
        return True
    due = _aware(due_at)
    return due is not None and due < now


def _is_overdue(due_at: datetime | None, now: datetime) -> bool:
    due = _aware(due_at)
    return due is not None and due < now


def _is_due_today(due_at: datetime | None, now: datetime) -> bool:
    due = _aware(due_at)
    if not due:
        return False
    return due.date() == now.date()


def _suggest_due_at(action_type: str, priority: str) -> datetime:
    now = _utc_now()
    if action_type == "reply_to_message":
        return now + timedelta(hours=4)
    if action_type in ("review_hot_lead", "check_payment"):
        return now + timedelta(days=1)
    if action_type in ("create_proposal", "review_proposal"):
        return now + timedelta(days=2)
    if priority in ("urgent", "high"):
        return now + timedelta(days=1)
    return now + timedelta(days=_FOLLOW_UP_DAYS)


def _action_for_rec_type(rec_type: str) -> str:
    return _REC_TYPE_TO_ACTION.get(rec_type, "manual_sales_action")


def _serialize_task(task: OperatorTask, classification: dict[str, Any] | None = None) -> dict[str, Any]:
    company_name = task.client.company_name if task.client else None
    lead_name = task.lead.name if getattr(task, "lead", None) else None
    deal_title = task.deal.title if getattr(task, "deal", None) else None
    proposal_title = task.proposal.title if getattr(task, "proposal", None) else None
    recommended_action = None
    if task.description and "\n\nRecommended:" in task.description:
        recommended_action = task.description.split("\n\nRecommended:", 1)[-1].strip()
    elif task.description:
        recommended_action = task.description[:500]
    return {
        "id": task.id,
        "client_id": task.client_id,
        "company_name": company_name,
        "source_type": task.source_type,
        "source_id": task.source_id,
        "title": task.title,
        "description": task.description,
        "priority": task.priority,
        "status": task.status,
        "action_type": task.action_type,
        "channel": task.channel,
        "due_at": task.due_at,
        "completed_at": task.completed_at,
        "dismissed_at": task.dismissed_at,
        "recommendation_id": task.recommendation_id,
        "conversation_id": task.conversation_id,
        "lead_id": task.lead_id,
        "lead_name": lead_name,
        "lead_classification": classification.get("classification") if classification else None,
        "lead_classification_score": classification.get("score") if classification else None,
        "lead_classification_urgency": classification.get("urgency_level") if classification else None,
        "deal_id": task.deal_id,
        "deal_title": deal_title,
        "proposal_id": task.proposal_id,
        "proposal_title": proposal_title,
        "recommended_action": recommended_action,
        "created_at": task.created_at,
        "updated_at": task.updated_at,
    }


class OperatorTaskEngineService:
    @staticmethod
    async def list_tasks(
        db: AsyncSession,
        *,
        status: str | None = None,
        client_id: UUID | None = None,
        priority: str | None = None,
        action_type: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        now = _utc_now()

        base = select(OperatorTask).options(
            selectinload(OperatorTask.client),
            selectinload(OperatorTask.lead),
            selectinload(OperatorTask.deal),
            selectinload(OperatorTask.proposal),
        )
        if client_id:
            base = base.where(OperatorTask.client_id == client_id)
        if status:
            base = base.where(OperatorTask.status == status)
        elif not status:
            base = base.where(
                OperatorTask.status.in_(tuple(OPEN_STATUSES)),
                OperatorTask.dismissed_at.is_(None),
            )
        if priority:
            base = base.where(OperatorTask.priority == _engine_priority(priority))
        if action_type:
            base = base.where(OperatorTask.action_type == action_type)

        count_q = select(func.count()).select_from(OperatorTask)
        if client_id:
            count_q = count_q.where(OperatorTask.client_id == client_id)
        if status:
            count_q = count_q.where(OperatorTask.status == status)
        else:
            count_q = count_q.where(
                OperatorTask.status.in_(tuple(OPEN_STATUSES)),
                OperatorTask.dismissed_at.is_(None),
            )
        if priority:
            count_q = count_q.where(OperatorTask.priority == _engine_priority(priority))
        if action_type:
            count_q = count_q.where(OperatorTask.action_type == action_type)
        total = int(await db.scalar(count_q) or 0)

        order = base.order_by(
            OperatorTask.priority.desc(),
            OperatorTask.due_at.asc().nulls_last(),
            OperatorTask.updated_at.desc(),
        )
        result = await db.execute(order.offset(skip).limit(limit))
        tasks = list(result.scalars().all())
        lead_ids = [t.lead_id for t in tasks if t.lead_id]
        from app.services.lead_classification_service import LeadClassificationService
        cls_map = await LeadClassificationService.classify_leads_map(db, lead_ids)
        items = [
            _serialize_task(t, cls_map.get(str(t.lead_id)) if t.lead_id else None)
            for t in tasks
        ]

        open_q = select(OperatorTask).where(
            OperatorTask.status.in_(tuple(OPEN_STATUSES)),
            OperatorTask.dismissed_at.is_(None),
        )
        if client_id:
            open_q = open_q.where(OperatorTask.client_id == client_id)
        open_rows = (await db.execute(open_q)).scalars().all()

        urgent_count = sum(1 for t in open_rows if _is_urgent(t.priority, t.due_at, now))
        overdue_count = sum(
            1 for t in open_rows
            if _is_overdue(t.due_at, now) and t.status in OPEN_STATUSES
        )
        due_today_count = sum(1 for t in open_rows if _is_due_today(t.due_at, now))

        return {
            "items": items,
            "total": total,
            "summary": {
                "open_count": len(open_rows),
                "urgent_count": urgent_count,
                "overdue_count": overdue_count,
                "due_today_count": due_today_count,
            },
        }

    @staticmethod
    async def generate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        logger.info("%s generate started client_id=%s", MARKER, client_id)
        scanned = 0
        created = 0
        skipped = 0

        candidates = await SalesAssistantService._collect_candidates(db)
        for cand in candidates:
            if client_id and cand.client_id != client_id:
                continue
            scanned += 1
            ok = await OperatorTaskEngineService._create_from_candidate(db, cand)
            if ok:
                created += 1
            else:
                skipped += 1

        recs_r = await db.execute(
            select(SalesAssistantRecommendation)
            .options(
                selectinload(SalesAssistantRecommendation.client),
                selectinload(SalesAssistantRecommendation.lead),
                selectinload(SalesAssistantRecommendation.deal),
            )
            .where(
                SalesAssistantRecommendation.status == "open",
                SalesAssistantRecommendation.linked_task_id.is_(None),
                *(
                    [SalesAssistantRecommendation.client_id == client_id]
                    if client_id
                    else []
                ),
            )
        )
        for rec in recs_r.scalars().all():
            scanned += 1
            ok = await OperatorTaskEngineService._create_from_recommendation_row(db, rec, mark_completed=False)
            if ok:
                created += 1
            else:
                skipped += 1

        now = _utc_now()
        proposals_r = await db.execute(
            select(ProposalDocument).where(
                ProposalDocument.status == "sent",
                ProposalDocument.sent_at.isnot(None),
                *([ProposalDocument.client_id == client_id] if client_id else []),
            )
        )
        for doc in proposals_r.scalars().all():
            sent = _aware(doc.sent_at)
            if not sent or sent > now - timedelta(days=_STALE_PROPOSAL_DAYS):
                continue
            scanned += 1
            dup = await OperatorTaskEngineService._find_duplicate(
                db,
                action_type="follow_up",
                proposal_id=doc.id,
                source_type="proposal",
                source_id=doc.id,
            )
            if dup:
                skipped += 1
                continue
            await OperatorTaskEngineService._persist_task(
                db,
                client_id=doc.client_id,
                source_type="proposal",
                source_id=doc.id,
                title=f"Follow up sent proposal: {doc.title}"[:255],
                description=f"Proposal sent {_STALE_PROPOSAL_DAYS}+ days ago — manual follow-up suggested.",
                priority="medium",
                action_type="follow_up",
                due_at=_suggest_due_at("follow_up", "medium"),
                lead_id=doc.lead_id,
                deal_id=doc.deal_id,
                proposal_id=doc.id,
                recommended_action="Contact buyer manually about the sent proposal",
            )
            created += 1

        await db.commit()
        logger.info("%s generate done scanned=%s created=%s skipped=%s", MARKER, scanned, created, skipped)
        return {
            "scanned": scanned,
            "created": created,
            "skipped_duplicates": skipped,
        }

    @staticmethod
    async def from_recommendation(
        db: AsyncSession,
        recommendation_id: UUID,
    ) -> dict[str, Any]:
        rec = await OperatorTaskEngineService._load_recommendation(db, recommendation_id)
        if rec.status != "open":
            raise HTTPException(status_code=400, detail="Recommendation already handled")
        if not rec.client_id:
            raise HTTPException(status_code=400, detail="Recommendation has no client")

        existing = await OperatorTaskEngineService._find_duplicate(
            db,
            recommendation_id=rec.id,
            action_type=_action_for_rec_type(rec.recommendation_type),
        )
        if existing:
            task = await OperatorTaskEngineService._load_engine_task(db, existing.id)
            return {"task": _serialize_task(task), "message": "Task already exists for this recommendation"}

        task = await OperatorTaskEngineService._create_from_recommendation_row(db, rec, mark_completed=True)
        if not task:
            raise HTTPException(status_code=409, detail="Could not create task")
        await db.commit()
        loaded = await OperatorTaskEngineService._load_engine_task(db, task.id)
        return {"task": _serialize_task(loaded), "message": "Task created from recommendation"}

    @staticmethod
    async def from_conversation(
        db: AsyncSession,
        conversation_id: str,
        *,
        task_type: str | None = None,
        title: str | None = None,
        description: str | None = None,
        priority: str | None = None,
        due_at: datetime | None = None,
    ) -> dict[str, Any]:
        detail = await UnifiedInboxService.get_conversation(db, conversation_id)
        conv = detail.get("conversation") or {}
        client_id = conv.get("client_id")
        if not client_id:
            raise HTTPException(status_code=400, detail="Conversation has no client — cannot create task")

        tt = (task_type or "follow_up").lower()
        action = {
            "reply": "reply_to_message",
            "follow_up": "follow_up",
            "proposal": "create_proposal",
            "link_lead": "link_lead",
        }.get(tt, "follow_up")

        default_title = {
            "reply_to_message": f"Reply: {conv.get('contact_name') or 'conversation'}",
            "follow_up": f"Follow up: {conv.get('contact_name') or 'conversation'}",
            "create_proposal": f"Create proposal: {conv.get('contact_name') or 'conversation'}",
            "link_lead": f"Link lead: {conv.get('contact_name') or 'conversation'}",
        }.get(action, "Sales action")

        prio = _engine_priority(priority or conv.get("priority") or "medium")
        suggested_due = due_at or _suggest_due_at(action, prio)

        dup = await OperatorTaskEngineService._find_duplicate(
            db,
            conversation_id=conversation_id,
            action_type=action,
        )
        if dup:
            loaded = await OperatorTaskEngineService._load_engine_task(db, dup.id)
            return {"task": _serialize_task(loaded), "message": "Open task already exists"}

        source, source_id = parse_unified_id(conversation_id)
        source_type = "unified_inbox" if source in ("thread", "whatsapp", "outreach") else "communication_hub"

        task = await OperatorTaskEngineService._persist_task(
            db,
            client_id=UUID(str(client_id)),
            source_type=source_type,
            source_id=source_id,
            title=(title or default_title)[:255],
            description=description or conv.get("last_message") or "Review conversation and take manual action.",
            priority=prio,
            action_type=action,
            due_at=suggested_due,
            conversation_id=conversation_id,
            channel=conv.get("channel"),
            lead_id=UUID(str(conv["lead_id"])) if conv.get("lead_id") else None,
            deal_id=UUID(str(conv["deal_id"])) if conv.get("deal_id") else None,
            recommended_action="Open conversation and complete action manually (no auto-send)",
        )
        await db.commit()
        loaded = await OperatorTaskEngineService._load_engine_task(db, task.id)
        return {"task": _serialize_task(loaded), "message": "Task created from conversation"}

    @staticmethod
    async def from_proposal(
        db: AsyncSession,
        proposal_id: UUID,
        *,
        due_at: datetime | None = None,
    ) -> dict[str, Any]:
        result = await db.execute(
            select(ProposalDocument).where(ProposalDocument.id == proposal_id)
        )
        doc = result.scalar_one_or_none()
        if not doc:
            raise HTTPException(status_code=404, detail="Proposal not found")

        dup = await OperatorTaskEngineService._find_duplicate(
            db,
            action_type="follow_up",
            proposal_id=doc.id,
            source_type="proposal",
            source_id=doc.id,
        )
        if dup:
            loaded = await OperatorTaskEngineService._load_engine_task(db, dup.id)
            return {"task": _serialize_task(loaded), "message": "Follow-up task already exists"}

        prio = "high" if doc.status == "sent" else "medium"
        suggested_due = due_at or _suggest_due_at("follow_up", prio)
        task = await OperatorTaskEngineService._persist_task(
            db,
            client_id=doc.client_id,
            source_type="proposal",
            source_id=doc.id,
            title=f"Follow up proposal: {doc.title}"[:255],
            description=f"Proposal status: {doc.status}. Manual follow-up only.",
            priority=prio,
            action_type="follow_up",
            due_at=suggested_due,
            lead_id=doc.lead_id,
            deal_id=doc.deal_id,
            proposal_id=doc.id,
            recommended_action="Follow up with buyer manually about this proposal",
        )
        await db.commit()
        loaded = await OperatorTaskEngineService._load_engine_task(db, task.id)
        return {"task": _serialize_task(loaded), "message": "Follow-up task created"}

    @staticmethod
    async def complete(db: AsyncSession, task_id: UUID) -> dict[str, Any]:
        task = await OperatorTaskEngineService._load_engine_task(db, task_id)
        if task.status in TERMINAL_STATUSES:
            return {"task": _serialize_task(task), "message": "Task already closed"}
        now = _utc_now()
        task.status = "done"
        task.completed_at = now
        task.updated_at = now
        await db.flush()
        await db.commit()
        await db.refresh(task, attribute_names=["client", "lead", "deal", "proposal"])
        logger.info("%s completed task=%s", MARKER, task_id)
        return {"task": _serialize_task(task), "message": "Task marked complete"}

    @staticmethod
    async def dismiss(db: AsyncSession, task_id: UUID) -> dict[str, Any]:
        task = await OperatorTaskEngineService._load_engine_task(db, task_id)
        if task.dismissed_at:
            return {"task": _serialize_task(task), "message": "Task already dismissed"}
        now = _utc_now()
        task.status = "canceled"
        task.dismissed_at = now
        task.updated_at = now
        await db.flush()
        await db.commit()
        await db.refresh(task, attribute_names=["client", "lead", "deal", "proposal"])
        logger.info("%s dismissed task=%s", MARKER, task_id)
        return {"task": _serialize_task(task), "message": "Task dismissed"}

    @staticmethod
    async def today_tasks(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        now = _utc_now()
        q = (
            select(OperatorTask)
            .options(
                selectinload(OperatorTask.client),
                selectinload(OperatorTask.lead),
                selectinload(OperatorTask.deal),
                selectinload(OperatorTask.proposal),
            )
            .where(
                OperatorTask.status.in_(tuple(OPEN_STATUSES)),
                OperatorTask.dismissed_at.is_(None),
                or_(
                    OperatorTask.due_at.is_(None),
                    func.date(OperatorTask.due_at) <= now.date(),
                ),
            )
            .order_by(OperatorTask.due_at.asc().nulls_last(), OperatorTask.priority.desc())
            .limit(limit)
        )
        if client_id:
            q = q.where(OperatorTask.client_id == client_id)
        rows = (await db.execute(q)).scalars().all()
        return {
            "count": len(rows),
            "items": [_serialize_task(t) for t in rows],
        }

    @staticmethod
    async def _create_from_candidate(db: AsyncSession, cand: _Candidate) -> bool:
        if not cand.client_id:
            return False
        action = _action_for_rec_type(cand.recommendation_type)
        dup = await OperatorTaskEngineService._find_duplicate(
            db,
            action_type=action,
            conversation_id=cand.conversation_id,
            lead_id=cand.lead_id,
            deal_id=cand.deal_id,
            dedupe_key=cand.dedupe_key,
        )
        if dup:
            return False
        source_id = None
        source_type = "sales_assistant"
        if cand.conversation_id and ":" in cand.conversation_id:
            try:
                _, source_id = parse_unified_id(cand.conversation_id)
                source_type = "unified_inbox"
            except HTTPException:
                pass
        await OperatorTaskEngineService._persist_task(
            db,
            client_id=cand.client_id,
            source_type=source_type,
            source_id=source_id,
            title=cand.title[:255],
            description=f"{cand.summary}\n\nRecommended: {cand.recommended_action}",
            priority=_engine_priority(cand.priority),
            action_type=action,
            due_at=_suggest_due_at(action, cand.priority),
            conversation_id=cand.conversation_id,
            channel=cand.channel,
            lead_id=cand.lead_id,
            deal_id=cand.deal_id,
            recommended_action=cand.recommended_action,
        )
        return True

    @staticmethod
    async def _create_from_recommendation_row(
        db: AsyncSession,
        rec: SalesAssistantRecommendation,
        *,
        mark_completed: bool,
    ) -> OperatorTask | None:
        if not rec.client_id:
            return None
        action = _action_for_rec_type(rec.recommendation_type)
        dup = await OperatorTaskEngineService._find_duplicate(
            db,
            recommendation_id=rec.id,
            action_type=action,
        )
        if dup:
            if mark_completed and rec.status == "open":
                rec.linked_task_id = dup.id
                rec.status = "completed"
                rec.updated_at = _utc_now()
            return dup

        source_id = rec.id
        task = await OperatorTaskEngineService._persist_task(
            db,
            client_id=rec.client_id,
            source_type="sales_assistant",
            source_id=source_id,
            title=rec.title[:255],
            description=f"{rec.summary}\n\nRecommended: {rec.recommended_action}",
            priority=_engine_priority(rec.priority),
            action_type=action,
            due_at=_suggest_due_at(action, rec.priority),
            recommendation_id=rec.id,
            conversation_id=rec.conversation_id,
            channel=rec.channel,
            lead_id=rec.lead_id,
            deal_id=rec.deal_id,
            recommended_action=rec.recommended_action,
        )
        if mark_completed:
            rec.status = "completed"
            rec.linked_task_id = task.id
            rec.updated_at = _utc_now()
        return task

    @staticmethod
    async def _persist_task(
        db: AsyncSession,
        *,
        client_id: UUID,
        source_type: str,
        source_id: UUID | None,
        title: str,
        description: str | None,
        priority: str,
        action_type: str,
        due_at: datetime | None,
        recommendation_id: UUID | None = None,
        conversation_id: str | None = None,
        channel: str | None = None,
        lead_id: UUID | None = None,
        deal_id: UUID | None = None,
        proposal_id: UUID | None = None,
        recommended_action: str | None = None,
    ) -> OperatorTask:
        if action_type not in ACTION_TYPES:
            action_type = "manual_sales_action"
        desc = description
        if recommended_action and recommended_action not in (desc or ""):
            desc = f"{desc or ''}\n\nRecommended: {recommended_action}".strip()

        task = OperatorTask(
            client_id=client_id,
            source_type=source_type,
            source_id=source_id,
            title=title,
            description=desc,
            priority=priority,
            status="todo",
            due_at=due_at,
            created_by="system",
            recommendation_id=recommendation_id,
            conversation_id=conversation_id,
            channel=channel,
            lead_id=lead_id,
            deal_id=deal_id,
            proposal_id=proposal_id,
            action_type=action_type,
        )
        db.add(task)
        await db.flush()
        logger.info(
            "%s task created id=%s action=%s source=%s",
            MARKER,
            task.id,
            action_type,
            source_type,
        )
        return task

    @staticmethod
    async def _find_duplicate(
        db: AsyncSession,
        *,
        action_type: str | None = None,
        conversation_id: str | None = None,
        recommendation_id: UUID | None = None,
        lead_id: UUID | None = None,
        deal_id: UUID | None = None,
        proposal_id: UUID | None = None,
        source_type: str | None = None,
        source_id: UUID | None = None,
        dedupe_key: str | None = None,
    ) -> OperatorTask | None:
        q = select(OperatorTask).where(
            OperatorTask.status.in_(tuple(OPEN_STATUSES)),
            OperatorTask.dismissed_at.is_(None),
        )
        if recommendation_id:
            q = q.where(OperatorTask.recommendation_id == recommendation_id)
        elif conversation_id and action_type:
            q = q.where(
                OperatorTask.conversation_id == conversation_id,
                OperatorTask.action_type == action_type,
            )
        elif proposal_id and action_type:
            q = q.where(
                OperatorTask.proposal_id == proposal_id,
                OperatorTask.action_type == action_type,
            )
        elif lead_id and action_type and not conversation_id:
            q = q.where(OperatorTask.lead_id == lead_id, OperatorTask.action_type == action_type)
        elif deal_id and action_type:
            q = q.where(OperatorTask.deal_id == deal_id, OperatorTask.action_type == action_type)
        elif source_type and source_id:
            q = q.where(
                OperatorTask.source_type == source_type,
                OperatorTask.source_id == source_id,
            )
        elif dedupe_key and ":" in dedupe_key:
            parts = dedupe_key.split(":")
            if len(parts) >= 3:
                try:
                    entity_id = UUID(parts[-1])
                    if parts[0] in ("reply", "stale_conv", "lead_link") and parts[1] == "thread":
                        q = q.where(
                            OperatorTask.conversation_id == f"thread:{entity_id}",
                            OperatorTask.action_type == action_type,
                        )
                    elif parts[0] == "follow_up" and parts[1] == "lead":
                        q = q.where(OperatorTask.lead_id == entity_id, OperatorTask.action_type == action_type)
                except ValueError:
                    return None
            else:
                return None
        else:
            return None

        q = q.order_by(OperatorTask.updated_at.desc()).limit(1)
        return (await db.execute(q)).scalar_one_or_none()

    @staticmethod
    async def _load_recommendation(
        db: AsyncSession,
        rec_id: UUID,
    ) -> SalesAssistantRecommendation:
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
    async def _load_engine_task(db: AsyncSession, task_id: UUID) -> OperatorTask:
        result = await db.execute(
            select(OperatorTask)
            .options(
                selectinload(OperatorTask.client),
                selectinload(OperatorTask.lead),
                selectinload(OperatorTask.deal),
                selectinload(OperatorTask.proposal),
            )
            .where(OperatorTask.id == task_id)
        )
        task = result.scalar_one_or_none()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return task
