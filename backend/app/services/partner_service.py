"""Partner & referral network — tracking and commission sharing."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.crm_deal import CrmDeal, CrmDealEvent
from app.models.crm_lead import CrmLead
from app.models.partner import Partner, ReferralLink
from app.models.partner_network import PartnerActivity, PartnerProductInterest
from app.models.product import Product
from app.schemas.partner import PartnerCreate, PartnerUpdate
from app.services.ai_service import _extract_json, _validate_api_key, get_openai

logger = logging.getLogger(__name__)

PARTNER_STATUSES = frozenset({"active", "inactive"})
PARTNER_TYPES = frozenset({
    "distributor", "dealer", "importer", "agent",
    "retail_chain", "construction_company", "other",
})
ACTIVITY_TYPES = frozenset({"call", "email", "meeting", "note", "match", "other"})
_INACTIVE_LEAD_DAYS = 14

_MATCH_SYSTEM = """\
You match B2B distribution partners to products or leads for factory exports in Uzbekistan.
Return ONLY JSON:
{
  "matches": [
    {
      "partner_id": "uuid from directory",
      "score": 0.0 to 1.0,
      "reason": "short explanation"
    }
  ]
}
Rules:
- Return up to 5 best partners sorted by score
- Only use partner_ids from the provided directory
- Consider partner_type, country, industries, and product/lead context
- Never invent partners
"""

_AI_SYSTEM = """\
You analyze partner referral performance for an SMM agency in Uzbekistan.
Return ONLY JSON:
{
  "best_opportunities": ["opportunity 1", "opportunity 2"],
  "inactive_leads": ["lead name — reason", "..."],
  "revenue_forecast": "1-2 sentence forecast based on pipeline",
  "recommended_actions": ["action 1", "action 2", "action 3"]
}

