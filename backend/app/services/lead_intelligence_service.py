"""AI Lead Intelligence & Qualification — score and recommend actions (no auto-changes)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.buyer_outreach import BuyerOutreachMessage
from app.models.buyer_recommendation import BuyerRecommendation
from app.models.communication import CommunicationMessage, CommunicationThread
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.product import Product
from app.models.proposal_document import ProposalDocument
from app.schemas.crm import LeadRescoreRequest
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.crm_service import CrmService, _serialize_lead
from app.services.schema_guard import SchemaGuard

logger = logging.getLogger(__name__)

MARKER = "[Lead Intelligence]"

QUALIFICATION_LEVELS = frozenset({"cold", "warm", "hot", "qualified", "opportunity"})
HOT_LEVELS = frozenset({"hot", "qualified", "opportunity"})
QUALIFIED_LEVELS = frozenset({"qualified", "opportunity"})
NEGLECTED_DAYS = 14
NO_ACTIVITY_DAYS = 7

_SCORE_SYSTEM = """\
You qualify B2B export sales leads for an operator CRM.
Return ONLY JSON:
{
  "score": 0-100 integer,
  "level": "cold|warm|hot|qualified|opportunity",
  "strengths": ["..."],
  "risks": ["..."],
  "next_action": "single recommended manual next step",
  "summary": "1-2 sentence lead intelligence summary"
}

Rules:
- Never suggest automatic messaging, status changes, or proposal sending
- Recommend manual operator review actions only
- Use signal data provided — do not invent facts
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp_score(score: int) -> int:
    return max(0, min(100, int(score)))


def _level_from_score(score: int, status: str) -> str:
    if status in ("negotiation", "won"):
        return "opportunity" if score >= 60 else "qualified"
    if status in ("qualified", "proposal_sent") and score >= 55:
        return "qualified" if score < 86 else "opportunity"
    if score >= 86:
        return "opportunity"
    if score >= 66:
        return "qualified"
    if score >= 46:
        return "hot"
    if score >= 26:
        return "warm"
    return "cold"


def _insights_from_parts(
    *,
    score: int,
    level: str,
    strengths: list[str],
    risks: list[str],
    next_action: str,
) -> dict[str, Any]:
    return {
        "score": _clamp_score(score),
        "level": level if level in QUALIFICATION_LEVELS else _level_from_score(score, "new"),
        "strengths": strengths[:6],
        "risks": risks[:6],
        "next_action": next_action[:500],
    }


def _infer_country(lead: CrmLead) -> str | None:
    blob = " ".join(filter(None, [lead.notes, lead.interest, lead.company]))
    for c in (
        "Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan", "Turkmenistan",
        "Russia", "China", "Turkey", "UAE", "Saudi Arabia", "India", "Pakistan",
    ):
        if c.lower() in blob.lower():
            return c
    return None


