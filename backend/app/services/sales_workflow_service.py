"""Sales Workflow Automation v1 — detect workflow gaps and recommend manual actions only."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.communication import CommunicationThread
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.operator_task import OperatorTask
from app.models.proposal_document import ProposalDocument
from app.models.sales_workflow_recommendation import SalesWorkflowRecommendation
from app.services.lead_classification_service import HOT_CLASSIFICATIONS, LeadClassificationService
from app.services.lead_intelligence_service import HOT_LEVELS, QUALIFIED_LEVELS
from app.services.operator_task_service import TERMINAL_STATUSES

logger = logging.getLogger(__name__)

MARKER = "[Sales Workflow]"

OPEN_STATUSES = frozenset({"open"})
_HOT_SCORE = 66
_STALE_LEAD_DAYS = 7
_INACTIVE_DAYS = 30
_PROPOSAL_STALL_DAYS = 7

WORKFLOW_TEMPLATES: list[dict[str, Any]] = [
    {
        "workflow_type": "follow_up_workflow",
        "name": "Follow-up Workflow",
        "description": "Schedule manual follow-ups for leads and conversations that need attention.",
        "typical_actions": ["schedule_follow_up", "create_task", "update_next_action"],
    },
    {
        "workflow_type": "proposal_workflow",
        "name": "Proposal Workflow",
        "description": "Review sent proposals and prepare qualified leads for commercial proposals.",
        "typical_actions": ["review_proposal", "create_task", "review_lead"],
    },
    {
        "workflow_type": "re_engagement_workflow",
        "name": "Re-engagement Workflow",
        "description": "Re-engage inactive leads with manual outreach recommendations.",
        "typical_actions": ["review_lead", "schedule_follow_up", "create_task"],
    },
    {
        "workflow_type": "crm_cleanup_workflow",
        "name": "CRM Cleanup Workflow",
        "description": "Link inbox conversations and clean up CRM data gaps.",
        "typical_actions": ["link_crm", "review_lead", "update_next_action"],
    },
    {
        "workflow_type": "hot_lead_workflow",
        "name": "Hot Lead Workflow",
        "description": "Prioritize hot leads that need immediate operator review.",
        "typical_actions": ["review_lead", "create_task", "schedule_follow_up"],
    },
]

_DETECTION_TO_WORKFLOW: dict[str, str] = {
    "hot_lead_no_followup": "hot_lead_workflow",
    "proposal_no_followup": "proposal_workflow",
    "inactive_lead": "re_engagement_workflow",
    "overdue_operator_task": "follow_up_workflow",
    "unlinked_inbox": "crm_cleanup_workflow",
    "qualified_no_proposal": "proposal_workflow",
    "lead_no_next_action": "follow_up_workflow",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _priority_rank(p: str) -> int:
    return {"urgent": 0, "high": 1, "medium": 2, "low": 3}.get(p, 4)


def _action(action: str, label: str, description: str) -> dict[str, str]:
    return {"action": action, "label": label, "description": description}


@dataclass
class _Candidate:
    detection_type: str
    workflow_type: str
    client_id: UUID | None
    lead_id: UUID | None
    deal_id: UUID | None
    proposal_id: UUID | None
    conversation_id: str | None
    channel: str | None
    priority: str
    title: str
    reason: str
    recommended_actions: list[dict[str, str]] = field(default_factory=list)
    dedupe_key: str = ""
    entity_type: str | None = None
    entity_id: str | None = None


def _serialize_rec(rec: SalesWorkflowRecommendation) -> dict[str, Any]:
    return {
        "id": rec.id,
        "client_id": rec.client_id,
        "client_name": rec.client.company_name if rec.client else None,
        "lead_id": rec.lead_id,
        "lead_name": rec.lead.name if rec.lead else None,
        "deal_id": rec.deal_id,
        "proposal_id": rec.proposal_id,
        "conversation_id": rec.conversation_id,
        "channel": rec.channel,
        "workflow_type": rec.workflow_type,
        "detection_type": rec.detection_type,
        "priority": rec.priority,
        "title": rec.title,
        "reason": rec.reason,
        "recommended_actions": rec.recommended_actions or [],
        "status": rec.status,
        "linked_task_id": rec.linked_task_id,
        "entity_type": rec.entity_type,
        "entity_id": rec.entity_id,
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


async def _overview_counts(
    db: AsyncSession,
    *,
    client_id: UUID | None = None,
) -> dict[str, Any]:
    base = [SalesWorkflowRecommendation.status == "open"]
    if client_id:
        base.append(SalesWorkflowRecommendation.client_id == client_id)

    active = await db.scalar(
        select(func.count()).select_from(SalesWorkflowRecommendation).where(*base)
    )
    high = await db.scalar(
        select(func.count()).select_from(SalesWorkflowRecommendation).where(
            *base,
            SalesWorkflowRecommendation.priority.in_(("urgent", "high")),
        )
    )
    follow_up = await db.scalar(
        select(func.count()).select_from(SalesWorkflowRecommendation).where(
            *base,
            SalesWorkflowRecommendation.workflow_type == "follow_up_workflow",
        )
    )
    proposal = await db.scalar(
        select(func.count()).select_from(SalesWorkflowRecommendation).where(
            *base,
            SalesWorkflowRecommendation.workflow_type == "proposal_workflow",
        )
    )
    cleanup = await db.scalar(
        select(func.count()).select_from(SalesWorkflowRecommendation).where(
            *base,
            SalesWorkflowRecommendation.workflow_type == "crm_cleanup_workflow",
        )
    )
    hot = await db.scalar(
        select(func.count()).select_from(SalesWorkflowRecommendation).where(
            *base,
            SalesWorkflowRecommendation.workflow_type == "hot_lead_workflow",
        )
    )
    reengage = await db.scalar(
        select(func.count()).select_from(SalesWorkflowRecommendation).where(
            *base,
            SalesWorkflowRecommendation.workflow_type == "re_engagement_workflow",
        )
    )
    return {
        "active_recommendations": int(active or 0),
        "high_priority": int(high or 0),
        "follow_up_workflows": int(follow_up or 0),
        "proposal_workflows": int(proposal or 0),
        "crm_cleanup_workflows": int(cleanup or 0),
        "hot_lead_workflows": int(hot or 0),
        "re_engagement_workflows": int(reengage or 0),
        "errors": [],
    }


class SalesWorkflowService:
    @staticmethod
    def templates() -> dict[str, Any]:
        return {"items": WORKFLOW_TEMPLATES}

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        return await _overview_counts(db, client_id=client_id)

    @staticmethod
    async def list_recommendations(
        db: AsyncSession,
        *,
        status: str | None = None,
        priority: str | None = None,
        workflow_type: str | None = None,
        client_id: UUID | None = None,
        lead_id: UUID | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        priority_rank = case(
            (SalesWorkflowRecommendation.priority == "urgent", 1),
            (SalesWorkflowRecommendation.priority == "high", 2),
            (SalesWorkflowRecommendation.priority == "medium", 3),
            else_=4,
        )
        query = (
            select(SalesWorkflowRecommendation)
            .options(
                selectinload(SalesWorkflowRecommendation.client),
                selectinload(SalesWorkflowRecommendation.lead),
                selectinload(SalesWorkflowRecommendation.deal),
            )
            .order_by(priority_rank, SalesWorkflowRecommendation.created_at.desc())
        )
        count_q = select(func.count()).select_from(SalesWorkflowRecommendation)
        filters = []
        if status:
            filters.append(SalesWorkflowRecommendation.status == status)
        else:
            filters.append(SalesWorkflowRecommendation.status != "dismissed")
        if priority:
            filters.append(SalesWorkflowRecommendation.priority == priority)
        if workflow_type:
            filters.append(SalesWorkflowRecommendation.workflow_type == workflow_type)
        if client_id:
            filters.append(SalesWorkflowRecommendation.client_id == client_id)
        if lead_id:
            filters.append(SalesWorkflowRecommendation.lead_id == lead_id)

        for flt in filters:
            query = query.where(flt)
            count_q = count_q.where(flt)

        total = (await db.execute(count_q)).scalar_one()
        result = await db.execute(query.offset(skip).limit(limit))
        items = [_serialize_rec(r) for r in result.scalars().unique().all()]
        overview = await _overview_counts(db, client_id=client_id)
        return {"items": items, "total": total, "overview": overview}

    @staticmethod
    async def top_open(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        data = await SalesWorkflowService.list_recommendations(
            db, status="open", client_id=client_id, limit=limit,
        )
        return data["items"]

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await _overview_counts(db, client_id=client_id)
        top = await SalesWorkflowService.top_open(db, client_id=client_id, limit=3)
        return {**overview, "top_recommendations": top}

    @staticmethod
    async def generate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        logger.info("%s generate started: client_id=%s", MARKER, client_id)
        candidates = await SalesWorkflowService._collect_candidates(db, client_id=client_id)
        created = 0
        skipped = 0

        for cand in candidates:
            exists = await db.execute(
                select(SalesWorkflowRecommendation.id).where(
                    SalesWorkflowRecommendation.dedupe_key == cand.dedupe_key,
                    SalesWorkflowRecommendation.status.in_(tuple(OPEN_STATUSES)),
                )
            )
            if exists.scalar_one_or_none():
                skipped += 1
                continue

            rec = SalesWorkflowRecommendation(
                client_id=cand.client_id,
                lead_id=cand.lead_id,
                deal_id=cand.deal_id,
                proposal_id=cand.proposal_id,
                conversation_id=cand.conversation_id,
                channel=cand.channel,
                workflow_type=cand.workflow_type,
                detection_type=cand.detection_type,
                priority=cand.priority,
                title=cand.title[:255],
                reason=cand.reason,
                recommended_actions=cand.recommended_actions,
                status="open",
                dedupe_key=cand.dedupe_key,
                entity_type=cand.entity_type,
                entity_id=cand.entity_id,
            )
            db.add(rec)
            await db.flush()
            created += 1
            logger.info(
                "%s recommendation created: id=%s type=%s workflow=%s",
                MARKER, rec.id, cand.detection_type, cand.workflow_type,
            )

        await db.commit()
        logger.info(
            "%s generate finished: candidates=%s created=%s skipped=%s",
            MARKER, len(candidates), created, skipped,
        )
        return {"scanned": len(candidates), "created": created, "skipped_duplicates": skipped}

    @staticmethod
    async def create_task_suggestion(db: AsyncSession, recommendation_id: UUID) -> dict[str, Any]:
        from app.services.operator_task_engine_service import (
            OperatorTaskEngineService,
            _suggest_due_at,
        )

        rec = await SalesWorkflowService._load_rec(db, recommendation_id)
        if rec.status != "open":
            raise HTTPException(status_code=400, detail="Recommendation is not open")

        action_type = SalesWorkflowService._primary_action_type(rec.recommended_actions or [])
        priority = "high" if rec.priority in ("urgent", "high") else "medium"
        title = rec.title[:255]
        description = f"{rec.reason}\n\nWorkflow: {rec.workflow_type.replace('_', ' ')}"
        actions_text = ", ".join(
            a.get("label", a.get("action", "")) for a in (rec.recommended_actions or [])
        )
        if actions_text:
            description = f"{description}\n\nSuggested actions: {actions_text}"

        if not rec.client_id:
            raise HTTPException(status_code=400, detail="Recommendation has no client — link CRM first")

        task = await OperatorTaskEngineService._persist_task(
            db,
            client_id=rec.client_id,
            source_type="sales_workflow",
            source_id=rec.id,
            title=title,
            description=description,
            priority=priority,
            action_type=action_type,
            due_at=_suggest_due_at(action_type, rec.priority),
            recommendation_id=None,
            conversation_id=rec.conversation_id,
            channel=rec.channel,
            lead_id=rec.lead_id,
            deal_id=rec.deal_id,
            proposal_id=rec.proposal_id,
            recommended_action=actions_text or rec.reason,
        )
        rec.linked_task_id = task.id
        rec.updated_at = _utc_now()
        await db.commit()
        await db.refresh(rec, attribute_names=["client", "lead", "deal"])
        logger.info("%s task suggestion created: rec=%s task=%s", MARKER, rec.id, task.id)
        return {
            "recommendation": _serialize_rec(rec),
            "task_id": task.id,
            "suggested": True,
        }

    @staticmethod
    def _primary_action_type(actions: list[dict[str, Any]]) -> str:
        mapping = {
            "create_task": "manual_sales_action",
            "schedule_follow_up": "follow_up",
            "review_proposal": "review_proposal",
            "review_lead": "review_hot_lead",
            "link_crm": "link_lead",
            "update_next_action": "follow_up",
        }
        for item in actions:
            action = item.get("action", "")
            if action in mapping:
                return mapping[action]
        return "manual_sales_action"

    @staticmethod
    async def _load_rec(db: AsyncSession, rec_id: UUID) -> SalesWorkflowRecommendation:
        result = await db.execute(
            select(SalesWorkflowRecommendation)
            .options(
                selectinload(SalesWorkflowRecommendation.client),
                selectinload(SalesWorkflowRecommendation.lead),
                selectinload(SalesWorkflowRecommendation.deal),
            )
            .where(SalesWorkflowRecommendation.id == rec_id)
        )
        rec = result.scalar_one_or_none()
        if not rec:
            raise HTTPException(status_code=404, detail="Workflow recommendation not found")
        return rec

    @staticmethod
    async def _collect_candidates(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> list[_Candidate]:
        now = _utc_now()
        candidates: list[_Candidate] = []

        await SalesWorkflowService._detect_leads(db, now, candidates, client_id=client_id)
        await SalesWorkflowService._detect_proposals(db, now, candidates, client_id=client_id)
        await SalesWorkflowService._detect_inbox(db, candidates, client_id=client_id)
        await SalesWorkflowService._detect_tasks(db, now, candidates, client_id=client_id)
        return candidates

    @staticmethod
    async def _detect_leads(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
        *,
        client_id: UUID | None = None,
    ) -> None:
        q = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
        if client_id:
            q = q.where(CrmLead.client_id == client_id)
        leads_r = await db.execute(q)
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
            is_qualified = (
                cls in HOT_CLASSIFICATIONS
                or (lead.qualification_level or "") in QUALIFIED_LEVELS
                or lead.status in ("qualified", "proposal_sent")
            )
            last_touch = await _last_lead_touch(db, lead.id)
            ref = last_touch or _aware(lead.created_at)
            days_idle = (now - ref).days if ref else None

            if is_hot and lead.status not in ("proposal_sent", "negotiation", "won"):
                if ref and ref < now - timedelta(days=3):
                    candidates.append(_Candidate(
                        detection_type="hot_lead_no_followup",
                        workflow_type=_DETECTION_TO_WORKFLOW["hot_lead_no_followup"],
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        proposal_id=None,
                        conversation_id=None,
                        channel=None,
                        priority="urgent" if cls_score >= 80 or (lead.lead_score or 0) >= 80 else "high",
                        title=f"Hot lead without follow-up: {lead.name}",
                        reason=(
                            f"Lead classified as {cls or 'hot'} (score {cls_score or lead.lead_score or '—'}) "
                            "with no recent activity."
                        ),
                        recommended_actions=[
                            _action("review_lead", "Review lead", "Open CRM and review lead profile manually"),
                            _action("schedule_follow_up", "Schedule follow-up", "Set next follow-up date in CRM"),
                            _action("create_task", "Create operator task", "Create a task for manual outreach"),
                        ],
                        dedupe_key=f"wf:hot_no_followup:{lead.id}",
                        entity_type="lead",
                        entity_id=str(lead.id),
                    ))

            if is_qualified and lead.status not in ("proposal_sent", "negotiation", "won"):
                has_proposal = await _lead_has_proposal(db, lead.id)
                if not has_proposal:
                    candidates.append(_Candidate(
                        detection_type="qualified_no_proposal",
                        workflow_type=_DETECTION_TO_WORKFLOW["qualified_no_proposal"],
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        proposal_id=None,
                        conversation_id=None,
                        channel=None,
                        priority="high" if is_hot else "medium",
                        title=f"Qualified lead without proposal: {lead.name}",
                        reason="Lead is qualified but has no commercial proposal on file.",
                        recommended_actions=[
                            _action("review_lead", "Review lead", "Confirm qualification in CRM"),
                            _action("create_task", "Prepare proposal", "Create task to draft proposal manually"),
                        ],
                        dedupe_key=f"wf:qualified_no_proposal:{lead.id}",
                        entity_type="lead",
                        entity_id=str(lead.id),
                    ))

            if cls == "inactive" or (
                days_idle is not None and days_idle >= _INACTIVE_DAYS and not is_hot
            ):
                candidates.append(_Candidate(
                    detection_type="inactive_lead",
                    workflow_type=_DETECTION_TO_WORKFLOW["inactive_lead"],
                    client_id=lead.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    proposal_id=None,
                    conversation_id=None,
                    channel=None,
                    priority="medium",
                    title=f"Inactive lead: {lead.name}",
                    reason=f"No engagement for {_INACTIVE_DAYS}+ days.",
                    recommended_actions=[
                        _action("review_lead", "Review lead", "Assess whether to re-engage or archive"),
                        _action("schedule_follow_up", "Plan re-engagement", "Schedule manual check-in date"),
                    ],
                    dedupe_key=f"wf:inactive:{lead.id}",
                    entity_type="lead",
                    entity_id=str(lead.id),
                ))

            if not lead.next_follow_up_at and lead.status in ("new", "contacted", "qualified"):
                if ref and ref < now - timedelta(days=_STALE_LEAD_DAYS):
                    candidates.append(_Candidate(
                        detection_type="lead_no_next_action",
                        workflow_type=_DETECTION_TO_WORKFLOW["lead_no_next_action"],
                        client_id=lead.client_id,
                        lead_id=lead.id,
                        deal_id=None,
                        proposal_id=None,
                        conversation_id=None,
                        channel=None,
                        priority="medium",
                        title=f"No next action: {lead.name}",
                        reason="Lead has no scheduled follow-up and no recent operator activity.",
                        recommended_actions=[
                            _action("update_next_action", "Set next action", "Update CRM next follow-up date"),
                            _action("create_task", "Create task", "Create operator task for follow-up"),
                        ],
                        dedupe_key=f"wf:no_next_action:{lead.id}",
                        entity_type="lead",
                        entity_id=str(lead.id),
                    ))

            if lead.next_follow_up_at and _aware(lead.next_follow_up_at) < now:
                candidates.append(_Candidate(
                    detection_type="lead_no_next_action",
                    workflow_type=_DETECTION_TO_WORKFLOW["lead_no_next_action"],
                    client_id=lead.client_id,
                    lead_id=lead.id,
                    deal_id=None,
                    proposal_id=None,
                    conversation_id=None,
                    channel=None,
                    priority="urgent",
                    title=f"Overdue follow-up: {lead.name}",
                    reason="CRM follow-up date is overdue.",
                    recommended_actions=[
                        _action("schedule_follow_up", "Reschedule follow-up", "Update follow-up date after manual contact"),
                        _action("create_task", "Create task", "Create urgent follow-up task"),
                    ],
                    dedupe_key=f"wf:overdue_followup:{lead.id}",
                    entity_type="lead",
                    entity_id=str(lead.id),
                ))

    @staticmethod
    async def _detect_proposals(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
        *,
        client_id: UUID | None = None,
    ) -> None:
        prop_filters = []
        if client_id:
            prop_filters.append(CrmProposal.client_id == client_id)
        props_r = await db.execute(
            select(CrmProposal).options(selectinload(CrmProposal.lead)).where(*prop_filters),
        )
        for prop in props_r.scalars().all():
            updated = _aware(prop.updated_at) or _aware(prop.created_at)
            if prop.status == "sent" and updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS):
                lead = prop.lead
                candidates.append(_Candidate(
                    detection_type="proposal_no_followup",
                    workflow_type=_DETECTION_TO_WORKFLOW["proposal_no_followup"],
                    client_id=prop.client_id,
                    lead_id=lead.id if lead else None,
                    deal_id=None,
                    proposal_id=None,
                    conversation_id=None,
                    channel=None,
                    priority="high",
                    title=f"Proposal sent without follow-up: {prop.title}",
                    reason=f"Proposal sent {_PROPOSAL_STALL_DAYS}+ days ago with no follow-up.",
                    recommended_actions=[
                        _action("review_proposal", "Review proposal", "Open proposal and review status"),
                        _action("schedule_follow_up", "Schedule follow-up", "Plan manual follow-up call or message"),
                        _action("create_task", "Create task", "Create follow-up task for operator"),
                    ],
                    dedupe_key=f"wf:proposal_stall:crm:{prop.id}",
                    entity_type="crm_proposal",
                    entity_id=str(prop.id),
                ))

        doc_filters = []
        if client_id:
            doc_filters.append(ProposalDocument.client_id == client_id)
        docs_r = await db.execute(
            select(ProposalDocument).options(selectinload(ProposalDocument.lead)).where(*doc_filters),
        )
        for doc in docs_r.scalars().all():
            updated = _aware(doc.updated_at) or _aware(doc.created_at)
            if doc.status == "sent" and updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS):
                lead = doc.lead
                candidates.append(_Candidate(
                    detection_type="proposal_no_followup",
                    workflow_type=_DETECTION_TO_WORKFLOW["proposal_no_followup"],
                    client_id=doc.client_id,
                    lead_id=lead.id if lead else None,
                    deal_id=None,
                    proposal_id=doc.id,
                    conversation_id=None,
                    channel=None,
                    priority="high",
                    title=f"Proposal document stalled: {doc.title}",
                    reason=f"Commercial proposal sent {_PROPOSAL_STALL_DAYS}+ days ago.",
                    recommended_actions=[
                        _action("review_proposal", "Review proposal", "Review proposal document status"),
                        _action("schedule_follow_up", "Schedule follow-up", "Plan manual buyer follow-up"),
                    ],
                    dedupe_key=f"wf:proposal_stall:doc:{doc.id}",
                    entity_type="proposal_document",
                    entity_id=str(doc.id),
                ))

    @staticmethod
    async def _detect_inbox(
        db: AsyncSession,
        candidates: list[_Candidate],
        *,
        client_id: UUID | None = None,
    ) -> None:
        thread_q = select(CommunicationThread).where(
            CommunicationThread.status.in_(("open", "waiting")),
        )
        if client_id:
            thread_q = thread_q.where(CommunicationThread.client_id == client_id)
        for thread in (await db.execute(thread_q)).scalars().all():
            conv_id = f"thread:{thread.id}"
            channel = thread.channel or "manual"
            if thread.client_id and not thread.lead_id:
                candidates.append(_Candidate(
                    detection_type="unlinked_inbox",
                    workflow_type=_DETECTION_TO_WORKFLOW["unlinked_inbox"],
                    client_id=thread.client_id,
                    lead_id=None,
                    deal_id=thread.deal_id,
                    proposal_id=None,
                    conversation_id=conv_id,
                    channel=channel,
                    priority="medium",
                    title=f"Unlinked inbox conversation: {thread.title or channel}",
                    reason="Active conversation is not linked to a CRM lead.",
                    recommended_actions=[
                        _action("link_crm", "Link to CRM", "Link conversation to existing or new lead"),
                        _action("review_lead", "Review pipeline", "Check CRM for matching buyer"),
                    ],
                    dedupe_key=f"wf:unlinked:thread:{thread.id}",
                    entity_type="communication_thread",
                    entity_id=str(thread.id),
                ))

    @staticmethod
    async def _detect_tasks(
        db: AsyncSession,
        now: datetime,
        candidates: list[_Candidate],
        *,
        client_id: UUID | None = None,
    ) -> None:
        task_q = select(OperatorTask).where(
            OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            OperatorTask.due_at.isnot(None),
            OperatorTask.due_at < now,
        )
        if client_id:
            task_q = task_q.where(OperatorTask.client_id == client_id)
        for task in (await db.execute(task_q.limit(30))).scalars().all():
            candidates.append(_Candidate(
                detection_type="overdue_operator_task",
                workflow_type=_DETECTION_TO_WORKFLOW["overdue_operator_task"],
                client_id=task.client_id,
                lead_id=task.lead_id,
                deal_id=task.deal_id,
                proposal_id=task.proposal_id,
                conversation_id=task.conversation_id,
                channel=task.channel,
                priority="urgent" if task.priority in ("urgent", "high") else "high",
                title=f"Overdue operator task: {task.title}",
                reason=f"Task was due {_aware(task.due_at).isoformat() if task.due_at else '—'}.",
                recommended_actions=[
                    _action("create_task", "Review task", "Complete or reschedule operator task manually"),
                    _action("update_next_action", "Update plan", "Adjust CRM next action after review"),
                ],
                dedupe_key=f"wf:overdue_task:{task.id}",
                entity_type="operator_task",
                entity_id=str(task.id),
            ))
