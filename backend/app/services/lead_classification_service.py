"""Lead Auto Classification v1 — heuristic lead scoring and categorization (read-only)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.communication import CommunicationMessage, CommunicationThread
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.operator_task import OperatorTask
from app.models.proposal_document import ProposalDocument
from app.models.sales_assistant_recommendation import SalesAssistantRecommendation
from app.services.crm_service import CrmService, _serialize_lead
from app.services.operator_task_service import TERMINAL_STATUSES
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.schema_guard import SchemaGuard

logger = logging.getLogger(__name__)

MARKER = "[Lead Classification]"

CLASSIFICATIONS = frozenset({"hot", "qualified", "nurturing", "cold", "inactive"})
HOT_CLASSIFICATIONS = frozenset({"hot", "qualified"})
ACTIVE_CLASSIFICATIONS = frozenset({"hot", "qualified", "nurturing"})

_INACTIVE_DAYS = 30
_COLD_DAYS = 21
_STALE_DAYS = 14
_RECENT_DAYS = 7


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _clamp_score(score: int) -> int:
    return max(0, min(100, int(score)))


def _days_since(ref: datetime | None, now: datetime) -> int | None:
    ref = _aware(ref)
    if ref is None:
        return None
    return (now - ref).days


class LeadClassificationService:
    @staticmethod
    async def _collect_signals(db: AsyncSession, lead: CrmLead) -> dict[str, Any]:
        now = _now()
        lead_id = lead.id

        act_r = await db.execute(
            select(func.count(CrmActivity.id), func.max(CrmActivity.created_at))
            .where(CrmActivity.lead_id == lead_id)
        )
        activity_count, last_activity_at = act_r.one()

        thread_r = await db.execute(
            select(func.count(CommunicationThread.id), func.max(CommunicationThread.updated_at))
            .where(CommunicationThread.lead_id == lead_id)
        )
        thread_count, last_thread_at = thread_r.one()

        msg_r = await db.execute(
            select(
                func.count(CommunicationMessage.id),
                func.max(CommunicationMessage.created_at),
                func.coalesce(func.sum(case(
                    (CommunicationMessage.direction == "inbound", 1),
                    else_=0,
                )), 0),
            )
            .select_from(CommunicationMessage)
            .join(CommunicationThread, CommunicationMessage.thread_id == CommunicationThread.id)
            .where(CommunicationThread.lead_id == lead_id)
        )
        message_count, last_message_at, inbound_count = msg_r.one()

        prop_r = await db.execute(
            select(
                func.count(ProposalDocument.id),
                func.coalesce(func.sum(case(
                    (ProposalDocument.status.in_(("sent", "accepted", "reviewed")), 1),
                    else_=0,
                )), 0),
                func.coalesce(func.sum(case(
                    (ProposalDocument.status == "draft", 1),
                    else_=0,
                )), 0),
                func.max(ProposalDocument.updated_at),
            ).where(ProposalDocument.lead_id == lead_id)
        )
        proposal_total, proposal_sent, proposal_draft, last_proposal_at = prop_r.one()

        task_r = await db.execute(
            select(
                func.count(OperatorTask.id),
                func.coalesce(func.sum(case(
                    (OperatorTask.status.notin_(tuple(TERMINAL_STATUSES)), 1),
                    else_=0,
                )), 0),
                func.coalesce(func.sum(case(
                    (OperatorTask.status.in_(("completed", "done")), 1),
                    else_=0,
                )), 0),
                func.max(OperatorTask.updated_at),
            ).where(OperatorTask.lead_id == lead_id)
        )
        task_total, open_tasks, completed_tasks, last_task_at = task_r.one()

        rec_r = await db.execute(
            select(func.count(SalesAssistantRecommendation.id))
            .where(
                SalesAssistantRecommendation.lead_id == lead_id,
                SalesAssistantRecommendation.status == "open",
            )
        )
        open_recommendations = rec_r.scalar() or 0

        touch_refs = [
            _aware(last_activity_at),
            _aware(last_thread_at),
            _aware(last_message_at),
            _aware(last_proposal_at),
            _aware(last_task_at),
            _aware(lead.updated_at),
        ]
        touch_refs = [t for t in touch_refs if t is not None]
        last_contact_at = max(touch_refs) if touch_refs else _aware(lead.created_at)
        days_since_contact = _days_since(last_contact_at, now)

        follow_up_overdue = False
        if lead.next_follow_up_at:
            fu = _aware(lead.next_follow_up_at)
            follow_up_overdue = fu is not None and fu < now

        follow_up_completed = bool(
            activity_count
            and last_activity_at
            and _days_since(last_activity_at, now) is not None
            and _days_since(last_activity_at, now) <= _RECENT_DAYS
        )

        crm_fields_filled = sum(
            1 for v in (lead.company, lead.phone, lead.email, lead.interest, lead.estimated_value)
            if v not in (None, "")
        )

        return {
            "has_scheduled_follow_up": lead.next_follow_up_at is not None,
            "activity_count": int(activity_count or 0),
            "last_activity_at": last_activity_at,
            "thread_count": int(thread_count or 0),
            "message_count": int(message_count or 0),
            "inbound_count": int(inbound_count or 0),
            "last_message_at": last_message_at,
            "proposal_total": int(proposal_total or 0),
            "proposal_sent": int(proposal_sent or 0),
            "proposal_draft": int(proposal_draft or 0),
            "last_proposal_at": last_proposal_at,
            "open_tasks": int(open_tasks or 0),
            "completed_tasks": int(completed_tasks or 0),
            "task_total": int(task_total or 0),
            "open_recommendations": int(open_recommendations or 0),
            "last_contact_at": last_contact_at,
            "days_since_contact": days_since_contact,
            "follow_up_overdue": follow_up_overdue,
            "follow_up_completed": follow_up_completed,
            "crm_fields_filled": crm_fields_filled,
            "status": lead.status,
            "priority": lead.priority,
        }

    @staticmethod
    def _compute_score(signals: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        reasons: list[str] = []

        # Recent communication (max 25)
        comm_score = 0
        if signals["inbound_count"] > 0 and signals["days_since_contact"] is not None:
            if signals["days_since_contact"] <= 3:
                comm_score = 25
                reasons.append("active conversation")
            elif signals["days_since_contact"] <= _RECENT_DAYS:
                comm_score = 18
                reasons.append("recent communication")
            elif signals["days_since_contact"] <= _STALE_DAYS:
                comm_score = 10
        elif signals["message_count"] > 0:
            comm_score = 8
            reasons.append("inbox activity present")
        elif signals["activity_count"] > 0:
            comm_score = 6
        score += comm_score

        # Proposal activity (max 25)
        if signals["proposal_sent"] > 0:
            score += 25
            reasons.append("proposal sent")
        elif signals["proposal_draft"] > 0:
            score += 14
            reasons.append("proposal in progress")
        elif signals["proposal_total"] > 0:
            score += 8

        # Follow-up activity (max 20)
        if signals["follow_up_completed"]:
            score += 12
            reasons.append("follow-up completed")
        if signals["follow_up_overdue"]:
            score -= 8
        elif signals.get("has_scheduled_follow_up"):
            score += 8
            reasons.append("follow-up scheduled")

        # Operator engagement (max 15)
        if signals["open_tasks"] > 0:
            score += 10
            reasons.append("operator tasks open")
        if signals["completed_tasks"] > 0:
            score += 5
        if signals["open_recommendations"] > 0:
            score += 4
            reasons.append("sales assistant flagged")

        # CRM completeness (max 15)
        filled = signals["crm_fields_filled"]
        score += min(15, filled * 3)
        if filled >= 4:
            reasons.append("complete CRM profile")

        if signals["priority"] == "high":
            score += 5
        elif signals["priority"] == "low":
            score -= 3

        if signals["status"] in ("qualified", "proposal_sent", "negotiation"):
            score += 8
        elif signals["status"] == "contacted":
            score += 4
        elif signals["status"] == "lost":
            score = min(score, 15)
        elif signals["status"] == "won":
            score = max(score, 85)

        days = signals.get("days_since_contact")
        if days is not None:
            if days >= _INACTIVE_DAYS:
                score -= 20
            elif days >= _COLD_DAYS:
                score -= 12
            elif days >= _STALE_DAYS:
                score -= 6

        return _clamp_score(score), reasons[:8]

    @staticmethod
    def _classification_from_score(score: int, signals: dict[str, Any]) -> str:
        status = signals["status"]
        days = signals.get("days_since_contact")

        if status in ("won",):
            return "hot"
        if status == "lost":
            return "inactive"
        if days is not None and days >= _INACTIVE_DAYS and score < 25:
            return "inactive"
        if days is not None and days >= _INACTIVE_DAYS and signals["activity_count"] == 0:
            return "inactive"

        if score >= 76 or (
            score >= 66
            and signals["inbound_count"] > 0
            and signals["days_since_contact"] is not None
            and signals["days_since_contact"] <= _RECENT_DAYS
        ):
            return "hot"
        if score >= 56 or status in ("qualified", "proposal_sent", "negotiation"):
            return "qualified"
        if score >= 30 or status in ("contacted", "new"):
            if days is not None and days >= _COLD_DAYS and score < 40:
                return "cold"
            return "nurturing"
        if days is not None and days >= _COLD_DAYS:
            return "cold"
        return "cold" if score < 30 else "nurturing"

    @staticmethod
    def _build_recommendations(
        classification: str,
        score: int,
        signals: dict[str, Any],
        reasons: list[str],
    ) -> dict[str, Any]:
        urgency = "medium"
        if classification == "hot" or signals["follow_up_overdue"]:
            urgency = "urgent"
        elif classification == "qualified":
            urgency = "high"
        elif classification == "cold":
            urgency = "low"
        elif classification == "inactive":
            urgency = "low"

        next_action = "Review lead profile and plan the next manual touchpoint."
        follow_up_rec: str | None = None
        proposal_rec: str | None = None

        if signals["follow_up_overdue"]:
            next_action = "Complete overdue follow-up manually — no auto-messaging."
            follow_up_rec = "Follow-up date passed; schedule a call or draft a message for manual send."
            urgency = "urgent"
        elif classification == "hot" and signals["proposal_sent"] == 0:
            next_action = "Review hot lead and prepare proposal manually after operator approval."
            proposal_rec = "Hot lead with no sent proposal — create and review proposal draft."
        elif classification == "hot":
            next_action = "Maintain momentum — log CRM activity after each manual touchpoint."
        elif classification == "qualified" and signals["proposal_draft"] > 0:
            next_action = "Review proposal draft and send manually when approved."
            proposal_rec = "Proposal draft ready for operator review."
        elif classification == "qualified":
            next_action = "Schedule qualification call and update CRM notes manually."
        elif classification == "nurturing" and not signals.get("has_scheduled_follow_up"):
            next_action = "Set next follow-up date or create operator task."
            follow_up_rec = "Lead is nurturing — schedule a follow-up to stay engaged."
        elif classification == "cold":
            next_action = "Re-engage with a manual outreach draft — operator sends when ready."
            follow_up_rec = "Lead cooling — plan a re-engagement touchpoint."
        elif classification == "inactive":
            next_action = "Review whether to archive or run a one-time re-engagement campaign."
            follow_up_rec = "Long inactivity — confirm lead status before further effort."

        if "proposal requested" in reasons or (
            classification in HOT_CLASSIFICATIONS and signals["proposal_total"] == 0
        ):
            proposal_rec = proposal_rec or "Consider creating a proposal draft for operator review."

        return {
            "next_recommended_action": next_action[:500],
            "follow_up_recommendation": follow_up_rec,
            "proposal_recommendation": proposal_rec,
            "urgency_level": urgency,
        }

    @staticmethod
    async def classify_lead(db: AsyncSession, lead: CrmLead) -> dict[str, Any]:
        signals = await LeadClassificationService._collect_signals(db, lead)
        score, reasons = LeadClassificationService._compute_score(signals)
        classification = LeadClassificationService._classification_from_score(score, signals)

        if signals["inbound_count"] > 0 and signals["days_since_contact"] is not None:
            if signals["days_since_contact"] <= 3 and "active conversation" not in reasons:
                reasons.insert(0, "active conversation")
        if signals["proposal_draft"] > 0 and "proposal requested" not in reasons:
            reasons.append("proposal requested")

        comm_score = None
        comm_score = await CommunicationIntelligenceService.get_lead_communication_score(db, lead.id)
        if comm_score:
            cs = int(comm_score.get("health_score") or 0)
            if cs >= 70:
                score = _clamp_score(score + 8)
                if "strong communication health" not in reasons:
                    reasons.append("strong communication health")
            elif cs >= 50:
                score = _clamp_score(score + 4)
            elif cs < 30:
                score = _clamp_score(score - 6)
                if "weak communication health" not in reasons:
                    reasons.append("weak communication health")
            classification = LeadClassificationService._classification_from_score(score, signals)

        recommendations = LeadClassificationService._build_recommendations(
            classification, score, signals, reasons,
        )

        return {
            "classification": classification,
            "score": score,
            "reasons": reasons,
            "recommendations": recommendations,
            "last_activity_at": signals["last_contact_at"],
            "signals": signals,
            "communication_score": comm_score,
        }

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        counts = {k: 0 for k in ("hot", "qualified", "nurturing", "cold", "inactive")}

        async def _classify_all() -> int:
            q = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
            if client_id:
                q = q.where(CrmLead.client_id == client_id)
            result = await db.execute(q)
            leads = list(result.scalars().all())
            for lead in leads:
                try:
                    item = await LeadClassificationService.classify_lead(db, lead)
                    cls = item["classification"]
                    if cls in counts:
                        counts[cls] += 1
                except Exception as exc:
                    logger.info("%s classify skip: lead=%s err=%s", MARKER, lead.id, exc)
            return len(leads)

        total = await safe_section(
            "lead_classification_overview",
            _classify_all(),
            default=0,
            errors=errors,
            db=db,
        )

        return {
            "hot_leads": counts["hot"],
            "qualified_leads": counts["qualified"],
            "nurturing_leads": counts["nurturing"],
            "cold_leads": counts["cold"],
            "inactive_leads": counts["inactive"],
            "total_classified": total,
            "errors": errors,
        }

    @staticmethod
    async def list_leads(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        classification: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        activity: str = "all",
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
        if client_id:
            q = q.where(CrmLead.client_id == client_id)
        result = await db.execute(q.order_by(CrmLead.updated_at.desc()))
        all_leads = list(result.scalars().all())

        items: list[dict[str, Any]] = []
        for lead in all_leads:
            try:
                item = await LeadClassificationService.classify_lead(db, lead)
            except Exception as exc:
                logger.info("%s list skip: lead=%s err=%s", MARKER, lead.id, exc)
                continue

            cls = item["classification"]
            score = item["score"]
            days = item["signals"].get("days_since_contact")

            if classification and cls != classification:
                continue
            if min_score is not None and score < min_score:
                continue
            if max_score is not None and score > max_score:
                continue
            if activity == "active" and cls not in ACTIVE_CLASSIFICATIONS:
                continue
            if activity == "stale" and cls not in ("cold", "nurturing"):
                continue
            if activity == "inactive" and cls != "inactive":
                continue

            items.append({
                "lead_id": lead.id,
                "name": lead.name,
                "company": lead.company,
                "score": score,
                "classification": cls,
                "last_activity_at": item["last_activity_at"],
                "recommended_action": item["recommendations"]["next_recommended_action"],
                "status": lead.status,
                "client_id": lead.client_id,
            })

        items.sort(key=lambda x: (x["score"], x["last_activity_at"] or _now()), reverse=True)
        total = len(items)
        page = items[skip: skip + limit]
        return {"items": page, "total": total}

    @staticmethod
    async def lead_detail(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        lead = await CrmService._load_lead(db, lead_id)
        item = await LeadClassificationService.classify_lead(db, lead)

        threads_r = await db.execute(
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .where(CommunicationThread.lead_id == lead_id)
            .order_by(CommunicationThread.updated_at.desc())
        )
        linked_threads = []
        for thread in threads_r.scalars().all():
            linked_threads.append({
                "thread_id": thread.id,
                "channel": thread.channel,
                "title": thread.title,
                "status": thread.status,
                "message_count": len(thread.messages or []),
            })

        props_r = await db.execute(
            select(ProposalDocument)
            .where(ProposalDocument.lead_id == lead_id)
            .order_by(ProposalDocument.updated_at.desc())
        )
        linked_proposals = [
            {
                "proposal_id": p.id,
                "title": p.title,
                "status": p.status,
                "updated_at": p.updated_at,
            }
            for p in props_r.scalars().all()
        ]

        available = await SchemaGuard.table_columns(db, "crm_leads")
        linked_crm = _serialize_lead(lead, available)

        return {
            "lead_id": lead.id,
            "name": lead.name,
            "company": lead.company,
            "status": lead.status,
            "client_id": lead.client_id,
            "classification": item["classification"],
            "score": item["score"],
            "reasons": item["reasons"],
            "recommendations": item["recommendations"],
            "linked_crm": linked_crm,
            "linked_threads": linked_threads,
            "linked_proposals": linked_proposals,
            "last_activity_at": item["last_activity_at"],
        }

    @staticmethod
    async def classify_batch(
        db: AsyncSession,
        *,
        lead_ids: list[UUID] | None = None,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        if lead_ids:
            q = select(CrmLead).where(CrmLead.id.in_(lead_ids))
        else:
            q = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
            if client_id:
                q = q.where(CrmLead.client_id == client_id)
            q = q.limit(100)

        result = await db.execute(q)
        leads = list(result.scalars().all())
        items: list[dict[str, Any]] = []
        for lead in leads:
            try:
                items.append(await LeadClassificationService.lead_detail(db, lead.id))
            except Exception as exc:
                logger.info("%s classify batch skip: lead=%s err=%s", MARKER, lead.id, exc)

        logger.info("%s classify batch: count=%s", MARKER, len(items))
        return {"items": items, "classified": len(items)}

    @staticmethod
    async def recalculate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        q = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
        if client_id:
            q = q.where(CrmLead.client_id == client_id)
        q = q.order_by(CrmLead.updated_at.desc()).limit(limit)
        result = await db.execute(q)
        leads = list(result.scalars().all())

        classified = 0
        for lead in leads:
            try:
                await LeadClassificationService.classify_lead(db, lead)
                classified += 1
            except Exception as exc:
                logger.info("%s recalculate skip: lead=%s err=%s", MARKER, lead.id, exc)

        overview = await LeadClassificationService.overview(db, client_id=client_id)
        logger.info("%s recalculate: classified=%s", MARKER, classified)
        return {
            "classified": classified,
            "overview": overview,
            "message": f"Recalculated {classified} lead(s). No CRM changes were made.",
        }

    @staticmethod
    async def classify_leads_map(
        db: AsyncSession,
        lead_ids: list[UUID],
    ) -> dict[str, dict[str, Any]]:
        if not lead_ids:
            return {}
        result = await db.execute(select(CrmLead).where(CrmLead.id.in_(lead_ids)))
        out: dict[str, dict[str, Any]] = {}
        for lead in result.scalars().all():
            try:
                item = await LeadClassificationService.classify_lead(db, lead)
                out[str(lead.id)] = {
                    "classification": item["classification"],
                    "score": item["score"],
                    "reasons": item["reasons"][:3],
                    "urgency_level": item["recommendations"]["urgency_level"],
                }
            except Exception:
                pass
        return out

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await LeadClassificationService.overview(db, client_id=client_id)
        return {
            "hot_leads": overview["hot_leads"],
            "qualified_leads": overview["qualified_leads"],
            "nurturing_leads": overview["nurturing_leads"],
            "cold_leads": overview["cold_leads"],
            "inactive_leads": overview["inactive_leads"],
            "total_classified": overview["total_classified"],
        }
