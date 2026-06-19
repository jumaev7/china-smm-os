"""AI Sales Manager v2 — executive sales layer (read-only analytics, manual briefing only)."""
from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.endpoint_guard import safe_section
from app.models.communication import CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.operator_task import OperatorTask
from app.models.proposal_document import ProposalDocument
from app.models.whatsapp import WhatsAppThread
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.lead_classification_service import HOT_CLASSIFICATIONS, LeadClassificationService
from app.services.lead_intelligence_service import HOT_LEVELS, LeadIntelligenceService
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.operator_task_service import TERMINAL_STATUSES
from app.services.sales_assistant_service import _HOT_SCORE, _PROPOSAL_STALL_DAYS, _STALE_DEAL_DAYS
from app.services.sales_workflow_service import SalesWorkflowService
from app.services.revenue_attribution_service import RevenueAttributionService

logger = logging.getLogger(__name__)

MARKER = "[Sales Manager]"

_ACTIVE_DEAL = frozenset({"new", "proposal", "contract", "invoice", "waiting_payment"})
_OVERLOAD_TASK_THRESHOLD = 8

_AI_BRIEFING_SYSTEM = """\
You are an AI Sales Manager producing an executive briefing for a B2B export sales team.
Return ONLY JSON:
{
  "summary": "2-4 sentence executive summary",
  "opportunities": ["opportunity 1", "opportunity 2"],
  "risks": ["risk 1", "risk 2"],
  "recommendations": ["manual action 1", "manual action 2"]
}

Rules:
- Read-only advisory — never suggest auto-messaging, auto CRM updates, or auto proposal sending
- Recommend manual operator review only
- Max 5 items per list; be specific using metrics from context
"""


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