Rules:
- Tracking only — never suggest automatic payments or transfers
- Be specific using partner and lead names from context
- Max 5 items per list except revenue_forecast (string)
"""


def _normalize_code(code: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", code.strip().lower())[:50]


async def _batch_partner_stats(
    db: AsyncSession,
    partner_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    default = {
        "leads_count": 0,
        "won_deals": 0,
        "revenue": Decimal("0"),
        "commission": Decimal("0"),
        "our_commission": Decimal("0"),
    }
    if not partner_ids:
        return {}

    stats: dict[UUID, dict[str, Any]] = {pid: dict(default) for pid in partner_ids}

    leads_r = await db.execute(
        select(CrmLead.partner_id, func.count())
        .where(CrmLead.partner_id.in_(partner_ids))
        .group_by(CrmLead.partner_id)
    )
    for pid, cnt in leads_r.all():
        if pid in stats:
            stats[pid]["leads_count"] = int(cnt or 0)

    deals_r = await db.execute(
        select(
            CrmLead.partner_id,
            func.count(CrmDeal.id),
            func.coalesce(func.sum(CrmDeal.deal_amount), 0),
            func.coalesce(func.sum(CrmDeal.partner_commission_amount), 0),
            func.coalesce(func.sum(CrmDeal.commission_amount), 0),
        )
        .select_from(CrmLead)
        .join(CrmDeal, CrmDeal.lead_id == CrmLead.id)
        .where(CrmLead.partner_id.in_(partner_ids), CrmDeal.status == "won")
        .group_by(CrmLead.partner_id)
    )
    for pid, won, revenue, partner_comm, our_comm in deals_r.all():
        if pid not in stats:
            continue
        stats[pid]["won_deals"] = int(won or 0)
        stats[pid]["revenue"] = Decimal(str(revenue or 0))
        stats[pid]["commission"] = Decimal(str(partner_comm or 0))
        stats[pid]["our_commission"] = Decimal(str(our_comm or 0))

    return stats


async def _partner_stats(db: AsyncSession, partner_id: UUID) -> dict[str, Any]:
    batch = await _batch_partner_stats(db, [partner_id])
    return batch.get(partner_id, {
        "leads_count": 0,
        "won_deals": 0,
        "revenue": Decimal("0"),
        "commission": Decimal("0"),
        "our_commission": Decimal("0"),
    })


def _display_company(partner: Partner) -> str | None:
    return partner.company_name or partner.company


def _serialize_partner(partner: Partner, stats: dict[str, Any]) -> dict[str, Any]:
    links = [
        {
            "id": link.id,
            "partner_id": link.partner_id,
            "code": link.code,
            "description": link.description,
            "created_at": link.created_at,
        }
        for link in (partner.referral_links or [])
    ]
    return {
        "id": partner.id,
        "name": partner.name,
        "company": partner.company,
        "company_name": _display_company(partner),
        "country": partner.country,
        "city": partner.city,
        "partner_type": partner.partner_type,
        "industries_json": partner.industries_json or [],
        "website": partner.website,
        "phone": partner.phone,
        "telegram": partner.telegram,
        "email": partner.email,
        "status": partner.status,
        "notes": partner.notes,
        "referral_links": links,
        "leads_count": stats["leads_count"],
        "won_deals": stats["won_deals"],
        "revenue": stats["revenue"],
        "commission": stats["commission"],
        "created_at": partner.created_at,
        "updated_at": partner.updated_at,
    }


class PartnerService:
    @staticmethod
    async def list_partners(
        db: AsyncSession,
        *,
        status: str | None = None,
        search: str | None = None,
        country: str | None = None,
        partner_type: str | None = None,
        industry: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        query = (
            select(Partner)
            .options(selectinload(Partner.referral_links))
            .order_by(Partner.name)
        )
        count_q = select(func.count()).select_from(Partner)
        if status:
            query = query.where(Partner.status == status)
            count_q = count_q.where(Partner.status == status)
        if country:
            query = query.where(Partner.country == country)
            count_q = count_q.where(Partner.country == country)
        if partner_type:
            query = query.where(Partner.partner_type == partner_type)
            count_q = count_q.where(Partner.partner_type == partner_type)
        if industry:
            filt = Partner.industries_json.cast(String).ilike(f"%{industry}%")
            query = query.where(filt)
            count_q = count_q.where(filt)
        if search:
            term = f"%{search.strip()}%"
            filt = (
                Partner.name.ilike(term)
                | Partner.company.ilike(term)
                | Partner.company_name.ilike(term)
                | Partner.email.ilike(term)
            )
            query = query.where(filt)
            count_q = count_q.where(filt)

        total = (await db.execute(count_q)).scalar_one()

        result = await db.execute(query.offset(skip).limit(limit))
        partners = list(result.scalars().unique().all())
        stats_map = await _batch_partner_stats(db, [p.id for p in partners])

        items = [
            _serialize_partner(partner, stats_map.get(partner.id, {
                "leads_count": 0,
                "won_deals": 0,
                "revenue": Decimal("0"),
                "commission": Decimal("0"),
            }))
            for partner in partners
        ]
        logger.info("[Partner Network] listed: total=%s returned=%s", total, len(items))
        return {"items": items, "total": total}

    @staticmethod
    async def create_partner(db: AsyncSession, data: PartnerCreate) -> dict[str, Any]:
        if data.status not in PARTNER_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid partner status")
        if data.partner_type and data.partner_type not in PARTNER_TYPES:
            raise HTTPException(status_code=400, detail="Invalid partner type")

        partner = Partner(
            name=data.name.strip(),
            company=data.company or data.company_name,
            company_name=(data.company_name or data.company or "").strip() or None,
            country=data.country,
            city=data.city,
            partner_type=data.partner_type,
            industries_json=data.industries_json,
            website=data.website,
            phone=data.phone,
            telegram=data.telegram,
            email=data.email,
            status=data.status,
            notes=data.notes,
        )
        db.add(partner)
        await db.flush()

        if data.referral_code:
            code = _normalize_code(data.referral_code)
            if not code:
                raise HTTPException(status_code=400, detail="Invalid referral code")
            existing = await db.execute(select(ReferralLink).where(ReferralLink.code == code))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=400, detail="Referral code already exists")
            db.add(ReferralLink(
                partner_id=partner.id,
                code=code,
                description=data.referral_description,
            ))

        await db.commit()
        await db.refresh(partner, attribute_names=["referral_links"])
        stats = await _partner_stats(db, partner.id)
        logger.info("[Partner] created: id=%s name=%s", partner.id, partner.name)
        return _serialize_partner(partner, stats)

    @staticmethod
    async def get_partner(db: AsyncSession, partner_id: UUID) -> dict[str, Any]:
        partner = await PartnerService._load_partner(db, partner_id)
        stats = await _partner_stats(db, partner.id)
        return _serialize_partner(partner, stats)

    @staticmethod
    async def update_partner(
        db: AsyncSession,
        partner_id: UUID,
        data: PartnerUpdate,
    ) -> dict[str, Any]:
        partner = await PartnerService._load_partner(db, partner_id)
        payload = data.model_dump(exclude_unset=True)
        if "status" in payload and payload["status"] not in PARTNER_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid partner status")
        if "partner_type" in payload and payload["partner_type"] and payload["partner_type"] not in PARTNER_TYPES:
            raise HTTPException(status_code=400, detail="Invalid partner type")
        if "name" in payload:
            payload["name"] = payload["name"].strip()

        for key, value in payload.items():
            setattr(partner, key, value)
        partner.updated_at = datetime.now(timezone.utc)
        await db.commit()
        await db.refresh(partner, attribute_names=["referral_links"])
        stats = await _partner_stats(db, partner.id)
        return _serialize_partner(partner, stats)

    @staticmethod
    async def delete_partner(db: AsyncSession, partner_id: UUID) -> None:
        partner = await PartnerService._load_partner(db, partner_id)
        await db.delete(partner)
        await db.commit()
        logger.info("[Partner] deleted: id=%s", partner_id)

    @staticmethod
    async def performance(db: AsyncSession, partner_id: UUID) -> dict[str, Any]:
        await PartnerService._load_partner(db, partner_id)
        stats = await _partner_stats(db, partner_id)

        leads_r = await db.execute(
            select(CrmLead)
            .where(CrmLead.partner_id == partner_id)
            .order_by(CrmLead.created_at.desc())
        )
        leads = list(leads_r.scalars().all())
        lead_ids = [l.id for l in leads]

        deal_items: list[dict[str, Any]] = []
        timeline: list[dict[str, Any]] = []

        if lead_ids:
            deals_r = await db.execute(
                select(CrmDeal)
                .where(CrmDeal.lead_id.in_(lead_ids))
                .order_by(CrmDeal.updated_at.desc())
            )
            deals = list(deals_r.scalars().all())
            deal_ids = [d.id for d in deals]

            for deal in deals:
                deal_items.append({
                    "id": deal.id,
                    "title": deal.title,
                    "status": deal.status,
                    "deal_amount": deal.deal_amount,
                    "currency": deal.currency or "UZS",
                    "partner_commission_amount": deal.partner_commission_amount,
                    "commission_amount": deal.commission_amount,
                    "updated_at": deal.updated_at,
                })

            if deal_ids:
                events_r = await db.execute(
                    select(CrmDealEvent, CrmDeal)
                    .join(CrmDeal, CrmDealEvent.deal_id == CrmDeal.id)
                    .where(CrmDealEvent.deal_id.in_(deal_ids))
                    .order_by(CrmDealEvent.created_at.desc())
                    .limit(30)
                )
                for event, deal in events_r.all():
                    timeline.append({
                        "id": event.id,
                        "deal_id": deal.id,
                        "deal_title": deal.title,
                        "event_type": event.event_type,
                        "title": event.title,
                        "created_at": event.created_at,
                    })

        return {
            "partner_id": partner_id,
            "leads": stats["leads_count"],
            "won_deals": stats["won_deals"],
            "revenue": stats["revenue"],
            "commission": stats["commission"],
            "our_commission": stats["our_commission"],
            "lead_items": [
                {
                    "id": l.id,
                    "name": l.name,
                    "company": l.company,
                    "status": l.status,
                    "estimated_value": l.estimated_value,
                    "referral_code": l.referral_code,
                    "created_at": l.created_at,
                }
                for l in leads
            ],
            "deal_items": deal_items,
            "timeline": timeline,
        }

    @staticmethod
    async def ai_insights(db: AsyncSession, partner_id: UUID) -> dict[str, Any]:
        perf = await PartnerService.performance(db, partner_id)
        partner = await PartnerService._load_partner(db, partner_id)
        context = PartnerService._build_ai_context(partner, perf)

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                result = PartnerService._heuristic_insights(partner, perf)
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
                    max_tokens=700,
                    response_format={"type": "json_object"},
                )
                parsed = _extract_json(response.choices[0].message.content or "{}")
                result = {
                    "best_opportunities": PartnerService._str_list(parsed.get("best_opportunities"), 5),
                    "inactive_leads": PartnerService._str_list(parsed.get("inactive_leads"), 5),
                    "revenue_forecast": str(parsed.get("revenue_forecast") or "")[:1000],
                    "recommended_actions": PartnerService._str_list(parsed.get("recommended_actions"), 5),
                    "source": "ai",
                }
        except Exception as exc:
            logger.warning("[Partner] AI insights fallback: partner=%s error=%s", partner_id, exc)
            result = PartnerService._heuristic_insights(partner, perf)

        logger.info("[Partner] ai-insights: partner=%s source=%s", partner_id, result["source"])
        return result

    @staticmethod
    async def resolve_referral_code(
        db: AsyncSession,
        code: str | None,
    ) -> tuple[UUID | None, str | None]:
        if not code or not code.strip():
            return None, None
        normalized = _normalize_code(code)
        if not normalized:
            return None, None
        result = await db.execute(
            select(ReferralLink)
            .options(selectinload(ReferralLink.partner))
            .where(ReferralLink.code == normalized)
        )
        link = result.scalar_one_or_none()
        if not link:
            return None, normalized
        if link.partner and link.partner.status != "active":
            return None, normalized
        return link.partner_id, normalized

    @staticmethod
    async def _load_partner(db: AsyncSession, partner_id: UUID) -> Partner:
        result = await db.execute(
            select(Partner)
            .options(selectinload(Partner.referral_links))
            .where(Partner.id == partner_id)
        )
        partner = result.scalar_one_or_none()
        if not partner:
            raise HTTPException(status_code=404, detail="Partner not found")
        return partner

    @staticmethod
    def _build_ai_context(partner: Partner, perf: dict[str, Any]) -> str:
        lines = [
            f"PARTNER: {partner.name} ({partner.company or 'no company'}) status={partner.status}",
            f"Leads: {perf['leads']}, Won: {perf['won_deals']}, Revenue: {perf['revenue']}, "
            f"Partner commission: {perf['commission']}",
            "",
            "LEADS:",
        ]
        for lead in perf.get("lead_items") or []:
            lines.append(
                f"- {lead['name']} status={lead['status']} value={lead.get('estimated_value') or 'TBD'}",
            )
        lines.append("")
        lines.append("DEALS:")
        for deal in perf.get("deal_items") or []:
            lines.append(f"- {deal['title']} status={deal['status']} amount={deal.get('deal_amount')}")
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
    def _heuristic_insights(partner: Partner, perf: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=_INACTIVE_LEAD_DAYS)

        opportunities: list[str] = []
        inactive: list[str] = []
        actions: list[str] = []

        for lead in perf.get("lead_items") or []:
            status = lead.get("status", "")
            if status in ("qualified", "proposal_sent", "negotiation"):
                opportunities.append(
                    f"Follow up {lead['name']} — in {status.replace('_', ' ')} stage",
                )
            created = lead.get("created_at")
            if status not in ("won", "lost") and created:
                ts = created if created.tzinfo else created.replace(tzinfo=timezone.utc)
                if ts < cutoff:
                    inactive.append(f"{lead['name']} — no progress in {_INACTIVE_LEAD_DAYS}+ days")

        pipeline_value = sum(
            float(l.get("estimated_value") or 0)
            for l in (perf.get("lead_items") or [])
            if l.get("status") not in ("won", "lost")
        )
        avg_deal = float(perf["revenue"]) / max(perf["won_deals"], 1)
        forecast = (
            f"Pipeline ~{pipeline_value:,.0f} UZS across open leads. "
            f"Historical avg won deal ~{avg_deal:,.0f} UZS."
        )

        if perf["leads"] == 0:
            actions.append("Share referral link with partner to generate leads")
        if inactive:
            actions.append("Re-engage inactive referred leads manually")
        if perf["won_deals"] > 0:
            actions.append("Thank partner for won deals — strengthen relationship")
        if not actions:
            actions.append("Review partner lead quality and follow-up cadence")

        return {
            "best_opportunities": opportunities[:5] or ["No hot leads — nurture early-stage referrals"],
            "inactive_leads": inactive[:5] or ["No inactive leads flagged"],
            "revenue_forecast": forecast,
            "recommended_actions": actions[:5],
            "source": "fallback",
        }

    @staticmethod
    async def list_filters(db: AsyncSession) -> dict[str, list[str]]:
        countries_r = await db.execute(
            select(Partner.country)
            .where(Partner.country.isnot(None), Partner.country != "")
            .distinct()
            .order_by(Partner.country)
        )
        industries: set[str] = set()
        ind_r = await db.execute(
            select(Partner.industries_json).where(Partner.industries_json.isnot(None))
        )
        for row in ind_r.scalars().all():
            if isinstance(row, list):
                industries.update(str(x) for x in row if x)
        return {
            "countries": [c for c in countries_r.scalars().all() if c],
            "partner_types": sorted(PARTNER_TYPES),
            "industries": sorted(industries),
        }

    @staticmethod
    async def get_hub(db: AsyncSession, partner_id: UUID) -> dict[str, Any]:
        partner = await PartnerService._load_partner(db, partner_id)
        stats = await _partner_stats(db, partner.id)

        act_r = await db.execute(
            select(PartnerActivity)
            .where(PartnerActivity.partner_id == partner_id)
            .order_by(PartnerActivity.created_at.desc())
            .limit(50)
        )
        activities = [
            {
                "id": a.id,
                "partner_id": a.partner_id,
                "activity_type": a.activity_type,
                "description": a.description,
                "created_at": a.created_at,
            }
            for a in act_r.scalars().all()
        ]

        prod_r = await db.execute(
            select(PartnerProductInterest, Product)
            .join(Product, Product.id == PartnerProductInterest.product_id)
            .where(PartnerProductInterest.partner_id == partner_id)
            .order_by(PartnerProductInterest.interest_score.desc().nullslast())
            .limit(30)
        )
        related_products = [
            {
                "interest_id": interest.id,
                "product_id": product.id,
                "name": product.name,
                "category": product.category,
                "unit_price": product.unit_price,
                "currency": product.currency,
                "interest_score": float(interest.interest_score) if interest.interest_score is not None else None,
                "notes": interest.notes,
            }
            for interest, product in prod_r.all()
        ]

        leads_r = await db.execute(
            select(CrmLead)
            .where(CrmLead.partner_id == partner_id)
            .order_by(CrmLead.created_at.desc())
            .limit(30)
        )
        referred_leads = list(leads_r.scalars().all())

        interest_blob = " ".join(filter(None, [
            partner.name,
            _display_company(partner) or "",
            " ".join(partner.industries_json or []),
            partner.partner_type or "",
        ])).lower()
        matched_leads: list[dict[str, Any]] = []
        if interest_blob.strip():
            all_leads_r = await db.execute(
                select(CrmLead)
                .where(CrmLead.partner_id.is_(None))
                .order_by(CrmLead.created_at.desc())
                .limit(100)
            )
            for lead in all_leads_r.scalars().all():
                text = " ".join(filter(None, [lead.interest, lead.notes, lead.company, lead.name])).lower()
                tokens = [t for t in re.split(r"\W+", interest_blob) if len(t) > 3]
                hits = sum(1 for t in tokens if t in text)
                if hits >= 1:
                    matched_leads.append({
                        "id": lead.id,
                        "name": lead.name,
                        "company": lead.company,
                        "status": lead.status,
                        "interest": lead.interest,
                        "match_hits": hits,
                    })
            matched_leads.sort(key=lambda x: x["match_hits"], reverse=True)
            matched_leads = matched_leads[:10]

        logger.info(
            "[Partner Network] hub: partner=%s activities=%s products=%s leads=%s",
            partner_id, len(activities), len(related_products), len(referred_leads),
        )
        return {
            "id": partner.id,
            "name": partner.name,
            "company_name": _display_company(partner),
            "country": partner.country,
            "city": partner.city,
            "partner_type": partner.partner_type,
            "industries_json": partner.industries_json or [],
            "website": partner.website,
            "phone": partner.phone,
            "email": partner.email,
            "status": partner.status,
            "notes": partner.notes,
            "leads_count": stats["leads_count"],
            "won_deals": stats["won_deals"],
            "revenue": stats["revenue"],
            "commission": stats["commission"],
            "activities": activities,
            "related_products": related_products,
            "related_leads": [
                {
                    "id": l.id,
                    "name": l.name,
                    "company": l.company,
                    "status": l.status,
                    "interest": l.interest,
                    "referral_code": l.referral_code,
                    "created_at": l.created_at,
                }
                for l in referred_leads
            ],
            "matched_leads": matched_leads,
        }

    @staticmethod
    async def add_activity(
        db: AsyncSession,
        partner_id: UUID,
        *,
        activity_type: str,
        description: str,
    ) -> dict[str, Any]:
        if activity_type not in ACTIVITY_TYPES:
            raise HTTPException(status_code=400, detail="Invalid activity type")
        await PartnerService._load_partner(db, partner_id)
        activity = PartnerActivity(
            partner_id=partner_id,
            activity_type=activity_type,
            description=description.strip(),
        )
        db.add(activity)
        await db.commit()
        await db.refresh(activity)
        logger.info("[Partner Network] activity: partner=%s type=%s", partner_id, activity_type)
        return {
            "id": activity.id,
            "partner_id": activity.partner_id,
            "activity_type": activity.activity_type,
            "description": activity.description,
            "created_at": activity.created_at,
        }

    @staticmethod
    def _keyword_partner_score(context: str, partner: Partner) -> tuple[float, str]:
        blob = " ".join(filter(None, [
            partner.name,
            _display_company(partner),
            partner.country,
            partner.city,
            partner.partner_type,
            " ".join(partner.industries_json or []),
            partner.notes,
        ])).lower()
        tokens = [t for t in re.split(r"\W+", context.lower()) if len(t) > 2]
        if not tokens or not blob:
            return 0.0, "No overlap"
        hits = sum(1 for t in tokens if t in blob)
        if hits == 0:
            return 0.0, "No keyword overlap"
        return min(0.92, 0.3 + hits * 0.1), f"Matched {hits} keyword(s)"

    @staticmethod
    async def _run_partner_match(
        db: AsyncSession,
        *,
        context: str,
        partners: list[Partner],
    ) -> tuple[list[dict[str, Any]], bool]:
        if not partners:
            return [], False
        demo_mode = False
        matches: list[dict[str, Any]] = []
        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise ValueError("AI unavailable")
            _validate_api_key()
            directory = [
                {
                    "partner_id": str(p.id),
                    "name": p.name,
                    "company_name": _display_company(p),
                    "partner_type": p.partner_type,
                    "country": p.country,
                    "city": p.city,
                    "industries": p.industries_json or [],
                }
                for p in partners
            ]
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _MATCH_SYSTEM},
                    {
                        "role": "user",
                        "content": f"Context:\n{context}\n\nPartner directory:\n{json.dumps(directory, ensure_ascii=False)}",
                    },
                ],
                temperature=0.2,
                max_tokens=800,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            by_id = {str(p.id): p for p in partners}
            for m in (parsed.get("matches") or [])[:5]:
                pid = str(m.get("partner_id", ""))
                partner = by_id.get(pid)
                if not partner:
                    continue
                score = float(m.get("score") or 0)
                matches.append({
                    "partner_id": partner.id,
                    "name": partner.name,
                    "company_name": _display_company(partner),
                    "partner_type": partner.partner_type,
                    "country": partner.country,
                    "score": max(0.0, min(1.0, score)),
                    "reason": str(m.get("reason") or "AI match"),
                })
        except Exception as exc:
            demo_mode = True
            logger.info("[Partner Match] fallback: %s", exc)
            scored = []
            for p in partners:
                score, reason = PartnerService._keyword_partner_score(context, p)
                if score > 0:
                    scored.append((score, reason, p))
            scored.sort(key=lambda x: x[0], reverse=True)
            for score, reason, p in scored[:5]:
                matches.append({
                    "partner_id": p.id,
                    "name": p.name,
                    "company_name": _display_company(p),
                    "partner_type": p.partner_type,
                    "country": p.country,
                    "score": round(score, 2),
                    "reason": reason,
                })
        matches.sort(key=lambda x: x["score"], reverse=True)
        return matches, demo_mode

    @staticmethod
    async def match_product(db: AsyncSession, product_id: UUID) -> dict[str, Any]:
        prod_r = await db.execute(select(Product).where(Product.id == product_id))
        product = prod_r.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        partners_r = await db.execute(
            select(Partner).where(Partner.status == "active").order_by(Partner.name).limit(200)
        )
        partners = list(partners_r.scalars().all())
        context = (
            f"Product: {product.name}\n"
            f"Category: {product.category or ''}\n"
            f"Description: {product.description or ''}\n"
            f"MOQ: {product.moq}\n"
            f"Price: {product.unit_price} {product.currency}"
        )
        logger.info("[Partner Match] product=%s partners=%s", product_id, len(partners))
        matches, demo_mode = await PartnerService._run_partner_match(db, context=context, partners=partners)

        for m in matches[:3]:
            existing = await db.execute(
                select(PartnerProductInterest).where(
                    PartnerProductInterest.partner_id == m["partner_id"],
                    PartnerProductInterest.product_id == product_id,
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                row.interest_score = m["score"]
                row.notes = m["reason"]
            else:
                db.add(PartnerProductInterest(
                    partner_id=m["partner_id"],
                    product_id=product_id,
                    interest_score=m["score"],
                    notes=m["reason"],
                ))
        await db.commit()
        logger.info("[Partner Match] product=%s matches=%s demo=%s", product_id, len(matches), demo_mode)
        return {
            "product_id": product_id,
            "product_name": product.name,
            "query_context": context,
            "matches": matches,
            "demo_mode": demo_mode,
        }

    @staticmethod
    async def match_lead(db: AsyncSession, lead_id: UUID) -> dict[str, Any]:
        lead_r = await db.execute(select(CrmLead).where(CrmLead.id == lead_id))
        lead = lead_r.scalar_one_or_none()
        if not lead:
            raise HTTPException(status_code=404, detail="Lead not found")

        partners_r = await db.execute(
            select(Partner).where(Partner.status == "active").order_by(Partner.name).limit(200)
        )
        partners = list(partners_r.scalars().all())
        context = (
            f"Lead: {lead.name}\n"
            f"Company: {lead.company or ''}\n"
            f"Interest: {lead.interest or ''}\n"
            f"Notes: {lead.notes or ''}\n"
            f"Status: {lead.status}"
        )
        logger.info("[Partner Match] lead=%s partners=%s", lead_id, len(partners))
        matches, demo_mode = await PartnerService._run_partner_match(db, context=context, partners=partners)
        logger.info("[Partner Match] lead=%s matches=%s demo=%s", lead_id, len(matches), demo_mode)
        return {
            "lead_id": lead_id,
            "lead_name": lead.name,
            "query_context": context,
            "matches": matches,
            "demo_mode": demo_mode,
        }
