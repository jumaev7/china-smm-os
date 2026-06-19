"""Revenue attribution, commission tracking, and executive insights."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.revenue_event import RevenueEvent
from app.schemas.revenue import CrmDealMarkWonRequest
from app.services.attribution_link_service import AttributionLinkService
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.crm_attribution import (
    ATTRIBUTION_LABELS,
    attribution_source_expr,
    effective_attribution_from_lead,
    normalize_attribution_key,
)
from app.services.deal_event_service import DealEventService
from app.services.deal_service import DealService, _serialize_deal

logger = logging.getLogger(__name__)

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})

COMMISSION_STATUSES = frozenset({"pending", "approved", "paid"})
REVENUE_EVENT_TYPES = frozenset({"won", "commission_approved", "commission_paid"})

DEFAULT_PARTNER_SHARE_PERCENT = Decimal("20")

_AI_SYSTEM = """\
You analyze revenue and commission data for an SMM agency in Uzbekistan.
Return ONLY JSON:
{
  "summary": "2-4 sentence executive summary of revenue performance",
  "risks": ["risk 1", "risk 2"],
  "opportunities": ["opportunity 1", "opportunity 2"],
  "recommendations": ["recommendation 1", "recommendation 2", "recommendation 3"]
}

Rules:
- Tracking only — never suggest automatic payments or financial transactions
- Use attribution and commission data from the context
- Mention best channels and high-value clients when evident
- Max 5 items per list; concise actionable phrases
"""


def _calc_commission(deal_amount: Decimal, commission_percent: Decimal) -> Decimal:
    raw = deal_amount * commission_percent / Decimal("100")
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _effective_attribution(lead: CrmLead | None) -> str:
    return effective_attribution_from_lead(lead)


def _serialize_revenue_deal(deal: CrmDeal) -> dict[str, Any]:
    lead = deal.lead
    base = _serialize_deal(deal)
    base.update({
        "deal_id": deal.id,
        "attribution_source": _effective_attribution(lead),
        "deal_amount": deal.deal_amount,
        "currency": deal.currency or "UZS",
        "commission_percent": deal.commission_percent,
        "commission_amount": deal.commission_amount,
        "commission_status": deal.commission_status,
        "partner_commission_percent": deal.partner_commission_percent,
        "partner_commission_amount": deal.partner_commission_amount,
    })
    return base


async def _record_revenue_event(
    db: AsyncSession,
    deal_id: UUID,
    event_type: str,
    amount: Decimal | None,
) -> RevenueEvent:
    event = RevenueEvent(deal_id=deal_id, type=event_type, amount=amount)
    db.add(event)
    await db.flush()
    return event


class RevenueService:
    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        deals_limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        errors: list[str] = []
        deals_limit = clamp_limit(deals_limit)

        async def _aggregates() -> dict[str, Any]:
            pipeline_value_raw = await db.scalar(
                select(func.coalesce(func.sum(CrmDeal.expected_value), 0))
                .select_from(CrmDeal)
                .where(CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)))
            )
            deals_won = int(await db.scalar(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.status == "won")
            ) or 0)
            deals_lost = int(await db.scalar(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.status == "lost")
            ) or 0)
            closed_revenue_raw = await db.scalar(
                select(func.coalesce(func.sum(CrmDeal.deal_amount), 0))
                .select_from(CrmDeal)
                .where(CrmDeal.status == "won")
            )
            our_comm_raw = await db.scalar(
                select(func.coalesce(func.sum(CrmDeal.commission_amount), 0))
                .select_from(CrmDeal)
                .where(CrmDeal.status == "won")
            )
            partner_comm_raw = await db.scalar(
                select(func.coalesce(func.sum(CrmDeal.partner_commission_amount), 0))
                .select_from(CrmDeal)
                .where(CrmDeal.status == "won")
            )
            pending_raw = await db.scalar(
                select(func.coalesce(func.sum(CrmDeal.commission_amount), 0))
                .select_from(CrmDeal)
                .where(
                    CrmDeal.status == "won",
                    (CrmDeal.commission_status.is_(None))
                    | (CrmDeal.commission_status.in_(("pending", "approved"))),
                )
            )
            paid_raw = await db.scalar(
                select(func.coalesce(func.sum(CrmDeal.commission_amount), 0))
                .select_from(CrmDeal)
                .where(CrmDeal.status == "won", CrmDeal.commission_status == "paid")
            )
            return {
                "pipeline_value": Decimal(str(pipeline_value_raw or 0)),
                "deals_won": deals_won,
                "deals_lost": deals_lost,
                "closed_revenue": Decimal(str(closed_revenue_raw or 0)),
                "our_commission": Decimal(str(our_comm_raw or 0)),
                "partner_commission": Decimal(str(partner_comm_raw or 0)),
                "pending_commission": Decimal(str(pending_raw or 0)),
                "paid_commission": Decimal(str(paid_raw or 0)),
            }

        async def _attribution() -> list[dict[str, Any]]:
            src_expr = attribution_source_expr()
            rows = await db.execute(
                select(
                    src_expr,
                    func.count(CrmDeal.id),
                    func.coalesce(func.sum(CrmDeal.deal_amount), 0),
                    func.coalesce(func.sum(CrmDeal.commission_amount), 0),
                )
                .select_from(CrmDeal)
                .join(CrmLead, CrmDeal.lead_id == CrmLead.id)
                .where(CrmDeal.status == "won")
                .group_by(src_expr)
            )
            attribution: dict[str, dict[str, Any]] = {}
            for src, count, revenue, commission in rows.all():
                key = normalize_attribution_key(str(src) if src is not None else None)
                bucket = attribution.setdefault(key, {
                    "source": key,
                    "label": ATTRIBUTION_LABELS.get(key, key.title()),
                    "deal_count": 0,
                    "revenue": Decimal("0"),
                    "commission": Decimal("0"),
                })
                bucket["deal_count"] += int(count or 0)
                bucket["revenue"] += Decimal(str(revenue or 0))
                bucket["commission"] += Decimal(str(commission or 0))

            breakdown = []
            for src_key, label in ATTRIBUTION_LABELS.items():
                data = attribution.get(src_key, {
                    "source": src_key,
                    "label": label,
                    "deal_count": 0,
                    "revenue": Decimal("0"),
                    "commission": Decimal("0"),
                })
                breakdown.append(data)
            breakdown.sort(key=lambda x: x["revenue"], reverse=True)
            return breakdown

        async def _deal_rows() -> tuple[list[dict[str, Any]], int]:
            total = int(await db.scalar(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.status == "won")
            ) or 0)
            deals_r = await db.execute(
                select(CrmDeal)
                .options(selectinload(CrmDeal.lead), selectinload(CrmDeal.client))
                .where(CrmDeal.status == "won")
                .order_by(CrmDeal.updated_at.desc())
                .limit(deals_limit)
            )
            rows = [_serialize_revenue_deal(d) for d in deals_r.scalars().all()]
            return rows, total

        agg = await safe_section("aggregates", _aggregates(), default={
            "pipeline_value": Decimal("0"),
            "deals_won": 0,
            "deals_lost": 0,
            "closed_revenue": Decimal("0"),
            "our_commission": Decimal("0"),
            "partner_commission": Decimal("0"),
            "pending_commission": Decimal("0"),
            "paid_commission": Decimal("0"),
        }, errors=errors, db=db)
        breakdown = await safe_section("attribution", _attribution(), default=[], errors=errors, db=db)
        link_breakdown = await safe_section(
            "attribution_links",
            AttributionLinkService.stats_breakdown(db),
            default=[],
            errors=errors,
            db=db,
        )
        deals, deals_total = await safe_section(
            "deals", _deal_rows(), default=([], 0), errors=errors, db=db,
        )

        our_comm = agg["our_commission"]
        partner_comm = agg["partner_commission"]
        total_commission = our_comm + partner_comm

        return {
            "total_pipeline_value": agg["pipeline_value"],
            "total_closed_revenue": agg["closed_revenue"],
            "total_commission_earned": total_commission,
            "pending_commission": agg["pending_commission"],
            "paid_commission": agg["paid_commission"],
            "our_commission": our_comm,
            "partner_commission": partner_comm,
            "deals_won": agg["deals_won"],
            "deals_lost": agg["deals_lost"],
            "attribution_breakdown": breakdown,
            "attribution_links": link_breakdown,
            "deals": deals,
            "deals_total": deals_total,
            "errors": errors,
        }

    @staticmethod
    async def mark_won(
        db: AsyncSession,
        deal_id: UUID,
        data: CrmDealMarkWonRequest,
    ) -> dict[str, Any]:
        deal = await DealService._load_deal(db, deal_id)
        if deal.status == "won" and deal.deal_amount is not None:
            raise HTTPException(status_code=400, detail="Deal already marked won with revenue")

        total_fee = _calc_commission(data.deal_amount, data.commission_percent)
        lead = deal.lead

        partner_fee = Decimal("0")
        partner_pct = None
        our_commission = total_fee

        if lead and lead.partner_id:
            partner_pct = data.partner_commission_percent or DEFAULT_PARTNER_SHARE_PERCENT
            partner_fee = _calc_commission(total_fee, partner_pct)
            our_commission = total_fee - partner_fee
            deal.partner_commission_percent = partner_pct
            deal.partner_commission_amount = partner_fee

        deal.status = "won"
        deal.deal_amount = data.deal_amount
        deal.currency = data.currency.strip().upper()[:10] or "UZS"
        deal.commission_percent = data.commission_percent
        deal.commission_amount = our_commission
        deal.commission_status = "pending"
        deal.probability = 100
        deal.updated_at = datetime.now(timezone.utc)

        if lead:
            lead.status = "won"
            lead.updated_at = datetime.now(timezone.utc)
            if not lead.attribution_source:
                lead.attribution_source = "referral" if lead.partner_id else (lead.source or "manual")

        await _record_revenue_event(db, deal.id, "won", data.deal_amount)
        await DealEventService.record_event(
            db,
            deal.id,
            "status_change",
            f"Deal won — {data.deal_amount} {deal.currency} "
            f"(our {our_commission}, partner {partner_fee})",
            {
                "deal_amount": str(data.deal_amount),
                "commission_percent": str(data.commission_percent),
                "our_commission": str(our_commission),
                "partner_commission": str(partner_fee),
                "partner_commission_percent": str(partner_pct) if partner_pct else None,
            },
        )

        await db.commit()
        await db.refresh(deal, attribute_names=["lead", "client"])

        logger.info(
            "[Revenue] deal won: id=%s amount=%s our=%s partner=%s",
            deal_id,
            data.deal_amount,
            our_commission,
            partner_fee,
        )
        return _serialize_deal(deal)

    @staticmethod
    async def approve_commission(db: AsyncSession, deal_id: UUID) -> dict[str, Any]:
        deal = await RevenueService._load_commission_deal(db, deal_id)
        if deal.commission_status != "pending":
            raise HTTPException(status_code=400, detail="Commission is not pending approval")

        deal.commission_status = "approved"
        deal.updated_at = datetime.now(timezone.utc)
        await _record_revenue_event(db, deal.id, "commission_approved", deal.commission_amount)
        await db.commit()
        await db.refresh(deal, attribute_names=["lead", "client"])

        logger.info("[Revenue] commission approved: deal=%s", deal_id)
        return _serialize_revenue_deal(deal)

    @staticmethod
    async def mark_commission_paid(db: AsyncSession, deal_id: UUID) -> dict[str, Any]:
        deal = await RevenueService._load_commission_deal(db, deal_id)
        if deal.commission_status not in ("pending", "approved"):
            raise HTTPException(status_code=400, detail="Commission cannot be marked paid")

        deal.commission_status = "paid"
        deal.updated_at = datetime.now(timezone.utc)
        await _record_revenue_event(db, deal.id, "commission_paid", deal.commission_amount)
        await db.commit()
        await db.refresh(deal, attribute_names=["lead", "client"])

        logger.info("[Revenue] commission paid: deal=%s", deal_id)
        return _serialize_revenue_deal(deal)

    @staticmethod
    async def ai_insights(db: AsyncSession) -> dict[str, Any]:
        overview = await RevenueService.overview(db)
        context = RevenueService._build_ai_context(overview)

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                result = RevenueService._heuristic_insights(overview)
            else:
                _validate_api_key()
                openai = get_openai()
                response = await openai.chat.completions.create(
                    model=settings.OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": _AI_SYSTEM},
                        {"role": "user", "content": context[:10000]},
                    ],
                    temperature=0.4,
                    max_tokens=800,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                result = {
                    "summary": str(parsed.get("summary") or "")[:2000],
                    "risks": RevenueService._str_list(parsed.get("risks"), 5),
                    "opportunities": RevenueService._str_list(parsed.get("opportunities"), 5),
                    "recommendations": RevenueService._str_list(parsed.get("recommendations"), 5),
                    "source": "ai",
                }
        except Exception as exc:
            logger.warning("[Revenue] AI insights fallback: %s", exc)
            result = RevenueService._heuristic_insights(overview)

        logger.info("[Revenue] ai-insights: source=%s", result["source"])
        return result

    @staticmethod
    async def _load_commission_deal(db: AsyncSession, deal_id: UUID) -> CrmDeal:
        deal = await DealService._load_deal(db, deal_id)
        if deal.status != "won":
            raise HTTPException(status_code=400, detail="Deal must be won to manage commission")
        if deal.commission_amount is None:
            raise HTTPException(status_code=400, detail="Deal has no commission recorded")
        return deal

    @staticmethod
    def _build_ai_context(overview: dict[str, Any]) -> str:
        lines = [
            "REVENUE OVERVIEW:",
            f"- Pipeline value: {overview['total_pipeline_value']}",
            f"- Closed revenue: {overview['total_closed_revenue']}",
            f"- Total commission earned: {overview['total_commission_earned']}",
            f"- Pending commission: {overview['pending_commission']}",
            f"- Paid commission: {overview['paid_commission']}",
            f"- Deals won/lost: {overview['deals_won']}/{overview['deals_lost']}",
            "",
            "ATTRIBUTION BREAKDOWN:",
        ]
        for row in overview.get("attribution_breakdown") or []:
            if row.get("deal_count", 0) > 0:
                lines.append(
                    f"- {row['label']}: {row['deal_count']} deals, "
                    f"revenue {row['revenue']}, commission {row['commission']}",
                )

        top_deals = sorted(
            overview.get("deals") or [],
            key=lambda d: float(d.get("deal_amount") or 0),
            reverse=True,
        )[:5]
        if top_deals:
            lines.append("")
            lines.append("TOP WON DEALS:")
            for d in top_deals:
                lines.append(
                    f"- {d.get('title')} ({d.get('client_name')}): "
                    f"{d.get('deal_amount')} {d.get('currency')}, "
                    f"commission {d.get('commission_amount')} [{d.get('commission_status')}]",
                )
        return "\n".join(lines)

    @staticmethod
    def _str_list(raw: Any, limit: int) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            text = str(item).strip()
            if text:
                out.append(text[:300])
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _heuristic_insights(overview: dict[str, Any]) -> dict[str, Any]:
        breakdown = overview.get("attribution_breakdown") or []
        active = [b for b in breakdown if b.get("deal_count", 0) > 0]
        best = max(active, key=lambda b: b["revenue"], default=None)

        risks: list[str] = []
        opportunities: list[str] = []
        recommendations: list[str] = []

        pending = overview.get("pending_commission") or Decimal("0")
        if pending > 0:
            risks.append(f"{pending} UZS commission pending approval or payment")
            recommendations.append("Review and approve pending commissions manually")

        if overview.get("deals_lost", 0) > overview.get("deals_won", 0):
            risks.append("More deals lost than won — review pipeline conversion")

        if best:
            opportunities.append(
                f"{best['label']} is top attribution source with {best['revenue']} UZS closed revenue",
            )
            recommendations.append(f"Invest more in {best['label']} channel campaigns")

        if overview.get("total_pipeline_value", 0) > overview.get("total_closed_revenue", 0):
            opportunities.append(
                f"Pipeline {overview['total_pipeline_value']} UZS exceeds closed revenue — conversion upside",
            )

        top_deals = overview.get("deals") or []
        if top_deals:
            top = max(top_deals, key=lambda d: float(d.get("deal_amount") or 0))
            opportunities.append(
                f"Highest deal: {top.get('client_name')} at {top.get('deal_amount')} {top.get('currency')}",
            )

        forecast_comm = overview.get("total_commission_earned") or Decimal("0")
        if overview.get("deals_won", 0) > 0:
            avg = forecast_comm / overview["deals_won"]
            recommendations.append(
                f"Average commission per won deal ~{avg.quantize(Decimal('0.01'))} UZS — use for forecasting",
            )

        summary = (
            f"Closed revenue {overview['total_closed_revenue']} UZS from "
            f"{overview['deals_won']} won deal(s). "
            f"Commission earned {overview['total_commission_earned']} UZS "
            f"({overview['paid_commission']} paid, {overview['pending_commission']} pending)."
        )
        if best:
            summary += f" Best channel: {best['label']}."

        return {
            "summary": summary,
            "risks": risks[:5] or ["Monitor pending commissions and pipeline stagnation"],
            "opportunities": opportunities[:5] or ["Grow pipeline in top attribution channels"],
            "recommendations": recommendations[:5] or ["Track attribution on all new leads"],
            "source": "fallback",
        }
