"""Buyer Intelligence v2 — heuristic buyer scoring, classification, and risk (read-only)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.communication import CommunicationMessage, CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.proposal_document import ProposalDocument
from app.models.revenue_event import RevenueEvent
from app.services.communication_intelligence_service import CommunicationIntelligenceService
from app.services.crm_service import CrmService
from app.services.lead_classification_service import LeadClassificationService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Buyer Intelligence]"

CLASSIFICATIONS = frozenset({
    "hot_buyer",
    "strategic_buyer",
    "high_potential_buyer",
    "active_buyer",
    "inactive_buyer",
    "price_sensitive_buyer",
    "at_risk_buyer",
})

_INACTIVE_DAYS = 30
_STALE_DAYS = 14
_RECENT_DAYS = 7
_STRATEGIC_VALUE = Decimal("50000000")
_PRICE_KEYWORDS = ("price", "discount", "cheaper", "budget", "cost", "pricing", "цена", "скидк")


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


def _infer_country(lead: CrmLead) -> str | None:
    blob = " ".join(filter(None, [lead.notes, lead.interest, lead.company]))
    for c in (
        "Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan", "Turkmenistan",
        "Russia", "China", "Turkey", "UAE", "Saudi Arabia", "India", "Pakistan",
        "Germany", "USA", "UK",
    ):
        if c.lower() in blob.lower():
            return c
    return None


def _infer_industry(lead: CrmLead) -> str | None:
    blob = " ".join(filter(None, [lead.notes, lead.interest, lead.company])).lower()
    industries = {
        "automotive": ("auto", "car", "vehicle"),
        "electronics": ("electronic", "pcb", "component"),
        "textile": ("textile", "fabric", "garment"),
        "food": ("food", "beverage", "restaurant"),
        "construction": ("construction", "building", "cement"),
        "logistics": ("logistics", "freight", "shipping"),
        "retail": ("retail", "wholesale", "distributor"),
    }
    for name, keys in industries.items():
        if any(k in blob for k in keys):
            return name
    return None


def _is_price_sensitive(lead: CrmLead, signals: dict[str, Any]) -> bool:
    blob = " ".join(filter(None, [lead.notes, lead.interest])).lower()
    if any(k in blob for k in _PRICE_KEYWORDS):
        return True
    if lead.status == "negotiation" and signals.get("proposal_sent", 0) > 0:
        est = _decimal(lead.estimated_value)
        if est > 0 and est < Decimal("10000000"):
            return True
    return False


class BuyerIntelligenceService:
    """Evaluates CRM leads as buyers — scoring, classification, potential, and risk only."""

    @staticmethod
    def _safety_notice() -> str:
        return (
            "Read-only intelligence — no automatic messaging, CRM updates, deal updates, or task execution."
        )

    @staticmethod
    async def _collect_signals(db: AsyncSession, lead: CrmLead) -> dict[str, Any]:
        base = await LeadClassificationService._collect_signals(db, lead)
        lead_id = lead.id
        now = _now()

        deal_r = await db.execute(
            select(
                func.count(CrmDeal.id),
                func.coalesce(func.sum(case(
                    (CrmDeal.status.notin_(("lost",)), CrmDeal.expected_value),
                    else_=0,
                )), 0),
                func.coalesce(func.sum(case((CrmDeal.status == "won", CrmDeal.deal_amount), else_=0)), 0),
                func.max(CrmDeal.updated_at),
                func.coalesce(func.sum(case(
                    (CrmDeal.status.in_(("new", "proposal", "contract", "invoice", "waiting_payment")), 1),
                    else_=0,
                )), 0),
            ).where(CrmDeal.lead_id == lead_id)
        )
        deal_count, pipeline_value, won_revenue, last_deal_at, active_deals = deal_r.one()

        rev_r = await db.execute(
            select(func.coalesce(func.sum(RevenueEvent.amount), 0), func.count(RevenueEvent.id))
            .select_from(RevenueEvent)
            .join(CrmDeal, RevenueEvent.deal_id == CrmDeal.id)
            .where(CrmDeal.lead_id == lead_id)
        )
        revenue_total, revenue_events = rev_r.one()

        outbound_r = await db.execute(
            select(func.coalesce(func.sum(case(
                (CommunicationMessage.direction == "outbound", 1),
                else_=0,
            )), 0))
            .select_from(CommunicationMessage)
            .join(CommunicationThread, CommunicationMessage.thread_id == CommunicationThread.id)
            .where(CommunicationThread.lead_id == lead_id)
        )
        outbound_count = outbound_r.scalar() or 0
        inbound = int(base.get("inbound_count") or 0)
        response_ratio = 0.0
        if outbound_count > 0:
            response_ratio = min(1.0, inbound / max(outbound_count, 1))

        days_since_deal = None
        if last_deal_at:
            days_since_deal = (now - _aware(last_deal_at)).days

        proposal_stagnation = False
        last_prop = base.get("last_proposal_at")
        if last_prop and base.get("proposal_sent", 0) == 0:
            days_prop = (now - _aware(last_prop)).days if _aware(last_prop) else 999
            proposal_stagnation = days_prop >= _STALE_DAYS

        return {
            **base,
            "deal_count": int(deal_count or 0),
            "active_deals": int(active_deals or 0),
            "pipeline_value": _decimal(pipeline_value),
            "won_revenue": _decimal(won_revenue),
            "revenue_history": _decimal(revenue_total),
            "revenue_events": int(revenue_events or 0),
            "last_deal_at": last_deal_at,
            "days_since_deal": days_since_deal,
            "outbound_count": int(outbound_count),
            "response_ratio": response_ratio,
            "proposal_stagnation": proposal_stagnation,
            "crm_lead_score": int(lead.lead_score or 0),
            "country": _infer_country(lead),
            "industry": _infer_industry(lead),
        }

    @staticmethod
    def _compute_buyer_score(signals: dict[str, Any]) -> tuple[int, list[str]]:
        score = 0
        insights: list[str] = []

        # Communication activity (max 20)
        comm = 0
        if signals["inbound_count"] > 0 and signals.get("days_since_contact") is not None:
            d = signals["days_since_contact"]
            if d <= 3:
                comm = 20
                insights.append("Strong recent communication activity")
            elif d <= _RECENT_DAYS:
                comm = 14
                insights.append("Active buyer communication")
            elif d <= _STALE_DAYS:
                comm = 8
        elif signals["message_count"] > 0:
            comm = 6
        score += comm

        # CRM lead score (max 15)
        ls = signals.get("crm_lead_score") or 0
        if ls >= 70:
            score += 15
            insights.append("High CRM lead score")
        elif ls >= 50:
            score += 10
        elif ls >= 30:
            score += 5

        # Deal activity (max 20)
        if signals["active_deals"] > 0:
            score += min(20, 10 + signals["active_deals"] * 3)
            insights.append(f"{signals['active_deals']} active deal(s) in pipeline")
        elif signals["deal_count"] > 0:
            score += 8

        # Proposal activity (max 15)
        if signals["proposal_sent"] > 0:
            score += 15
            insights.append("Proposal activity recorded")
        elif signals["proposal_draft"] > 0:
            score += 9
        elif signals["proposal_total"] > 0:
            score += 5

        # Revenue history (max 15)
        rev = signals.get("revenue_history") or Decimal("0")
        if rev >= _STRATEGIC_VALUE:
            score += 15
            insights.append("Significant revenue history")
        elif rev > 0:
            score += 10
            insights.append("Prior revenue attributed to buyer")
        elif signals.get("won_revenue", 0) > 0:
            score += 12

        # Response frequency (max 15)
        ratio = signals.get("response_ratio") or 0
        if ratio >= 0.8 and signals["inbound_count"] >= 2:
            score += 15
            insights.append("High inbound response frequency")
        elif ratio >= 0.5:
            score += 10
        elif signals["inbound_count"] > 0:
            score += 6

        # Penalties
        days = signals.get("days_since_contact")
        if days is not None:
            if days >= _INACTIVE_DAYS:
                score -= 25
                insights.append("Extended buyer inactivity")
            elif days >= _STALE_DAYS:
                score -= 10
        if signals.get("follow_up_overdue"):
            score -= 8
            insights.append("Overdue follow-up increases churn risk")
        if signals.get("proposal_stagnation"):
            score -= 6
            insights.append("Proposal stagnation detected")

        if signals["status"] == "won":
            score = max(score, 80)
        elif signals["status"] == "lost":
            score = min(score, 20)

        return _clamp_score(score), insights[:8]

    @staticmethod
    def _classification(
        score: int,
        signals: dict[str, Any],
        lead: CrmLead,
    ) -> str:
        days = signals.get("days_since_contact")
        pipeline = signals.get("pipeline_value") or Decimal("0")
        won = signals.get("won_revenue") or Decimal("0")

        if _is_price_sensitive(lead, signals) and score >= 35:
            return "price_sensitive_buyer"

        if signals.get("follow_up_overdue") or signals.get("proposal_stagnation"):
            if days is not None and days >= _STALE_DAYS:
                return "at_risk_buyer"

        if days is not None and days >= _INACTIVE_DAYS and score < 35:
            return "inactive_buyer"

        if won >= _STRATEGIC_VALUE or pipeline >= _STRATEGIC_VALUE or signals["deal_count"] >= 2:
            if score >= 50 or lead.status in ("negotiation", "won", "qualified"):
                return "strategic_buyer"

        if score >= 76 and signals["inbound_count"] > 0:
            if days is not None and days <= _RECENT_DAYS:
                return "hot_buyer"

        if score >= 56 or lead.status in ("qualified", "proposal_sent", "negotiation"):
            return "high_potential_buyer"

        if days is not None and days <= _STALE_DAYS and score >= 40:
            return "active_buyer"

        if score < 40 and days is not None and days >= _STALE_DAYS:
            return "at_risk_buyer"

        if days is not None and days >= _INACTIVE_DAYS:
            return "inactive_buyer"

        return "active_buyer" if score >= 30 else "at_risk_buyer"

    @staticmethod
    def _risk_level(score: int, signals: dict[str, Any], classification: str) -> str:
        if classification in ("at_risk_buyer", "inactive_buyer"):
            if signals.get("follow_up_overdue") or signals.get("proposal_stagnation"):
                return "critical" if score < 30 else "high"
            return "high" if score < 45 else "medium"
        if signals.get("follow_up_overdue") or signals.get("proposal_stagnation"):
            return "medium"
        if classification == "hot_buyer" and score >= 80:
            return "low"
        if score >= 60:
            return "low"
        if score >= 40:
            return "medium"
        return "high"

    @staticmethod
    def _potential(signals: dict[str, Any], lead: CrmLead, score: int) -> dict[str, Any]:
        base = _decimal(lead.estimated_value)
        pipeline = signals.get("pipeline_value") or Decimal("0")
        won = signals.get("won_revenue") or signals.get("revenue_history") or Decimal("0")

        deal_size = base if base > 0 else pipeline
        if deal_size <= 0 and signals["proposal_sent"] > 0:
            deal_size = Decimal("15000000")

        annual = won * Decimal("1.2") if won > 0 else deal_size * Decimal("2.5")
        if annual <= 0:
            annual = Decimal(str(max(5000000, score * 200000)))

        growth = "stable"
        days = signals.get("days_since_contact")
        if days is not None and days <= _RECENT_DAYS and score >= 60:
            growth = "high"
        elif days is not None and days <= _STALE_DAYS:
            growth = "moderate"
        elif days is not None and days >= _INACTIVE_DAYS:
            growth = "declining"

        return {
            "expected_annual_revenue": _quantize(annual),
            "expected_deal_size": _quantize(deal_size if deal_size > 0 else annual * Decimal("0.4")),
            "growth_potential": growth,
            "currency": "UZS",
        }

    @staticmethod
    def _risk_signals(signals: dict[str, Any], classification: str) -> list[str]:
        risks: list[str] = []
        days = signals.get("days_since_contact")
        if days is not None and days >= _INACTIVE_DAYS:
            risks.append("inactivity")
        if signals.get("proposal_stagnation"):
            risks.append("proposal_stagnation")
        if days is not None and days >= _STALE_DAYS and signals["inbound_count"] == 0:
            risks.append("communication_decline")
        if signals.get("follow_up_overdue"):
            risks.append("lost_opportunity_signal")
        if classification == "at_risk_buyer" and "lost_opportunity_signal" not in risks:
            risks.append("lost_opportunity_signal")
        return risks

    @staticmethod
    def _recommendations(
        classification: str,
        risk_level: str,
        signals: dict[str, Any],
    ) -> list[str]:
        recs: list[str] = []
        if classification == "hot_buyer":
            recs.append("Prioritize manual outreach — maintain momentum with timely follow-up.")
        elif classification == "strategic_buyer":
            recs.append("Assign senior operator review — coordinate proposals and deal room planning.")
        elif classification == "high_potential_buyer":
            recs.append("Advance qualification — prepare proposal draft for manual approval.")
        elif classification == "price_sensitive_buyer":
            recs.append("Prepare value-focused proposal options — avoid auto-discounting.")
        elif classification == "at_risk_buyer":
            recs.append("Run re-engagement review — confirm deal status before further investment.")
        elif classification == "inactive_buyer":
            recs.append("Evaluate archive vs. one-time re-engagement campaign manually.")
        else:
            recs.append("Schedule next manual touchpoint and log CRM activity.")

        if signals.get("follow_up_overdue"):
            recs.append("Complete overdue follow-up manually — no auto-messaging.")
        if risk_level in ("high", "critical"):
            recs.append("Escalate to sales manager for executive review this week.")
        return recs[:5]

    @staticmethod
    async def evaluate_buyer(db: AsyncSession, lead: CrmLead) -> dict[str, Any]:
        signals = await BuyerIntelligenceService._collect_signals(db, lead)
        score, insights = BuyerIntelligenceService._compute_buyer_score(signals)
        classification = BuyerIntelligenceService._classification(score, signals, lead)
        risk_level = BuyerIntelligenceService._risk_level(score, signals, classification)
        potential = BuyerIntelligenceService._potential(signals, lead, score)
        risks = BuyerIntelligenceService._risk_signals(signals, classification)
        recommendations = BuyerIntelligenceService._recommendations(classification, risk_level, signals)

        comm = await CommunicationIntelligenceService.get_lead_communication_score(db, lead.id)
        if comm:
            cs = int(comm.get("health_score") or 0)
            if cs >= 70 and "communication health" not in " ".join(insights).lower():
                insights.append("Strong communication health score")
                score = _clamp_score(score + 5)
            elif cs < 30:
                insights.append("Weak communication health — monitor closely")
                score = _clamp_score(score - 5)
                if risk_level == "low":
                    risk_level = "medium"

        return {
            "buyer_score": score,
            "classification": classification,
            "risk_level": risk_level,
            "annual_potential": potential["expected_annual_revenue"],
            "potential": potential,
            "insights": insights,
            "recommendations": recommendations,
            "risks": risks,
            "signals": signals,
            "last_activity_at": signals.get("last_contact_at"),
        }

    @staticmethod
    async def _load_buyers(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        client_ids: list[UUID] | None = None,
    ) -> list[CrmLead]:
        q = select(CrmLead).where(CrmLead.status.notin_(("lost",)))
        if client_id:
            q = q.where(CrmLead.client_id == client_id)
        elif client_ids is not None:
            if not client_ids:
                return []
            q = q.where(CrmLead.client_id.in_(client_ids))
        result = await db.execute(q.order_by(CrmLead.updated_at.desc()))
        return list(result.scalars().all())

    @staticmethod
    async def _resolve_scope(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> tuple[UUID | None, list[UUID] | None]:
        return await TenantService.resolve_tenant_client_scope(
            db, tenant_id=tenant_id, client_id=client_id,
        )

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_id, client_ids = await BuyerIntelligenceService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        errors: list[str] = []
        counts = {k: 0 for k in CLASSIFICATIONS}
        scores: list[int] = []

        async def _eval_all() -> int:
            leads = await BuyerIntelligenceService._load_buyers(
                db, client_id=client_id, client_ids=client_ids,
            )
            for lead in leads:
                try:
                    item = await BuyerIntelligenceService.evaluate_buyer(db, lead)
                    cls = item["classification"]
                    if cls in counts:
                        counts[cls] += 1
                    scores.append(item["buyer_score"])
                except Exception as exc:
                    logger.info("%s overview skip: lead=%s err=%s", MARKER, lead.id, exc)
            return len(leads)

        total = await safe_section(
            "buyer_intelligence_overview",
            _eval_all(),
            default=0,
            errors=errors,
            db=db,
        )

        avg = int(sum(scores) / len(scores)) if scores else 0
        return {
            "hot_buyers": counts["hot_buyer"],
            "strategic_buyers": counts["strategic_buyer"],
            "high_potential_buyers": counts["high_potential_buyer"],
            "active_buyers": counts["active_buyer"],
            "inactive_buyers": counts["inactive_buyer"],
            "price_sensitive_buyers": counts["price_sensitive_buyer"],
            "at_risk_buyers": counts["at_risk_buyer"],
            "total_buyers": total,
            "average_buyer_score": avg,
            "errors": errors,
            "safety_notice": BuyerIntelligenceService._safety_notice(),
        }

    @staticmethod
    async def list_buyers(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        classification: str | None = None,
        min_score: int | None = None,
        max_score: int | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        leads = await BuyerIntelligenceService._load_buyers(db, client_id=client_id)
        items: list[dict[str, Any]] = []

        for lead in leads:
            try:
                ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
            except Exception as exc:
                logger.info("%s list skip: lead=%s err=%s", MARKER, lead.id, exc)
                continue

            if classification and ev["classification"] != classification:
                continue
            if min_score is not None and ev["buyer_score"] < min_score:
                continue
            if max_score is not None and ev["buyer_score"] > max_score:
                continue

            sig = ev["signals"]
            items.append({
                "buyer_id": lead.id,
                "name": lead.name,
                "company": lead.company,
                "country": sig.get("country"),
                "industry": sig.get("industry"),
                "buyer_score": ev["buyer_score"],
                "classification": ev["classification"],
                "annual_potential": ev["annual_potential"],
                "risk_level": ev["risk_level"],
                "status": lead.status,
                "client_id": lead.client_id,
            })

        items.sort(key=lambda x: (x["buyer_score"], x["annual_potential"]), reverse=True)
        total = len(items)
        return {"items": items[skip: skip + limit], "total": total}

    @staticmethod
    async def buyer_detail(db: AsyncSession, buyer_id: UUID) -> dict[str, Any]:
        lead = await CrmService._load_lead(db, buyer_id)
        ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
        sig = ev["signals"]

        deals_r = await db.execute(
            select(CrmDeal).where(CrmDeal.lead_id == buyer_id).order_by(CrmDeal.updated_at.desc())
        )
        linked_deals = [
            {
                "deal_id": d.id,
                "title": d.title,
                "status": d.status,
                "expected_value": d.expected_value,
                "updated_at": d.updated_at,
            }
            for d in deals_r.scalars().all()
        ]

        props_r = await db.execute(
            select(ProposalDocument)
            .where(ProposalDocument.lead_id == buyer_id)
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

        threads_r = await db.execute(
            select(CommunicationThread)
            .options(selectinload(CommunicationThread.messages))
            .where(CommunicationThread.lead_id == buyer_id)
            .order_by(CommunicationThread.updated_at.desc())
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

        return {
            "buyer_id": lead.id,
            "name": lead.name,
            "company": lead.company,
            "country": sig.get("country"),
            "industry": sig.get("industry"),
            "status": lead.status,
            "client_id": lead.client_id,
            "buyer_score": ev["buyer_score"],
            "classification": ev["classification"],
            "risk_level": ev["risk_level"],
            "potential": ev["potential"],
            "insights": ev["insights"],
            "recommendations": ev["recommendations"],
            "risks": ev["risks"],
            "linked_deals": linked_deals,
            "linked_proposals": linked_proposals,
            "linked_communications": linked_communications,
            "last_activity_at": ev["last_activity_at"],
        }

    @staticmethod
    async def top_buyers(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        errors: list[str] = []
        leads = await BuyerIntelligenceService._load_buyers(db, client_id=client_id)
        evaluated: list[dict[str, Any]] = []

        for lead in leads:
            try:
                ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
                sig = ev["signals"]
                evaluated.append({
                    "buyer_id": lead.id,
                    "name": lead.name,
                    "company": lead.company,
                    "buyer_score": ev["buyer_score"],
                    "classification": ev["classification"],
                    "annual_potential": ev["annual_potential"],
                    "revenue_history": sig.get("revenue_history") or Decimal("0"),
                    "days_since_contact": sig.get("days_since_contact"),
                    "growth_score": (
                        100 - (sig.get("days_since_contact") or 30) * 2
                        + ev["buyer_score"] // 2
                    ),
                })
            except Exception as exc:
                logger.info("%s top skip: lead=%s err=%s", MARKER, lead.id, exc)

        by_score = sorted(evaluated, key=lambda x: x["buyer_score"], reverse=True)[:limit]
        by_growth = sorted(evaluated, key=lambda x: x["growth_score"], reverse=True)[:limit]
        by_revenue = sorted(evaluated, key=lambda x: x["revenue_history"], reverse=True)[:limit]

        def _rank(rows: list[dict[str, Any]], label: str) -> list[dict[str, Any]]:
            out = []
            for i, r in enumerate(rows, start=1):
                out.append({
                    "rank": i,
                    "buyer_id": r["buyer_id"],
                    "name": r["name"],
                    "company": r["company"],
                    "buyer_score": r["buyer_score"],
                    "classification": r["classification"],
                    "annual_potential": r["annual_potential"],
                    "metric_label": label,
                })
            return out

        return {
            "top_buyers": _rank(by_score, "buyer_score"),
            "fastest_growing": _rank(by_growth, "growth_momentum"),
            "highest_revenue": _rank(by_revenue, "revenue_history"),
            "errors": errors,
        }

    @staticmethod
    async def risks(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        errors: list[str] = []
        leads = await BuyerIntelligenceService._load_buyers(db, client_id=client_id)
        items: list[dict[str, Any]] = []
        by_level: dict[str, int] = {"low": 0, "medium": 0, "high": 0, "critical": 0}

        for lead in leads:
            try:
                ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
            except Exception as exc:
                logger.info("%s risks skip: lead=%s err=%s", MARKER, lead.id, exc)
                continue

            rl = ev["risk_level"]
            if rl not in ("high", "critical") and ev["classification"] not in (
                "at_risk_buyer", "inactive_buyer", "price_sensitive_buyer",
            ):
                continue

            risk_sigs = ev["risks"]
            title = f"{lead.name}: {ev['classification'].replace('_', ' ')}"
            desc_parts = []
            if "inactivity" in risk_sigs:
                desc_parts.append("Extended inactivity")
            if "proposal_stagnation" in risk_sigs:
                desc_parts.append("Proposal stagnation")
            if "communication_decline" in risk_sigs:
                desc_parts.append("Communication decline")
            if "lost_opportunity_signal" in risk_sigs:
                desc_parts.append("Lost opportunity signals")

            items.append({
                "buyer_id": lead.id,
                "name": lead.name,
                "company": lead.company,
                "risk_level": rl,
                "classification": ev["classification"],
                "buyer_score": ev["buyer_score"],
                "title": title,
                "description": "; ".join(desc_parts) or "Buyer risk flagged for manual review",
                "risk_signals": risk_sigs,
            })
            by_level[rl] = by_level.get(rl, 0) + 1

        items.sort(
            key=lambda x: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(x["risk_level"], 4),
        )
        page = items[:limit]
        return {"items": page, "total": len(items), "by_level": by_level, "errors": errors}

    @staticmethod
    async def recalculate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 200,
    ) -> dict[str, Any]:
        q = select(CrmLead).where(CrmLead.status.notin_(("lost",)))
        if client_id:
            q = q.where(CrmLead.client_id == client_id)
        q = q.order_by(CrmLead.updated_at.desc()).limit(limit)
        leads = list((await db.execute(q)).scalars().all())

        evaluated = 0
        for lead in leads:
            try:
                await BuyerIntelligenceService.evaluate_buyer(db, lead)
                evaluated += 1
            except Exception as exc:
                logger.info("%s recalculate skip: lead=%s err=%s", MARKER, lead.id, exc)

        overview = await BuyerIntelligenceService.overview(db, client_id=client_id)
        logger.info("%s recalculate: evaluated=%s", MARKER, evaluated)
        return {
            "evaluated": evaluated,
            "overview": overview,
            "message": f"Evaluated {evaluated} buyer(s). No CRM or deal changes were made.",
            "errors": overview.get("errors", []),
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await BuyerIntelligenceService.overview(db, client_id=client_id)
        top = await BuyerIntelligenceService.top_buyers(db, client_id=client_id, limit=1)
        top_row = (top.get("top_buyers") or [None])[0]
        return {
            "hot_buyers": overview["hot_buyers"],
            "strategic_buyers": overview["strategic_buyers"],
            "high_potential_buyers": overview["high_potential_buyers"],
            "at_risk_buyers": overview["at_risk_buyers"],
            "average_buyer_score": overview["average_buyer_score"],
            "top_buyer_name": top_row["name"] if top_row else None,
            "top_buyer_score": top_row["buyer_score"] if top_row else 0,
            "errors": overview.get("errors", []),
        }

    @staticmethod
    async def buyer_recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Compact recommendations for Multi-Agent and Sales Department panels."""
        errors: list[str] = []
        items: list[dict[str, Any]] = []
        try:
            overview = await BuyerIntelligenceService.overview(db, client_id=client_id)
            if overview["hot_buyers"] > 0:
                items.append({
                    "title": f"{overview['hot_buyers']} hot buyer(s) need momentum",
                    "description": "Prioritize manual follow-up on highest-scoring active buyers.",
                    "priority": "high",
                    "source": "buyer_intelligence",
                })
            if overview["at_risk_buyers"] > 0:
                items.append({
                    "title": f"{overview['at_risk_buyers']} buyer(s) at risk",
                    "description": "Review stagnation and inactivity signals before pipeline decay.",
                    "priority": "high",
                    "source": "buyer_intelligence",
                })
            top = await BuyerIntelligenceService.top_buyers(db, client_id=client_id, limit=3)
            for row in top.get("top_buyers", [])[: max(0, limit - len(items))]:
                items.append({
                    "title": f"Top buyer: {row['name']} (score {row['buyer_score']})",
                    "description": f"Classification: {row['classification'].replace('_', ' ')} — manual review.",
                    "priority": "medium",
                    "source": "buyer_intelligence",
                })
        except Exception as exc:
            errors.append(str(exc))
        return {"items": items[:limit], "total": len(items), "errors": errors}

    @staticmethod
    async def classify_buyers_map(
        db: AsyncSession,
        buyer_ids: list[UUID],
    ) -> dict[str, dict[str, Any]]:
        if not buyer_ids:
            return {}
        result = await db.execute(select(CrmLead).where(CrmLead.id.in_(buyer_ids)))
        out: dict[str, dict[str, Any]] = {}
        for lead in result.scalars().all():
            try:
                ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
                out[str(lead.id)] = {
                    "buyer_score": ev["buyer_score"],
                    "classification": ev["classification"],
                    "risk_level": ev["risk_level"],
                    "annual_potential": ev["annual_potential"],
                }
            except Exception:
                pass
        return out

    @staticmethod
    async def executive_insights(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        top = await BuyerIntelligenceService.top_buyers(db, client_id=client_id, limit=limit)
        risks_data = await BuyerIntelligenceService.risks(db, client_id=client_id, limit=limit)
        overview = await BuyerIntelligenceService.overview(db, client_id=client_id)
        return {
            "overview": overview,
            "top_buyers": top.get("top_buyers", []),
            "fastest_growing": top.get("fastest_growing", []),
            "highest_revenue": top.get("highest_revenue", []),
            "highest_risk": risks_data.get("items", [])[:limit],
        }

    @staticmethod
    async def buyer_contributions(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Top buyer contribution hints for revenue forecast."""
        top = await BuyerIntelligenceService.top_buyers(db, client_id=client_id, limit=limit)
        out: list[dict[str, Any]] = []
        for row in top.get("highest_revenue", []):
            out.append({
                "buyer_id": str(row["buyer_id"]),
                "name": row["name"],
                "annual_potential": row["annual_potential"],
                "buyer_score": row["buyer_score"],
                "classification": row["classification"],
            })
        return out