def _severity_rank(s: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(s, 4)


@dataclass
class _Snapshot:
    now: datetime
    client_id: UUID | None = None
    lead_metrics: dict[str, Any] = field(default_factory=dict)
    leads: list[CrmLead] = field(default_factory=list)
    opportunities: list[dict[str, Any]] = field(default_factory=list)
    risks: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    overview: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    workflow_summary: dict[str, Any] = field(default_factory=dict)


class SalesManagerService:
    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await SalesManagerService._build_snapshot(db, client_id=client_id)
        return {**snap.overview, "errors": snap.errors}

    @staticmethod
    async def opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        snap = await SalesManagerService._build_snapshot(db, client_id=client_id)
        items = snap.opportunities[:limit]
        return {"items": items, "total": len(snap.opportunities)}

    @staticmethod
    async def risks(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        snap = await SalesManagerService._build_snapshot(db, client_id=client_id)
        items = snap.risks[:limit]
        return {"items": items, "total": len(snap.risks)}

    @staticmethod
    async def recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 30,
    ) -> dict[str, Any]:
        snap = await SalesManagerService._build_snapshot(db, client_id=client_id)
        items = snap.recommendations[:limit]
        return {"items": items, "total": len(snap.recommendations)}

    @staticmethod
    async def generate_briefing(
        db: AsyncSession,
        *,
        use_ai: bool = False,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await SalesManagerService._build_snapshot(db, client_id=client_id)
        errors = list(snap.errors)
        now = snap.now

        if use_ai and not settings.DEMO_MODE and (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
            try:
                _validate_api_key()
                ctx = SalesManagerService._briefing_context(snap)
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _AI_BRIEFING_SYSTEM},
                        {"role": "user", "content": ctx[:12000]},
                    ],
                    temperature=0.35,
                    max_tokens=900,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                result = {
                    "summary": str(parsed.get("summary") or "")[:2000],
                    "opportunities": [str(x)[:300] for x in (parsed.get("opportunities") or [])[:5]],
                    "risks": [str(x)[:300] for x in (parsed.get("risks") or [])[:5]],
                    "recommendations": [str(x)[:300] for x in (parsed.get("recommendations") or [])[:5]],
                    "source": "ai",
                    "generated_at": now,
                    "errors": errors,
                }
                logger.info("%s briefing generated: source=ai client=%s", MARKER, client_id)
                return result
            except Exception as exc:
                logger.warning("%s AI briefing fallback: %s", MARKER, exc)
                errors.append(f"ai_briefing: {exc}")

        heuristic = SalesManagerService._heuristic_briefing(snap)
        heuristic["generated_at"] = now
        heuristic["errors"] = errors
        logger.info("%s briefing generated: source=%s client=%s", MARKER, heuristic["source"], client_id)
        return heuristic

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await SalesManagerService._build_snapshot(db, client_id=client_id)
        ov = snap.overview
        return {
            "hot_leads": ov.get("hot_leads", 0),
            "opportunities_count": ov.get("opportunities_count", 0),
            "risks_count": ov.get("risks_count", 0),
            "overdue_tasks": ov.get("overdue_tasks", 0),
            "open_conversations": ov.get("inbox_activity", {}).get("open_conversations", 0),
            "active_proposals": ov.get("active_proposals", 0),
            "workflow_recommendations": ov.get("workflow_recommendations", 0),
            "workflow_high_priority": ov.get("workflow_high_priority", 0),
            "top_workflow_recommendations": snap.workflow_summary.get("top_recommendations") or [],
            "top_opportunities": [
                {"type": o["type"], "title": o["title"], "priority": o["priority"]}
                for o in snap.opportunities[:3]
            ],
            "top_risks": [
                {"issue": r["issue"], "severity": r["severity"]}
                for r in snap.risks[:3]
            ],
            "revenue_performance": snap.lead_metrics.get("revenue_performance") or {},
        }

    @staticmethod
    async def _build_snapshot(db: AsyncSession, *, client_id: UUID | None) -> _Snapshot:
        now = _utc_now()
        errors: list[str] = []
        snap = _Snapshot(now=now, client_id=client_id, errors=errors)

        async def _lead_metrics() -> dict[str, Any]:
            return await LeadIntelligenceService.metrics(db, client_id=client_id)

        async def _load_leads() -> list[CrmLead]:
            q = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
            if client_id:
                q = q.where(CrmLead.client_id == client_id)
            r = await db.execute(q)
            return list(r.scalars().all())

        snap.lead_metrics = await safe_section(
            "lead_metrics", _lead_metrics(), default={}, errors=errors, db=db,
        )
        snap.leads = await safe_section("leads", _load_leads(), default=[], errors=errors, db=db)

        async def _classification_overview() -> dict[str, Any]:
            return await LeadClassificationService.overview(db, client_id=client_id)

        snap.lead_metrics = {
            **snap.lead_metrics,
            **await safe_section(
                "lead_classification",
                _classification_overview(),
                default={},
                errors=errors,
                db=db,
            ),
        }

        await SalesManagerService._detect_opportunities(db, snap)
        await SalesManagerService._detect_risks(db, snap)

        async def _comm_intel() -> dict[str, Any]:
            return await CommunicationIntelligenceService.communication_risks_and_opportunities(
                db, client_id=client_id, limit=10,
            )

        comm_data = await safe_section(
            "communication_intelligence",
            _comm_intel(),
            default={"risks": [], "opportunities": [], "follow_ups_required": 0, "avg_health_score": 0},
            errors=errors,
            db=db,
        )
        for risk in comm_data.get("risks") or []:
            if len(snap.risks) < 25:
                snap.risks.append(risk)
        for opp in comm_data.get("opportunities") or []:
            snap.opportunities.append(opp)
        snap.lead_metrics["communication_intelligence"] = {
            "follow_ups_required": comm_data.get("follow_ups_required", 0),
            "avg_health_score": comm_data.get("avg_health_score", 0),
            "risk_count": len(comm_data.get("risks") or []),
            "opportunity_count": len(comm_data.get("opportunities") or []),
        }

        SalesManagerService._build_recommendations(snap)

        async def _workflow_summary() -> dict[str, Any]:
            return await SalesWorkflowService.summary_widget(db, client_id=client_id)

        snap.workflow_summary = await safe_section(
            "workflow_recommendations",
            _workflow_summary(),
            default={"active_recommendations": 0, "high_priority": 0, "top_recommendations": []},
            errors=errors,
            db=db,
        )

        async def _revenue_performance() -> dict[str, Any]:
            widget = await RevenueAttributionService.summary_widget(db, client_id=client_id)
            insights = await RevenueAttributionService.insights(db, client_id=client_id)
            return {**widget, "insights": insights}

        snap.lead_metrics["revenue_performance"] = await safe_section(
            "revenue_attribution",
            _revenue_performance(),
            default={},
            errors=errors,
            db=db,
        )

        snap.overview = await SalesManagerService._compute_overview(db, snap)
        return snap

    @staticmethod
    async def _compute_overview(db: AsyncSession, snap: _Snapshot) -> dict[str, Any]:
        now = snap.now
        lm = snap.lead_metrics

        open_tasks_q = select(func.count()).select_from(OperatorTask).where(
            OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
        )
        overdue_tasks_q = select(func.count()).select_from(OperatorTask).where(
            OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            OperatorTask.due_at.isnot(None),
            OperatorTask.due_at < now,
        )
        urgent_tasks_q = select(func.count()).select_from(OperatorTask).where(
            OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            OperatorTask.priority.in_(("urgent", "high")),
        )
        unassigned_q = select(func.count()).select_from(OperatorTask).where(
            OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            OperatorTask.assigned_to.is_(None),
        )
        if snap.client_id:
            open_tasks_q = open_tasks_q.where(OperatorTask.client_id == snap.client_id)
            overdue_tasks_q = overdue_tasks_q.where(OperatorTask.client_id == snap.client_id)
            urgent_tasks_q = urgent_tasks_q.where(OperatorTask.client_id == snap.client_id)
            unassigned_q = unassigned_q.where(OperatorTask.client_id == snap.client_id)

        open_tasks = int(await db.scalar(open_tasks_q) or 0)
        overdue_tasks = int(await db.scalar(overdue_tasks_q) or 0)
        urgent_tasks = int(await db.scalar(urgent_tasks_q) or 0)
        unassigned = int(await db.scalar(unassigned_q) or 0)

        assignee_q = (
            select(OperatorTask.assigned_to, func.count())
            .where(
                OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
                OperatorTask.assigned_to.isnot(None),
            )
            .group_by(OperatorTask.assigned_to)
        )
        if snap.client_id:
            assignee_q = assignee_q.where(OperatorTask.client_id == snap.client_id)
        overloaded = sum(1 for _, cnt in (await db.execute(assignee_q)).all() if int(cnt or 0) >= _OVERLOAD_TASK_THRESHOLD)

        prop_q = select(func.count()).select_from(CrmProposal).where(
            CrmProposal.status.in_(("draft", "sent")),
        )
        doc_q = select(func.count()).select_from(ProposalDocument).where(
            ProposalDocument.status.in_(("draft", "sent", "review")),
        )
        sent_prop_q = select(func.count()).select_from(CrmProposal).where(CrmProposal.status == "sent")
        won_with_prop_q = select(func.count()).select_from(CrmLead).where(
            CrmLead.status == "won",
            CrmLead.id.in_(
                select(CrmProposal.lead_id).where(CrmProposal.status.in_(("sent", "accepted"))),
            ),
        )
        if snap.client_id:
            prop_q = prop_q.where(CrmProposal.client_id == snap.client_id)
            doc_q = doc_q.where(ProposalDocument.client_id == snap.client_id)
            sent_prop_q = sent_prop_q.where(CrmProposal.client_id == snap.client_id)
            won_with_prop_q = won_with_prop_q.where(CrmLead.client_id == snap.client_id)

        active_proposals = int(await db.scalar(prop_q) or 0) + int(await db.scalar(doc_q) or 0)
        sent_proposals = int(await db.scalar(sent_prop_q) or 0)
        won_from_proposals = int(await db.scalar(won_with_prop_q) or 0)
        conversion = round(won_from_proposals / sent_proposals * 100, 1) if sent_proposals else 0.0

        thread_q = select(func.count()).select_from(CommunicationThread).where(
            CommunicationThread.status.in_(("open", "waiting")),
        )
        if snap.client_id:
            thread_q = thread_q.where(CommunicationThread.client_id == snap.client_id)
        open_conversations = int(await db.scalar(thread_q) or 0)

        wa_threads_q = select(func.count()).select_from(WhatsAppThread)
        wechat_threads_q = select(func.count()).select_from(CommunicationThread).where(
            CommunicationThread.channel == "wechat",
        )
        if snap.client_id:
            wechat_threads_q = wechat_threads_q.where(CommunicationThread.client_id == snap.client_id)

        wa_threads = int(await db.scalar(wa_threads_q) or 0)
        wechat_threads = int(await db.scalar(wechat_threads_q) or 0)

        cutoff_24h = now - timedelta(hours=24)
        active_24h = int(await db.scalar(
            select(func.count()).select_from(CommunicationThread).where(
                CommunicationThread.last_message_at >= cutoff_24h,
            ),
        ) or 0)

        leads_count = len(snap.leads) if snap.leads else int(lm.get("hot_leads", 0) + lm.get("neglected_leads", 0))

        total_leads_q = select(func.count()).select_from(CrmLead).where(
            CrmLead.status.notin_(("won", "lost")),
        )
        if snap.client_id:
            total_leads_q = total_leads_q.where(CrmLead.client_id == snap.client_id)
        leads_count = int(await db.scalar(total_leads_q) or 0)

        unanswered = sum(
            1 for o in snap.opportunities if o.get("type") in ("reply_needed", "unanswered_inbox")
        )

        return {
            "leads_count": leads_count,
            "hot_leads": int(lm.get("hot_leads") or 0),
            "qualified_leads": int(lm.get("qualified_leads") or 0),
            "neglected_leads": int(lm.get("neglected_leads") or 0),
            "overdue_tasks": overdue_tasks,
            "active_proposals": active_proposals,
            "proposal_conversion_rate": conversion,
            "inbox_activity": {
                "open_conversations": open_conversations,
                "unanswered": unanswered,
                "active_24h": active_24h,
                "wechat_threads": wechat_threads,
                "whatsapp_threads": wa_threads,
            },
            "operator_workload": {
                "open_tasks": open_tasks,
                "overdue_tasks": overdue_tasks,
                "urgent_tasks": urgent_tasks,
                "unassigned_tasks": unassigned,
                "overloaded_assignees": overloaded,
            },
            "opportunities_count": len(snap.opportunities),
            "risks_count": len(snap.risks),
            "conversations_count": open_conversations + wa_threads,
            "workflow_recommendations": int(snap.workflow_summary.get("active_recommendations") or 0),
            "workflow_high_priority": int(snap.workflow_summary.get("high_priority") or 0),
            "workflow_follow_ups": int(snap.workflow_summary.get("follow_up_workflows") or 0),
            "workflow_proposals": int(snap.workflow_summary.get("proposal_workflows") or 0),
            "workflow_crm_cleanup": int(snap.workflow_summary.get("crm_cleanup_workflows") or 0),
            "communication_intelligence": lm.get("communication_intelligence") or {},
            "revenue_performance": lm.get("revenue_performance") or {},
        }

    @staticmethod
    async def _detect_opportunities(db: AsyncSession, snap: _Snapshot) -> None:
        now = snap.now
        items: list[dict[str, Any]] = []
        client_id = snap.client_id

        for lead in snap.leads:
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
            if is_hot and lead.status not in ("proposal_sent", "negotiation", "won"):
                last_touch = await SalesManagerService._last_lead_touch(db, lead.id)
                ref = last_touch or _aware(lead.updated_at) or _aware(lead.created_at)
                if ref and ref < now - timedelta(days=3):
                    items.append({
                        "type": "hot_lead_no_followup",
                        "source": "crm",
                        "priority": "urgent" if cls_score >= 80 or (lead.lead_score or 0) >= 80 else "high",
                        "action": "Review hot lead and schedule manual follow-up",
                        "title": f"Hot lead without follow-up: {lead.name}",
                        "summary": (
                            f"Classification {cls or '—'}, score {cls_score or lead.lead_score or '—'}, "
                            "no recent activity."
                        ),
                        "lead_id": lead.id,
                        "entity_id": str(lead.id),
                        "classification": cls,
                    })

            if not lead.next_follow_up_at and lead.status in ("new", "contacted", "qualified"):
                items.append({
                    "type": "lead_no_next_action",
                    "source": "crm",
                    "priority": "medium",
                    "action": "Set next follow-up or create operator task",
                    "title": f"No next action: {lead.name}",
                    "summary": "Lead lacks scheduled follow-up.",
                    "lead_id": lead.id,
                    "entity_id": str(lead.id),
                })

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
                items.append({
                    "type": "proposal_no_followup",
                    "source": "proposals",
                    "priority": "high",
                    "action": "Follow up on sent proposal manually",
                    "title": f"Proposal sent, no follow-up: {prop.title}",
                    "summary": f"Sent {_PROPOSAL_STALL_DAYS}+ days ago.",
                    "lead_id": lead.id if lead else None,
                    "entity_id": str(prop.id),
                })

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
                items.append({
                    "type": "proposal_no_followup",
                    "source": "proposals",
                    "priority": "high",
                    "action": "Follow up on proposal document manually",
                    "title": f"Proposal document stalled: {doc.title}",
                    "summary": f"Sent {_PROPOSAL_STALL_DAYS}+ days ago.",
                    "lead_id": lead.id if lead else None,
                    "entity_id": str(doc.id),
                })

        thread_q = (
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .where(CommunicationThread.status.in_(("open", "waiting")))
        )
        if client_id:
            thread_q = thread_q.where(CommunicationThread.client_id == client_id)
        for thread in (await db.execute(thread_q)).scalars().all():
            msgs = list(thread.messages or [])
            conv_id = f"thread:{thread.id}"
            channel = thread.channel or "manual"
            source = "wechat" if channel == "wechat" else "unified_inbox"

            if thread.client_id and not thread.lead_id:
                items.append({
                    "type": "conversation_no_crm_link",
                    "source": source,
                    "priority": "medium",
                    "action": "Link conversation to CRM lead manually",
                    "title": f"Active conversation without CRM link: {thread.title or channel}",
                    "summary": "Conversation not linked to pipeline.",
                    "conversation_id": conv_id,
                    "entity_id": str(thread.id),
                })

            outbound_times = [m.created_at for m in msgs if m.direction == "outbound"]
            last_out = max(outbound_times) if outbound_times else None
            unanswered = [
                m for m in msgs
                if m.direction == "inbound" and (last_out is None or m.created_at > last_out)
            ]
            if unanswered:
                items.append({
                    "type": "reply_needed",
                    "source": source,
                    "priority": "urgent" if len(unanswered) > 1 else "high",
                    "action": "Review and reply manually",
                    "title": f"Unanswered conversation: {thread.title or channel}",
                    "summary": f"{len(unanswered)} inbound message(s) awaiting reply.",
                    "conversation_id": conv_id,
                    "lead_id": thread.lead_id,
                    "entity_id": str(thread.id),
                })

            inbound_recent = [m for m in msgs if m.direction == "inbound" and _aware(m.created_at) and _aware(m.created_at) >= now - timedelta(days=2)]
            if len(inbound_recent) >= 3:
                items.append({
                    "type": "repeated_buyer_activity",
                    "source": source,
                    "priority": "high",
                    "action": "Review buyer engagement and plan next step",
                    "title": f"Repeated buyer activity: {thread.title or channel}",
                    "summary": f"{len(inbound_recent)} inbound messages in 48h.",
                    "conversation_id": conv_id,
                    "lead_id": thread.lead_id,
                    "entity_id": str(thread.id),
                })

        wa_r = await db.execute(
            select(WhatsAppThread).options(
                selectinload(WhatsAppThread.messages),
                selectinload(WhatsAppThread.contact),
            ),
        )
        for wa in wa_r.scalars().all():
            if client_id and wa.contact and wa.contact.crm_client_id != client_id:
                continue
            msgs = list(wa.messages or [])
            conv_id = f"whatsapp:{wa.id}"
            outbound = [m for m in msgs if m.direction == "outgoing" and m.status != "draft"]
            last_out = max((m.created_at for m in outbound), default=None)
            unanswered = [
                m for m in msgs
                if m.direction == "incoming" and (last_out is None or m.created_at > last_out)
            ]
            if unanswered:
                items.append({
                    "type": "reply_needed",
                    "source": "whatsapp",
                    "priority": "high",
                    "action": "Open WhatsApp center and reply manually",
                    "title": "WhatsApp reply needed",
                    "summary": f"{len(unanswered)} message(s) awaiting reply.",
                    "conversation_id": conv_id,
                    "entity_id": str(wa.id),
                })

        task_q = select(OperatorTask).where(
            OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            OperatorTask.due_at.isnot(None),
            OperatorTask.due_at < now,
        )
        if client_id:
            task_q = task_q.where(OperatorTask.client_id == client_id)
        for task in (await db.execute(task_q.limit(20))).scalars().all():
            items.append({
                "type": "overdue_operator_task",
                "source": "operator_tasks",
                "priority": "urgent" if task.priority in ("urgent", "high") else "high",
                "action": "Complete or reschedule operator task",
                "title": f"Overdue task: {task.title}",
                "summary": f"Due {_aware(task.due_at).isoformat() if task.due_at else '—'}.",
                "lead_id": task.lead_id,
                "entity_id": str(task.id),
            })

        items.sort(key=lambda x: (_priority_rank(x["priority"]), x["title"]))
        snap.opportunities = items

    @staticmethod
    async def _detect_risks(db: AsyncSession, snap: _Snapshot) -> None:
        now = snap.now
        items: list[dict[str, Any]] = []
        client_id = snap.client_id

        neglected = int(snap.lead_metrics.get("neglected_leads") or 0)
        if neglected:
            items.append({
                "issue": f"{neglected} neglected lead(s) with no recent engagement",
                "severity": "high" if neglected >= 5 else "medium",
                "recommendation": "Review neglected leads in CRM and schedule manual outreach",
                "type": "neglected_leads",
                "source": "crm",
            })

        deal_q = select(CrmDeal).options(selectinload(CrmDeal.lead)).where(
            CrmDeal.status.in_(tuple(_ACTIVE_DEAL)),
        )
        if client_id:
            deal_q = deal_q.where(CrmDeal.client_id == client_id)
        stale_deals = 0
        for deal in (await db.execute(deal_q)).scalars().all():
            updated = _aware(deal.updated_at) or _aware(deal.created_at)
            if updated and updated < now - timedelta(days=_STALE_DEAL_DAYS):
                stale_deals += 1
                lead = deal.lead
                items.append({
                    "issue": f"Stale deal: {deal.title}",
                    "severity": "high",
                    "recommendation": "Review deal room and log next step manually",
                    "type": "stale_deal",
                    "source": "crm",
                    "deal_id": deal.id,
                    "lead_id": deal.lead_id,
                })
                if stale_deals >= 10:
                    break

        thread_q = (
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .where(CommunicationThread.status.in_(("open", "waiting")))
        )
        if client_id:
            thread_q = thread_q.where(CommunicationThread.client_id == client_id)
        unanswered_count = 0
        for thread in (await db.execute(thread_q)).scalars().all():
            msgs = list(thread.messages or [])
            outbound_times = [m.created_at for m in msgs if m.direction == "outbound"]
            last_out = max(outbound_times) if outbound_times else None
            unanswered = [
                m for m in msgs
                if m.direction == "inbound" and (last_out is None or m.created_at > last_out)
            ]
            if unanswered:
                unanswered_count += 1
                if unanswered_count <= 8:
                    ch = thread.channel or "inbox"
                    items.append({
                        "issue": f"Unanswered {ch} conversation: {thread.title or 'thread'}",
                        "severity": "high" if len(unanswered) > 1 else "medium",
                        "recommendation": "Reply manually — no auto-send",
                        "type": "unanswered_inbox",
                        "source": ch,
                        "conversation_id": f"thread:{thread.id}",
                    })

        overdue_prop = 0
        prop_q = select(CrmProposal).where(CrmProposal.status == "sent")
        if client_id:
            prop_q = prop_q.where(CrmProposal.client_id == client_id)
        for prop in (await db.execute(prop_q)).scalars().all():
            updated = _aware(prop.updated_at) or _aware(prop.created_at)
            if updated and updated < now - timedelta(days=_PROPOSAL_STALL_DAYS * 2):
                overdue_prop += 1
                if overdue_prop <= 5:
                    items.append({
                        "issue": f"Overdue proposal follow-up: {prop.title}",
                        "severity": "high",
                        "recommendation": "Chase proposal manually",
                        "type": "overdue_proposal",
                        "source": "proposals",
                    })

        assignee_counts: Counter[str] = Counter()
        task_q = select(OperatorTask).where(OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)))
        if client_id:
            task_q = task_q.where(OperatorTask.client_id == client_id)
        for task in (await db.execute(task_q)).scalars().all():
            if task.assigned_to:
                assignee_counts[task.assigned_to] += 1
        for assignee, cnt in assignee_counts.items():
            if cnt >= _OVERLOAD_TASK_THRESHOLD:
                items.append({
                    "issue": f"Overloaded operator: {assignee} ({cnt} open tasks)",
                    "severity": "medium",
                    "recommendation": "Rebalance workload manually across operators",
                    "type": "overloaded_operator",
                    "source": "operator_tasks",
                })

        unassigned_q = select(func.count()).select_from(OperatorTask).where(
            OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)),
            OperatorTask.assigned_to.is_(None),
        )
        if client_id:
            unassigned_q = unassigned_q.where(OperatorTask.client_id == client_id)
        unassigned = int(await db.scalar(unassigned_q) or 0)
        if unassigned >= 3:
            items.append({
                "issue": f"{unassigned} unassigned operator task(s)",
                "severity": "medium",
                "recommendation": "Assign tasks to operators manually",
                "type": "unassigned_tasks",
                "source": "operator_tasks",
            })

        items.sort(key=lambda x: (_severity_rank(x["severity"]), x["issue"]))
        snap.risks = items

    @staticmethod
    def _build_recommendations(snap: _Snapshot) -> None:
        recs: list[dict[str, Any]] = []

        for opp in snap.opportunities[:15]:
            cat = "follow_up"
            if opp["type"] in ("hot_lead_no_followup", "repeated_buyer_activity"):
                cat = "priority_action"
            elif opp["type"] == "proposal_no_followup":
                cat = "proposal_reminder"
            elif opp["type"] == "conversation_no_crm_link":
                cat = "lead_assignment"
            elif opp["type"] == "overdue_operator_task":
                cat = "priority_action"
            elif opp["type"] in ("hot_buyer_conversation", "proposal_requested_conversation"):
                cat = "priority_action"
            recs.append({
                "category": cat,
                "title": opp["title"],
                "description": opp["action"],
                "priority": opp["priority"],
                "lead_id": opp.get("lead_id"),
                "conversation_id": opp.get("conversation_id"),
            })

        for risk in snap.risks[:10]:
            if risk["type"] == "overloaded_operator":
                recs.append({
                    "category": "workload_balance",
                    "title": risk["issue"],
                    "description": risk["recommendation"],
                    "priority": "medium",
                })
            elif risk["type"] == "neglected_leads":
                recs.append({
                    "category": "follow_up",
                    "title": "Address neglected leads",
                    "description": risk["recommendation"],
                    "priority": "high",
                })
            elif risk["type"] in ("unanswered_inbox", "overdue_proposal", "unanswered_conversation", "inactive_conversation"):
                sev = risk["severity"]
                pri = "high" if sev in ("critical", "high") else "medium"
                recs.append({
                    "category": "priority_action",
                    "title": risk["issue"],
                    "description": risk["recommendation"],
                    "priority": pri,
                })

        for wf in (snap.workflow_summary.get("top_recommendations") or [])[:5]:
            recs.append({
                "category": "workflow",
                "title": wf.get("title") or "Workflow recommendation",
                "description": wf.get("reason") or "Review workflow recommendation manually",
                "priority": wf.get("priority") or "medium",
                "lead_id": wf.get("lead_id"),
                "conversation_id": wf.get("conversation_id"),
                "workflow_type": wf.get("workflow_type"),
            })

        recs.sort(key=lambda x: (_priority_rank(x["priority"]), x["title"]))
        snap.recommendations = recs[:25]

    @staticmethod
    async def _last_lead_touch(db: AsyncSession, lead_id: UUID) -> datetime | None:
        act_r = await db.execute(
            select(func.max(CrmActivity.created_at)).where(CrmActivity.lead_id == lead_id),
        )
        last_act = act_r.scalar_one_or_none()
        lead_r = await db.execute(select(CrmLead.updated_at).where(CrmLead.id == lead_id))
        updated = lead_r.scalar_one_or_none()
        candidates = [_aware(last_act), _aware(updated)]
        valid = [c for c in candidates if c]
        return max(valid) if valid else None

    @staticmethod
    def _briefing_context(snap: _Snapshot) -> str:
        ov = snap.overview
        lines = [
            "SALES MANAGER EXECUTIVE METRICS (read-only):",
            json.dumps(ov, default=str),
            "",
            "TOP OPPORTUNITIES:",
        ]
        for o in snap.opportunities[:8]:
            lines.append(f"- [{o['priority']}] {o['title']}: {o['action']}")
        lines.append("")
        lines.append("TOP RISKS:")
        for r in snap.risks[:8]:
            lines.append(f"- [{r['severity']}] {r['issue']}")
        lines.append("")
        lines.append("RECOMMENDATIONS:")
        for rec in snap.recommendations[:8]:
            lines.append(f"- [{rec['category']}] {rec['title']}")
        return "\n".join(lines)

    @staticmethod
    def _heuristic_briefing(snap: _Snapshot) -> dict[str, Any]:
        ov = snap.overview
        lm = snap.lead_metrics

        summary = (
            f"Sales pipeline: {ov.get('leads_count', 0)} active leads "
            f"({ov.get('hot_leads', 0)} hot, {ov.get('qualified_leads', 0)} qualified). "
            f"{ov.get('active_proposals', 0)} active proposals "
            f"({ov.get('proposal_conversion_rate', 0)}% conversion). "
            f"{ov.get('opportunities_count', 0)} opportunities and "
            f"{ov.get('risks_count', 0)} risks detected. "
            f"Operator workload: {ov.get('operator_workload', {}).get('open_tasks', 0)} open tasks, "
            f"{ov.get('overdue_tasks', 0)} overdue."
        )

        opportunities = [
            f"{o['title']} — {o['action']}"
            for o in snap.opportunities[:5]
        ]
        if not opportunities and int(lm.get("hot_leads") or 0):
            opportunities.append(f"{lm['hot_leads']} hot lead(s) require operator review")

        risks = [r["issue"] for r in snap.risks[:5]]
        if not risks and int(lm.get("neglected_leads") or 0):
            risks.append(f"{lm['neglected_leads']} neglected lead(s) need attention")

        recommendations = [
            f"{r['title']}: {r['description']}"
            for r in snap.recommendations[:5]
        ]
        if not recommendations:
            recommendations = [
                "Review CRM pipeline manually",
                "Check unified inbox for unanswered conversations",
                "Review operator task queue",
            ]

        return {
            "summary": summary,
            "opportunities": opportunities or ["Continue nurturing active pipeline"],
            "risks": risks or ["No critical risks flagged"],
            "recommendations": recommendations,
            "source": "heuristic",
        }