class LeadIntelligenceService:
    @staticmethod
    async def _collect_signals(db: AsyncSession, lead: CrmLead) -> dict[str, Any]:
        now = _now()

        act_r = await db.execute(
            select(func.count(CrmActivity.id), func.max(CrmActivity.created_at))
            .where(CrmActivity.lead_id == lead.id)
        )
        activity_count, last_activity_at = act_r.one()

        thread_r = await db.execute(
            select(func.count(CommunicationThread.id))
            .where(CommunicationThread.lead_id == lead.id)
        )
        thread_count = thread_r.scalar() or 0

        msg_r = await db.execute(
            select(func.count(CommunicationMessage.id))
            .select_from(CommunicationMessage)
            .join(CommunicationThread, CommunicationMessage.thread_id == CommunicationThread.id)
            .where(CommunicationThread.lead_id == lead.id)
        )
        message_count = msg_r.scalar() or 0

        out_r = await db.execute(
            select(
                func.count(BuyerOutreachMessage.id),
                func.coalesce(func.sum(case((BuyerOutreachMessage.status == "sent", 1), else_=0)), 0),
                func.coalesce(func.sum(case(
                    (BuyerOutreachMessage.status.in_(("draft", "approved")), 1),
                    else_=0,
                )), 0),
            ).where(BuyerOutreachMessage.lead_id == lead.id)
        )
        outreach_total, outreach_sent, outreach_draft = out_r.one()

        prop_r = await db.execute(
            select(
                func.count(ProposalDocument.id),
                func.coalesce(func.sum(case(
                    (ProposalDocument.status.in_(("sent", "accepted", "reviewed")), 1),
                    else_=0,
                )), 0),
            ).where(ProposalDocument.lead_id == lead.id)
        )
        proposal_total, proposal_sent = prop_r.one()

        buyer_rec_count = 0
        country = _infer_country(lead)
        prod_r = await db.execute(
            select(Product.id).where(Product.client_id == lead.client_id, Product.active.is_(True)).limit(20)
        )
        product_ids = [row[0] for row in prod_r.all()]
        if product_ids:
            br_r = await db.execute(
                select(func.count(BuyerRecommendation.id))
                .where(
                    BuyerRecommendation.product_id.in_(product_ids),
                    BuyerRecommendation.score >= 70,
                )
            )
            buyer_rec_count = br_r.scalar() or 0

        days_since_activity = None
        if last_activity_at:
            la = last_activity_at if last_activity_at.tzinfo else last_activity_at.replace(tzinfo=timezone.utc)
            days_since_activity = (now - la).days

        follow_up_overdue = False
        if lead.next_follow_up_at:
            fu = lead.next_follow_up_at if lead.next_follow_up_at.tzinfo else lead.next_follow_up_at.replace(tzinfo=timezone.utc)
            follow_up_overdue = fu < now

        return {
            "activity_count": int(activity_count or 0),
            "last_activity_at": last_activity_at.isoformat() if last_activity_at else None,
            "days_since_activity": days_since_activity,
            "thread_count": int(thread_count),
            "message_count": int(message_count),
            "outreach_total": int(outreach_total or 0),
            "outreach_sent": int(outreach_sent or 0),
            "outreach_draft": int(outreach_draft or 0),
            "proposal_total": int(proposal_total or 0),
            "proposal_sent": int(proposal_sent or 0),
            "buyer_rec_count": int(buyer_rec_count),
            "country": country,
            "follow_up_overdue": follow_up_overdue,
            "status": lead.status,
            "priority": lead.priority,
            "estimated_value": float(lead.estimated_value) if lead.estimated_value else None,
            "interest": (lead.interest or "")[:300],
        }

    @staticmethod
    def _heuristic_insights(lead: CrmLead, signals: dict[str, Any]) -> dict[str, Any]:
        score = 35
        strengths: list[str] = []
        risks: list[str] = []

        if signals["activity_count"] >= 3:
            score += 12
            strengths.append("Multiple CRM activities logged")
        elif signals["activity_count"] >= 1:
            score += 6
            strengths.append("Some CRM engagement recorded")
        else:
            score -= 12
            risks.append("No CRM activities yet")

        if signals["thread_count"] > 0 or signals["message_count"] > 0:
            score += 10
            strengths.append("Communication hub activity present")

        if signals["outreach_sent"] > 0:
            score += 10
            strengths.append("Outreach marked as sent")
        elif signals["outreach_draft"] > 0:
            score += 4
            strengths.append("Outreach drafts prepared")

        if signals["proposal_sent"] > 0:
            score += 15
            strengths.append("Proposal activity in pipeline")
        elif signals["proposal_total"] > 0:
            score += 6
            strengths.append("Proposal draft exists")

        if lead.priority == "high":
            score += 8
            strengths.append("Marked high priority")
        elif lead.priority == "low":
            score -= 4

        if signals["estimated_value"]:
            score += 6
            strengths.append("Estimated deal value captured")

        if signals["country"]:
            score += 3
            strengths.append(f"Target market identified: {signals['country']}")

        if signals["buyer_rec_count"] > 0:
            score += 5
            strengths.append("Buyer Finder shows strong product-market fit")

        if signals["follow_up_overdue"]:
            score -= 10
            risks.append("Follow-up date is overdue")

        days = signals.get("days_since_activity")
        if days is not None and days >= NEGLECTED_DAYS:
            score -= 14
            risks.append(f"No activity for {days} days")
        elif days is not None and days >= NO_ACTIVITY_DAYS:
            score -= 6
            risks.append("Recent engagement is slowing")

        if lead.status in ("qualified", "proposal_sent", "negotiation"):
            score += 10
        elif lead.status == "contacted":
            score += 4
        elif lead.status in ("won",):
            score = max(score, 90)
        elif lead.status == "lost":
            score = min(score, 20)
            risks.append("Lead marked as lost")

        score = _clamp_score(score)
        level = _level_from_score(score, lead.status)

        if level in HOT_LEVELS and not strengths:
            strengths.append("Score indicates active sales potential")

        next_action = "Review lead profile and log the next manual touchpoint."
        if signals["activity_count"] == 0:
            next_action = "Add a CRM activity or prepare first outreach draft — no auto-send."
        elif signals["follow_up_overdue"]:
            next_action = "Complete overdue follow-up manually (call or message draft)."
        elif signals["outreach_draft"] > 0 and signals["outreach_sent"] == 0:
            next_action = "Review outreach draft, approve, and send manually when ready."
        elif signals["proposal_total"] > 0 and signals["proposal_sent"] == 0:
            next_action = "Review proposal draft and send manually after approval."
        elif level in HOT_LEVELS:
            next_action = "Schedule a qualification call and update CRM notes manually."
        elif days is not None and days >= NEGLECTED_DAYS:
            next_action = "Re-engage with a follow-up outreach draft — operator sends manually."

        summary = (
            f"{lead.name}: score {score}/100 ({level}). "
            f"{len(strengths)} strength(s), {len(risks)} risk(s)."
        )

        insights = _insights_from_parts(
            score=score,
            level=level,
            strengths=strengths,
            risks=risks,
            next_action=next_action,
        )
        insights["summary"] = summary
        return insights

    @staticmethod
    async def _ai_insights(lead: CrmLead, signals: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        base = LeadIntelligenceService._heuristic_insights(lead, signals)
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise RuntimeError("demo")
            _validate_api_key()
            openai = get_openai()
            user = (
                f"LEAD: {lead.name} | {lead.company or '—'} | status={lead.status} | priority={lead.priority}\n"
                f"SIGNALS: {signals}\n"
                f"HEURISTIC: score={base['score']} level={base['level']}"
            )
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _SCORE_SYSTEM},
                    {"role": "user", "content": user},
                ],
                temperature=0.3,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            score = _clamp_score(int(parsed.get("score", base["score"])))
            level = str(parsed.get("level") or base["level"])
            if level not in QUALIFICATION_LEVELS:
                level = _level_from_score(score, lead.status)
            strengths = [str(s) for s in (parsed.get("strengths") or base["strengths"]) if str(s).strip()]
            risks = [str(s) for s in (parsed.get("risks") or base["risks"]) if str(s).strip()]
            next_action = str(parsed.get("next_action") or base["next_action"]).strip()
            summary = str(parsed.get("summary") or base.get("summary") or "").strip()
            insights = _insights_from_parts(
                score=score, level=level, strengths=strengths, risks=risks, next_action=next_action,
            )
            insights["summary"] = summary or base.get("summary", "")
            return insights, False
        except Exception as exc:
            logger.info("%s AI fallback: %s", MARKER, exc)
            return base, True

    @staticmethod
    def _attach_insights(lead_data: dict[str, Any]) -> dict[str, Any]:
        score = lead_data.get("lead_score")
        level = lead_data.get("qualification_level")
        if score is not None and level:
            lead_data["lead_insights"] = {
                "score": score,
                "level": level,
                "strengths": [],
                "risks": [],
                "next_action": lead_data.get("recommended_action") or "",
            }
        return lead_data

    @staticmethod
    async def score_lead(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        lead = await CrmService._load_lead(db, lead_id)
        signals = await LeadIntelligenceService._collect_signals(db, lead)
        insights, demo_mode = await LeadIntelligenceService._ai_insights(lead, signals)

        now = _now()
        lead.lead_score = insights["score"]
        lead.qualification_level = insights["level"]
        lead.ai_summary = insights.get("summary") or lead.ai_summary
        lead.recommended_action = insights["next_action"]
        lead.last_scored_at = now
        lead.updated_at = now

        await db.commit()
        available = await SchemaGuard.table_columns(db, "crm_leads")
        lead = await CrmService._load_lead(db, lead_id)
        lead_data = _serialize_lead(lead, available)
        lead_data["lead_insights"] = {
            "score": insights["score"],
            "level": insights["level"],
            "strengths": insights["strengths"],
            "risks": insights["risks"],
            "next_action": insights["next_action"],
        }

        logger.info("%s scored: lead=%s score=%s level=%s", MARKER, lead_id, insights["score"], insights["level"])
        return {
            "lead_id": lead_id,
            "insights": lead_data["lead_insights"],
            "ai_summary": lead.ai_summary,
            "recommended_action": lead.recommended_action,
            "demo_mode": demo_mode,
            "lead": lead_data,
        }

    @staticmethod
    async def rescore_leads(db: AsyncSession, data: LeadRescoreRequest | None = None) -> dict[str, Any]:
        body = data or LeadRescoreRequest()
        query = (
            select(CrmLead.id)
            .where(CrmLead.status.notin_(("won", "lost")))
            .order_by(CrmLead.updated_at.desc())
            .limit(body.limit)
        )
        if body.client_id:
            query = query.where(CrmLead.client_id == body.client_id)

        result = await db.execute(query)
        lead_ids = [row[0] for row in result.all()]
        scored = 0
        failed = 0
        for lid in lead_ids:
            try:
                await LeadIntelligenceService.score_lead(db, lid)
                scored += 1
            except Exception as exc:
                failed += 1
                logger.info("%s rescore skip: lead=%s err=%s", MARKER, lid, exc)

        logger.info("%s bulk rescore: scored=%s failed=%s", MARKER, scored, failed)
        return {
            "scored": scored,
            "failed": failed,
            "message": f"Rescored {scored} lead(s). No status or outreach changes were made.",
        }

    @staticmethod
    async def _is_neglected(db: AsyncSession, lead: CrmLead) -> bool:
        if lead.status in ("won", "lost"):
            return False
        act_r = await db.execute(
            select(func.max(CrmActivity.created_at)).where(CrmActivity.lead_id == lead.id)
        )
        last_act = act_r.scalar_one_or_none()
        ref = last_act or lead.updated_at or lead.created_at
        if not ref:
            return True
        if ref.tzinfo is None:
            ref = ref.replace(tzinfo=timezone.utc)
        return (_now() - ref).days >= NEGLECTED_DAYS

    @staticmethod
    async def _has_no_activity(db: AsyncSession, lead: CrmLead) -> bool:
        act_r = await db.execute(
            select(func.count()).select_from(CrmActivity).where(CrmActivity.lead_id == lead.id)
        )
        return (act_r.scalar() or 0) == 0

    @staticmethod
    async def metrics(db: AsyncSession, *, client_id: UUID | None = None) -> dict[str, Any]:
        query = select(CrmLead).options(selectinload(CrmLead.client))
        if client_id:
            query = query.where(CrmLead.client_id == client_id)
        result = await db.execute(query)
        leads = list(result.scalars().all())

        hot = 0
        qualified = 0
        neglected = 0
        no_activity = 0
        hot_candidates: list[CrmLead] = []

        for lead in leads:
            if lead.status in ("won", "lost"):
                continue
            level = lead.qualification_level
            if level in HOT_LEVELS or (lead.lead_score is not None and lead.lead_score >= 70):
                hot += 1
                hot_candidates.append(lead)
            if level in QUALIFIED_LEVELS:
                qualified += 1
            if await LeadIntelligenceService._is_neglected(db, lead):
                neglected += 1
            if await LeadIntelligenceService._has_no_activity(db, lead):
                no_activity += 1

        hot_candidates.sort(
            key=lambda l: (l.lead_score or 0, l.updated_at or l.created_at),
            reverse=True,
        )
        top_hot = [
            {
                "lead_id": l.id,
                "name": l.name,
                "company": l.company,
                "lead_score": l.lead_score or 0,
                "qualification_level": l.qualification_level or "warm",
                "recommended_action": l.recommended_action,
                "status": l.status,
            }
            for l in hot_candidates[:10]
            if (l.lead_score or 0) >= 46 or l.qualification_level in HOT_LEVELS
        ]

        return {
            "hot_leads": hot,
            "qualified_leads": qualified,
            "neglected_leads": neglected,
            "leads_without_activity": no_activity,
            "top_hot_leads": top_hot,
        }

    @staticmethod
    async def list_hot_leads(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        metrics = await LeadIntelligenceService.metrics(db, client_id=client_id)
        return metrics["top_hot_leads"][:limit]

    @staticmethod
    async def list_neglected_leads(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        query = select(CrmLead).where(CrmLead.status.notin_(("won", "lost")))
        if client_id:
            query = query.where(CrmLead.client_id == client_id)
        result = await db.execute(query.order_by(CrmLead.updated_at.asc()).limit(limit * 3))
        items: list[dict[str, Any]] = []
        for lead in result.scalars().all():
            if await LeadIntelligenceService._is_neglected(db, lead):
                items.append({
                    "lead_id": lead.id,
                    "name": lead.name,
                    "company": lead.company,
                    "lead_score": lead.lead_score,
                    "qualification_level": lead.qualification_level,
                    "status": lead.status,
                    "recommended_action": lead.recommended_action or "Manual re-engagement recommended",
                })
            if len(items) >= limit:
                break
        return items
