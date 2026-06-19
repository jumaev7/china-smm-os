"""Deal Risk Engine v2 — heuristic deal health, risk classification, close probability (read-only)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.communication import CommunicationMessage, CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.operator_task import OperatorTask
from app.models.proposal_document import ProposalDocument
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.crm_service import CrmService
from app.services.lead_classification_service import LeadClassificationService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Deal Risk]"

RISK_LEVELS = frozenset({
    "healthy",
    "watchlist",
    "at_risk",
    "critical",
    "stalled",
    "lost_probability_high",
})

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})

_INACTIVE_DAYS = 30
_STALE_DAYS = 14
_RECENT_DAYS = 7
_STALL_DAYS = 21
_PROPOSAL_STALE_DAYS = 14
_HIGH_CLOSE_PROB = 70

_STAGE_DURATION_WARN: dict[str, int] = {
    "new": 14,
    "proposal": 21,
    "contract": 30,
    "invoice": 21,
    "waiting_payment": 14,
}


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


def _decimal(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (TypeError, ValueError):
        return Decimal("0")


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"))


def _deal_revenue(deal: CrmDeal) -> Decimal:
    val = _decimal(deal.expected_value)
    if val > 0:
        return val
    return _decimal(deal.deal_amount)


class DealRiskService:
    """Evaluates CRM deals — health score, risk level, close probability, recommendations only."""

    @staticmethod
    def _safety_notice() -> str:
        return (
            "Read-only intelligence — no automatic messaging, CRM updates, deal stage updates, or task execution."
        )

    @staticmethod
    async def _load_deals(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        client_ids: list[UUID] | None = None,
        include_closed: bool = False,
    ) -> list[CrmDeal]:
        q = select(CrmDeal).options(selectinload(CrmDeal.lead))
        if not include_closed:
            q = q.where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)))
        if client_id:
            q = q.where(CrmDeal.client_id == client_id)
        elif client_ids is not None:
            if not client_ids:
                return []
            q = q.where(CrmDeal.client_id.in_(client_ids))
        result = await db.execute(q.order_by(CrmDeal.updated_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def _collect_signals(db: AsyncSession, deal: CrmDeal, lead: CrmLead) -> dict[str, Any]:
        now = _now()
        base = await LeadClassificationService._collect_signals(db, lead)
        deal_id = deal.id
        lead_id = lead.id

        props_r = await db.execute(
            select(
                func.count(ProposalDocument.id),
                func.coalesce(func.sum(
                    case((ProposalDocument.status == "sent", 1), else_=0),
                ), 0),
                func.coalesce(func.sum(
                    case((ProposalDocument.status == "draft", 1), else_=0),
                ), 0),
                func.max(ProposalDocument.updated_at),
            ).where(
                or_(
                    ProposalDocument.lead_id == lead_id,
                    ProposalDocument.deal_id == deal_id,
                ),
            ),
        )
        prop_total, prop_sent, prop_draft, last_prop_at = props_r.one()

        tasks_r = await db.execute(
            select(OperatorTask).where(
                or_(OperatorTask.deal_id == deal_id, OperatorTask.lead_id == lead_id),
                OperatorTask.status.notin_(("completed", "dismissed")),
            ),
        )
        open_tasks = list(tasks_r.scalars().all())
        overdue_tasks = 0
        completed_recent = 0
        for t in open_tasks:
            due = _aware(t.due_at)
            if due and due < now:
                overdue_tasks += 1
        done_r = await db.execute(
            select(func.count(OperatorTask.id)).where(
                or_(OperatorTask.deal_id == deal_id, OperatorTask.lead_id == lead_id),
                OperatorTask.status == "completed",
            ),
        )
        completed_recent = int(done_r.scalar() or 0)

        outbound_r = await db.execute(
            select(func.coalesce(func.sum(
                case((CommunicationMessage.direction == "outbound", 1), else_=0),
            ), 0))
            .select_from(CommunicationMessage)
            .join(CommunicationThread, CommunicationMessage.thread_id == CommunicationThread.id)
            .where(CommunicationThread.lead_id == lead_id),
        )
        outbound_count = int(outbound_r.scalar() or 0)
        inbound = int(base.get("inbound_count") or 0)
        response_ratio = min(1.0, inbound / max(outbound_count, 1)) if outbound_count > 0 else (
            0.5 if inbound > 0 else 0.0
        )

        days_in_stage = (_now() - _aware(deal.updated_at)).days if deal.updated_at else 0
        stage_limit = _STAGE_DURATION_WARN.get(deal.status or "new", 21)
        stage_stalled = days_in_stage >= stage_limit

        proposal_aging = False
        if last_prop_at and int(prop_sent or 0) == 0:
            days_prop = (_now() - _aware(last_prop_at)).days if _aware(last_prop_at) else 999
            proposal_aging = days_prop >= _PROPOSAL_STALE_DAYS

        buyer_score = 50
        buyer_risk = "medium"
        try:
            buyer_ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
            buyer_score = int(buyer_ev.get("buyer_score") or 50)
            buyer_risk = str(buyer_ev.get("risk_level") or "medium")
        except Exception as exc:
            logger.info("%s buyer intel skip deal=%s err=%s", MARKER, deal.id, exc)

        comm_health = 50
        try:
            comm = await CommunicationIntelligenceService.get_lead_communication_score(db, lead_id)
            if comm:
                comm_health = int(comm.get("health_score") or 50)
        except Exception as exc:
            logger.info("%s comm intel skip deal=%s err=%s", MARKER, deal.id, exc)

        notes_blob = " ".join(filter(None, [lead.notes, lead.interest, lead.company])).lower()
        missing_decision_maker = not any(
            k in notes_blob for k in ("ceo", "director", "decision", "owner", "manager", "директор", "руковод")
        ) and lead.qualification_level not in ("qualified", "hot", "opportunity")

        declining_comm = False
        days_contact = base.get("days_since_contact")
        if days_contact is not None and days_contact >= _STALE_DAYS:
            if inbound == 0 or (outbound_count > 0 and response_ratio < 0.3):
                declining_comm = True

        low_engagement = inbound == 0 and outbound_count <= 1 and int(base.get("message_count") or 0) <= 1

        forecast_confidence = "medium"
        if buyer_score >= 70 and comm_health >= 60 and not overdue_tasks:
            forecast_confidence = "high"
        elif buyer_score < 40 or comm_health < 35 or overdue_tasks >= 2:
            forecast_confidence = "low"

        return {
            **base,
            "deal_status": deal.status,
            "deal_probability": int(deal.probability or 10),
            "days_in_stage": days_in_stage,
            "stage_stalled": stage_stalled,
            "proposal_total": int(prop_total or 0),
            "proposal_sent": int(prop_sent or 0),
            "proposal_draft": int(prop_draft or 0),
            "last_proposal_at": last_prop_at,
            "proposal_aging": proposal_aging,
            "open_tasks": len(open_tasks),
            "overdue_tasks": overdue_tasks,
            "completed_tasks": completed_recent,
            "outbound_count": outbound_count,
            "response_ratio": response_ratio,
            "buyer_score": buyer_score,
            "buyer_risk": buyer_risk,
            "comm_health": comm_health,
            "missing_decision_maker": missing_decision_maker,
            "declining_communication": declining_comm,
            "low_engagement": low_engagement,
            "forecast_confidence": forecast_confidence,
            "expected_close_date": deal.expected_close_date,
            "revenue": _deal_revenue(deal),
        }

    @staticmethod
    def _detect_risks(signals: dict[str, Any]) -> list[str]:
        risks: list[str] = []
        days = signals.get("days_since_contact")
        if days is not None and days >= _STALE_DAYS and signals.get("inbound_count", 0) == 0:
            risks.append("no_buyer_response")
        if signals.get("proposal_aging"):
            risks.append("proposal_aging")
        if signals.get("follow_up_overdue") or signals.get("overdue_tasks", 0) > 0:
            risks.append("overdue_follow_up")
        if signals.get("stage_stalled") or signals.get("deal_status") == "negotiation":
            if signals.get("days_in_stage", 0) >= _STALL_DAYS:
                risks.append("stalled_negotiations")
        if signals.get("declining_communication"):
            risks.append("declining_communication")
        if signals.get("missing_decision_maker") and signals.get("proposal_sent", 0) > 0:
            risks.append("missing_decision_maker")
        if signals.get("low_engagement"):
            risks.append("low_engagement")
        return risks

    @staticmethod
    def _compute_health_score(signals: dict[str, Any], risks: list[str]) -> tuple[int, list[str]]:
        score = 0
        factors: list[str] = []

        comm = 0
        days = signals.get("days_since_contact")
        if days is not None and days <= _RECENT_DAYS and signals.get("inbound_count", 0) > 0:
            comm = 18
            factors.append("Strong recent communication activity")
        elif days is not None and days <= _STALE_DAYS:
            comm = 12
            factors.append("Moderate communication activity")
        elif signals.get("message_count", 0) > 0:
            comm = 6
        score += comm

        buyer = signals.get("buyer_score") or 50
        if buyer >= 70:
            score += 18
            factors.append("Strong buyer intelligence score")
        elif buyer >= 50:
            score += 12
        elif buyer >= 35:
            score += 6
        else:
            score += 2
            factors.append("Weak buyer intelligence score")

        if signals.get("proposal_sent", 0) > 0:
            score += 15
            factors.append("Proposal activity recorded")
        elif signals.get("proposal_draft", 0) > 0:
            score += 9
        elif signals.get("proposal_total", 0) > 0:
            score += 4

        tasks_open = signals.get("open_tasks") or 0
        overdue = signals.get("overdue_tasks") or 0
        if tasks_open > 0 and overdue == 0:
            score += 10
            factors.append("Open tasks on track")
        elif overdue == 0:
            score += 5
        else:
            score -= min(15, overdue * 5)
            factors.append("Overdue operator tasks")

        days_stage = signals.get("days_in_stage") or 0
        limit = _STAGE_DURATION_WARN.get(signals.get("deal_status") or "new", 21)
        if days_stage <= limit // 2:
            score += 12
        elif days_stage <= limit:
            score += 7
        else:
            score -= min(20, (days_stage - limit) * 2)
            factors.append("Extended time in current stage")

        ratio = signals.get("response_ratio") or 0
        if ratio >= 0.7 and signals.get("inbound_count", 0) >= 2:
            score += 12
            factors.append("High response frequency")
        elif ratio >= 0.4:
            score += 7
        elif signals.get("inbound_count", 0) > 0:
            score += 4

        fc = signals.get("forecast_confidence") or "medium"
        if fc == "high":
            score += 10
            factors.append("High revenue forecast confidence")
        elif fc == "medium":
            score += 5
        else:
            score -= 5
            factors.append("Low revenue forecast confidence")

        comm_h = signals.get("comm_health") or 50
        if comm_h >= 70:
            score += 5
        elif comm_h < 30:
            score -= 8

        for risk in risks:
            if risk == "no_buyer_response":
                score -= 12
            elif risk == "proposal_aging":
                score -= 8
            elif risk == "overdue_follow_up":
                score -= 10
            elif risk == "stalled_negotiations":
                score -= 15
            elif risk == "declining_communication":
                score -= 10
            elif risk == "missing_decision_maker":
                score -= 6
            elif risk == "low_engagement":
                score -= 8

        prob = signals.get("deal_probability") or 10
        score = int(score * 0.85 + prob * 0.15)

        return _clamp_score(score), factors[:8]

    @staticmethod
    def _classify_risk(
        health: int,
        risks: list[str],
        signals: dict[str, Any],
    ) -> str:
        if signals.get("deal_status") == "lost" or health <= 15:
            return "lost_probability_high"
        if "stalled_negotiations" in risks and health < 45:
            return "stalled"
        if health < 25 or (len(risks) >= 4 and health < 40):
            return "critical"
        if health < 40 or len(risks) >= 3:
            return "at_risk"
        if health < 55 or len(risks) >= 2:
            return "watchlist"
        if "stalled_negotiations" in risks:
            return "stalled"
        if health >= 70 and len(risks) == 0:
            return "healthy"
        if health >= 60 and len(risks) <= 1:
            return "healthy"
        return "watchlist"

    @staticmethod
    def _close_probability(health: int, signals: dict[str, Any], risk_level: str) -> float:
        base = float(signals.get("deal_probability") or 10)
        buyer = float(signals.get("buyer_score") or 50)
        blended = base * 0.4 + health * 0.35 + buyer * 0.25

        penalties = {
            "healthy": 0,
            "watchlist": -5,
            "at_risk": -15,
            "critical": -30,
            "stalled": -20,
            "lost_probability_high": -45,
        }
        prob = blended + penalties.get(risk_level, 0)

        if signals.get("proposal_sent", 0) > 0:
            prob += 8
        if signals.get("overdue_tasks", 0) > 0:
            prob -= signals["overdue_tasks"] * 3

        return round(max(0.0, min(100.0, prob)), 1)

    @staticmethod
    def _expected_close_date(
        deal: CrmDeal,
        signals: dict[str, Any],
        close_prob: float,
    ) -> datetime | None:
        if deal.expected_close_date:
            return _aware(deal.expected_close_date)
        if close_prob < 25:
            return None
        now = _now()
        days = 45
        if close_prob >= 80:
            days = 14
        elif close_prob >= 60:
            days = 30
        elif close_prob >= 40:
            days = 60
        if signals.get("stage_stalled"):
            days += 21
        return now + timedelta(days=days)

    @staticmethod
    def _confidence_level(signals: dict[str, Any], risks: list[str]) -> str:
        fc = signals.get("forecast_confidence") or "medium"
        if len(risks) >= 3:
            return "low"
        if fc == "high" and len(risks) <= 1:
            return "high"
        if fc == "low" or len(risks) >= 2:
            return "low"
        return "medium"

    @staticmethod
    def _recommendations(risk_level: str, risks: list[str], signals: dict[str, Any]) -> list[str]:
        recs: list[str] = []
        if "no_buyer_response" in risks:
            recs.append("Schedule manual follow-up — verify buyer availability before further investment.")
        if "proposal_aging" in risks:
            recs.append("Review proposal status manually — confirm buyer received and understood terms.")
        if "overdue_follow_up" in risks:
            recs.append("Complete overdue follow-up tasks — no automatic messaging.")
        if "stalled_negotiations" in risks:
            recs.append("Escalate stalled deal to sales manager for negotiation strategy review.")
        if "declining_communication" in risks:
            recs.append("Re-engage buyer via preferred channel — manual outreach only.")
        if "missing_decision_maker" in risks:
            recs.append("Identify decision maker — update CRM notes before next proposal revision.")
        if "low_engagement" in risks:
            recs.append("Increase engagement touchpoints manually — avoid bulk automated outreach.")

        if risk_level == "critical":
            recs.append("Executive review recommended — assess continue vs. archive decision.")
        elif risk_level == "at_risk":
            recs.append("Assign operator task for deal recovery plan — manual execution only.")
        elif risk_level == "healthy" and signals.get("close_probability", 0) >= _HIGH_CLOSE_PROB:
            recs.append("Prepare closing checklist — coordinate proposal and contract manually.")
        elif risk_level == "watchlist":
            recs.append("Monitor weekly — log CRM activity after each buyer touchpoint.")

        if not recs:
            recs.append("Maintain deal momentum with scheduled manual check-ins.")
        return recs[:6]

    @staticmethod
    async def evaluate_deal(db: AsyncSession, deal: CrmDeal) -> dict[str, Any]:
        lead = deal.lead
        if not lead:
            result = await db.execute(select(CrmLead).where(CrmLead.id == deal.lead_id))
            lead = result.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found for deal")

        signals = await DealRiskService._collect_signals(db, deal, lead)
        risks = DealRiskService._detect_risks(signals)
        health, factors = DealRiskService._compute_health_score(signals, risks)
        risk_level = DealRiskService._classify_risk(health, risks, signals)
        close_prob = DealRiskService._close_probability(health, signals, risk_level)
        expected_close = DealRiskService._expected_close_date(deal, signals, close_prob)
        confidence = DealRiskService._confidence_level(signals, risks)
        recommendations = DealRiskService._recommendations(risk_level, risks, signals)

        risk_labels = [r.replace("_", " ") for r in risks]

        return {
            "deal_health_score": health,
            "risk_level": risk_level,
            "close_probability": close_prob,
            "expected_close_date": expected_close,
            "confidence_level": confidence,
            "risk_reasons": risk_labels,
            "recommendations": recommendations,
            "risk_factors": factors,
            "signals": signals,
            "buyer_name": lead.name,
            "buyer_company": lead.company,
            "lead_id": lead.id,
            "revenue": signals.get("revenue") or Decimal("0"),
            "last_activity_at": signals.get("last_contact_at") or deal.updated_at,
        }

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_id, client_ids = await TenantService.resolve_tenant_client_scope(
            db, tenant_id=tenant_id, client_id=client_id,
        )
        errors: list[str] = []
        counts = {k: 0 for k in RISK_LEVELS}
        high_close = 0
        scores: list[int] = []
        at_risk_revenue = Decimal("0")

        async def _eval_all() -> int:
            nonlocal high_close, at_risk_revenue
            deals = await DealRiskService._load_deals(
                db, client_id=client_id, client_ids=client_ids,
            )
            for deal in deals:
                try:
                    ev = await DealRiskService.evaluate_deal(db, deal)
                    rl = ev["risk_level"]
                    if rl in counts:
                        counts[rl] += 1
                    scores.append(ev["deal_health_score"])
                    if ev["close_probability"] >= _HIGH_CLOSE_PROB:
                        high_close += 1
                    if rl in ("at_risk", "critical", "stalled", "lost_probability_high"):
                        at_risk_revenue += _decimal(ev.get("revenue"))
                except Exception as exc:
                    logger.info("%s overview skip deal=%s err=%s", MARKER, deal.id, exc)
            return len(deals)

        total = await safe_section(
            "deal_risk_overview",
            _eval_all(),
            default=0,
            errors=errors,
            db=db,
        )

        avg = int(sum(scores) / len(scores)) if scores else 0
        return {
            "healthy_deals": counts["healthy"],
            "watchlist_deals": counts["watchlist"],
            "at_risk_deals": counts["at_risk"],
            "critical_deals": counts["critical"],
            "stalled_deals": counts["stalled"],
            "lost_probability_high_deals": counts["lost_probability_high"],
            "high_close_probability_deals": high_close,
            "total_deals": total,
            "average_health_score": avg,
            "total_at_risk_revenue": _quantize(at_risk_revenue),
            "errors": errors,
            "safety_notice": DealRiskService._safety_notice(),
        }

    @staticmethod
    async def list_deals(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        risk_level: str | None = None,
        min_health: int | None = None,
        max_health: int | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        deals = await DealRiskService._load_deals(db, client_id=client_id)
        items: list[dict[str, Any]] = []

        for deal in deals:
            try:
                ev = await DealRiskService.evaluate_deal(db, deal)
            except Exception as exc:
                logger.info("%s list skip deal=%s err=%s", MARKER, deal.id, exc)
                continue

            if risk_level and ev["risk_level"] != risk_level:
                continue
            if min_health is not None and ev["deal_health_score"] < min_health:
                continue
            if max_health is not None and ev["deal_health_score"] > max_health:
                continue

            items.append({
                "deal_id": deal.id,
                "title": deal.title,
                "buyer_name": ev.get("buyer_name"),
                "buyer_company": ev.get("buyer_company"),
                "lead_id": ev["lead_id"],
                "client_id": deal.client_id,
                "status": deal.status,
                "deal_health_score": ev["deal_health_score"],
                "risk_level": ev["risk_level"],
                "close_probability": ev["close_probability"],
                "expected_close_date": ev["expected_close_date"],
                "revenue": ev.get("revenue") or Decimal("0"),
                "currency": deal.currency or "UZS",
            })

        items.sort(key=lambda x: (x["deal_health_score"], x["close_probability"]), reverse=True)
        total = len(items)
        return {"items": items[skip: skip + limit], "total": total}

    @staticmethod
    async def deal_detail(db: AsyncSession, deal_id: UUID) -> dict[str, Any]:
        result = await db.execute(
            select(CrmDeal).options(selectinload(CrmDeal.lead)).where(CrmDeal.id == deal_id),
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")

        ev = await DealRiskService.evaluate_deal(db, deal)
        lead_id = ev["lead_id"]

        buyer_intel = None
        try:
            lead = deal.lead or await CrmService._load_lead(db, lead_id)
            bi = await BuyerIntelligenceService.evaluate_buyer(db, lead)
            buyer_intel = {
                "buyer_id": lead.id,
                "name": lead.name,
                "company": lead.company,
                "buyer_score": bi["buyer_score"],
                "classification": bi["classification"],
                "risk_level": bi["risk_level"],
            }
        except Exception as exc:
            logger.info("%s detail buyer skip deal=%s err=%s", MARKER, deal_id, exc)

        threads_r = await db.execute(
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .where(CommunicationThread.lead_id == lead_id)
            .order_by(CommunicationThread.updated_at.desc()),
        )
        linked_communications = [
            {
                "thread_id": t.id,
                "channel": t.channel,
                "title": t.title,
                "message_count": len(t.messages or []),
            }
            for t in threads_r.scalars().all()
        ]

        props_r = await db.execute(
            select(ProposalDocument)
            .where(or_(ProposalDocument.lead_id == lead_id, ProposalDocument.deal_id == deal_id))
            .order_by(ProposalDocument.updated_at.desc()),
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

        now = _now()
        tasks_r = await db.execute(
            select(OperatorTask)
            .where(or_(OperatorTask.deal_id == deal_id, OperatorTask.lead_id == lead_id))
            .order_by(OperatorTask.updated_at.desc()),
        )
        linked_tasks = []
        for t in tasks_r.scalars().all():
            due = _aware(t.due_at)
            linked_tasks.append({
                "task_id": t.id,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "due_at": t.due_at,
                "is_overdue": bool(due and due < now and t.status not in ("completed", "dismissed")),
            })

        return {
            "deal_id": deal.id,
            "title": deal.title,
            "status": deal.status,
            "client_id": deal.client_id,
            "lead_id": lead_id,
            "buyer_name": ev.get("buyer_name"),
            "buyer_company": ev.get("buyer_company"),
            "expected_value": deal.expected_value,
            "currency": deal.currency or "UZS",
            "deal_health_score": ev["deal_health_score"],
            "risk_level": ev["risk_level"],
            "close_probability": ev["close_probability"],
            "expected_close_date": ev["expected_close_date"],
            "confidence_level": ev["confidence_level"],
            "risk_reasons": ev["risk_reasons"],
            "recommendations": ev["recommendations"],
            "risk_factors": ev["risk_factors"],
            "linked_buyer_intelligence": buyer_intel,
            "linked_communications": linked_communications,
            "linked_proposals": linked_proposals,
            "linked_tasks": linked_tasks,
            "last_activity_at": ev.get("last_activity_at"),
        }

    @staticmethod
    async def high_risk(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        errors: list[str] = []
        deals = await DealRiskService._load_deals(db, client_id=client_id)
        items: list[dict[str, Any]] = []
        at_risk_revenue = Decimal("0")
        intervention = 0

        rank_order = {
            "lost_probability_high": 0,
            "critical": 1,
            "stalled": 2,
            "at_risk": 3,
            "watchlist": 4,
            "healthy": 5,
        }

        for deal in deals:
            try:
                ev = await DealRiskService.evaluate_deal(db, deal)
            except Exception as exc:
                logger.info("%s high_risk skip deal=%s err=%s", MARKER, deal.id, exc)
                continue

            rl = ev["risk_level"]
            if rl in ("healthy",):
                continue

            rev = _decimal(ev.get("revenue"))
            if rl in ("at_risk", "critical", "stalled", "lost_probability_high"):
                at_risk_revenue += rev
            if rl in ("critical", "stalled", "lost_probability_high"):
                intervention += 1

            items.append({
                "deal_id": deal.id,
                "title": deal.title,
                "buyer_name": ev.get("buyer_name"),
                "deal_health_score": ev["deal_health_score"],
                "risk_level": rl,
                "close_probability": ev["close_probability"],
                "revenue": rev,
                "risk_reasons": ev["risk_reasons"],
                "_sort": rank_order.get(rl, 9),
            })

        items.sort(key=lambda x: (x["_sort"], x["deal_health_score"], -float(x["revenue"])))
        ranked: list[dict[str, Any]] = []
        for i, row in enumerate(items[:limit], start=1):
            ranked.append({
                "rank": i,
                "deal_id": row["deal_id"],
                "title": row["title"],
                "buyer_name": row["buyer_name"],
                "deal_health_score": row["deal_health_score"],
                "risk_level": row["risk_level"],
                "close_probability": row["close_probability"],
                "revenue": row["revenue"],
                "risk_reasons": row["risk_reasons"],
            })

        return {
            "items": ranked,
            "total": len(items),
            "largest_at_risk_revenue": _quantize(at_risk_revenue),
            "requiring_intervention": intervention,
            "errors": errors,
        }

    @staticmethod
    async def opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        errors: list[str] = []
        deals = await DealRiskService._load_deals(db, client_id=client_id)
        items: list[dict[str, Any]] = []
        now = _now()
        month_end = (now.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        close_this_month = 0

        for deal in deals:
            try:
                ev = await DealRiskService.evaluate_deal(db, deal)
            except Exception as exc:
                logger.info("%s opportunities skip deal=%s err=%s", MARKER, deal.id, exc)
                continue

            if ev["close_probability"] < _HIGH_CLOSE_PROB:
                continue

            exp = ev.get("expected_close_date")
            if exp and _aware(exp) and _aware(exp) <= month_end:
                close_this_month += 1

            items.append({
                "deal_id": deal.id,
                "title": deal.title,
                "buyer_name": ev.get("buyer_name"),
                "close_probability": ev["close_probability"],
                "expected_close_date": exp,
                "revenue": ev.get("revenue") or Decimal("0"),
                "deal_health_score": ev["deal_health_score"],
            })

        items.sort(key=lambda x: (-x["close_probability"], -x["deal_health_score"]))
        ranked: list[dict[str, Any]] = []
        for i, row in enumerate(items[:limit], start=1):
            ranked.append({
                "rank": i,
                **{k: v for k, v in row.items()},
            })

        return {
            "items": ranked,
            "likely_close_this_month": close_this_month,
            "total": len(items),
            "errors": errors,
        }

    @staticmethod
    async def recalculate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        q = select(CrmDeal).where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)))
        if client_id:
            q = q.where(CrmDeal.client_id == client_id)
        q = q.order_by(CrmDeal.updated_at.desc()).limit(limit)
        deals = list((await db.execute(q)).scalars().all())

        evaluated = 0
        for deal in deals:
            try:
                await DealRiskService.evaluate_deal(db, deal)
                evaluated += 1
            except Exception as exc:
                logger.info("%s recalculate skip deal=%s err=%s", MARKER, deal.id, exc)

        overview = await DealRiskService.overview(db, client_id=client_id)
        logger.info("%s recalculate: evaluated=%s", MARKER, evaluated)
        return {
            "evaluated": evaluated,
            "overview": overview,
            "message": f"Evaluated {evaluated} deal(s). No CRM, stage, or task changes were made.",
            "errors": overview.get("errors", []),
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await DealRiskService.overview(db, client_id=client_id)
        high = await DealRiskService.high_risk(db, client_id=client_id, limit=1)
        top = (high.get("items") or [None])[0]
        return {
            "healthy_deals": overview["healthy_deals"],
            "at_risk_deals": overview["at_risk_deals"] + overview["critical_deals"],
            "critical_deals": overview["critical_deals"],
            "high_close_probability_deals": overview["high_close_probability_deals"],
            "average_health_score": overview["average_health_score"],
            "total_at_risk_revenue": overview["total_at_risk_revenue"],
            "top_risk_deal_title": top["title"] if top else None,
            "errors": overview.get("errors", []),
        }

    @staticmethod
    async def executive_insights(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        overview = await DealRiskService.overview(db, client_id=client_id)
        high = await DealRiskService.high_risk(db, client_id=client_id, limit=limit)
        opps = await DealRiskService.opportunities(db, client_id=client_id, limit=limit)
        return {
            "overview": overview,
            "highest_risk_deals": high.get("items", []),
            "largest_at_risk_revenue": high.get("largest_at_risk_revenue") or Decimal("0"),
            "requiring_intervention": high.get("requiring_intervention") or 0,
            "likely_close_this_month": opps.get("items", [])[:limit],
        }

    @staticmethod
    async def deal_recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        errors: list[str] = []
        items: list[dict[str, Any]] = []
        try:
            overview = await DealRiskService.overview(db, client_id=client_id)
            if overview["critical_deals"] > 0:
                items.append({
                    "title": f"{overview['critical_deals']} critical deal(s) need intervention",
                    "description": "Review deal risk panel and assign manual recovery actions.",
                    "priority": "high",
                    "source": "deal_risk",
                })
            if overview["at_risk_deals"] > 0:
                items.append({
                    "title": f"{overview['at_risk_deals']} deal(s) at risk",
                    "description": "Mitigate stagnation and communication decline before pipeline decay.",
                    "priority": "high",
                    "source": "deal_risk",
                })
            high = await DealRiskService.high_risk(db, client_id=client_id, limit=3)
            for row in high.get("items", [])[: max(0, limit - len(items))]:
                items.append({
                    "title": f"Deal risk: {row['title']} ({row['risk_level'].replace('_', ' ')})",
                    "description": "; ".join(row.get("risk_reasons") or []) or "Manual review recommended.",
                    "priority": "high" if row["risk_level"] in ("critical", "lost_probability_high") else "medium",
                    "source": "deal_risk",
                    "deal_id": str(row["deal_id"]),
                })
        except Exception as exc:
            errors.append(str(exc))
        return {"items": items[:limit], "total": len(items), "errors": errors}

    @staticmethod
    async def classify_deals_map(
        db: AsyncSession,
        deal_ids: list[UUID],
    ) -> dict[str, dict[str, Any]]:
        if not deal_ids:
            return {}
        result = await db.execute(
            select(CrmDeal).options(selectinload(CrmDeal.lead)).where(CrmDeal.id.in_(deal_ids)),
        )
        out: dict[str, dict[str, Any]] = {}
        for deal in result.scalars().all():
            try:
                ev = await DealRiskService.evaluate_deal(db, deal)
                out[str(deal.id)] = {
                    "deal_health_score": ev["deal_health_score"],
                    "risk_level": ev["risk_level"],
                    "close_probability": ev["close_probability"],
                }
            except Exception:
                pass
        return out

    @staticmethod
    async def forecast_confidence_inputs(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Deal risk summary for revenue forecast confidence adjustment."""
        overview = await DealRiskService.overview(db, client_id=client_id)
        at_risk = (
            overview["at_risk_deals"]
            + overview["critical_deals"]
            + overview["stalled_deals"]
            + overview["lost_probability_high_deals"]
        )
        total = max(overview["total_deals"], 1)
        risk_ratio = at_risk / total
        penalty = min(0.3, risk_ratio * 0.5)
        return {
            "at_risk_deals": at_risk,
            "critical_deals": overview["critical_deals"],
            "average_health_score": overview["average_health_score"],
            "confidence_penalty": round(penalty, 3),
            "total_at_risk_revenue": overview["total_at_risk_revenue"],
        }

    @staticmethod
    async def operator_task_suggestions(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 6,
    ) -> list[dict[str, Any]]:
        """Risk-based task suggestions for Operator Tasks panel (read-only)."""
        high = await DealRiskService.high_risk(db, client_id=client_id, limit=limit)
        out: list[dict[str, Any]] = []
        for row in high.get("items") or []:
            out.append({
                "title": f"Deal intervention: {row['title']}",
                "description": "; ".join(row.get("risk_reasons") or []) or "Review deal risk manually.",
                "priority": "urgent" if row["risk_level"] in ("critical", "lost_probability_high") else "high",
                "source": "deal_risk",
                "deal_id": str(row["deal_id"]),
                "category": "deal_intervention",
            })
        return out
