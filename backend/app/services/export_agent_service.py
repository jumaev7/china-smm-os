"""Export Agent — advisory export opportunity analysis (no outreach)."""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.export_agent import ExportInsight, ExportOpportunity
from app.models.partner import Partner
from app.models.partner_network import PartnerActivity, PartnerProductInterest
from app.models.product import Product
from app.services.ai_service import _extract_json, _validate_api_key, get_openai

logger = logging.getLogger(__name__)

DEMAND_LEVELS = frozenset({"low", "medium", "high", "very_high"})

_DEFAULT_COUNTRIES = (
    "Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan", "Turkmenistan",
    "Russia", "China", "Turkey", "UAE", "Saudi Arabia", "India", "Pakistan",
    "Germany", "Poland", "USA",
)

_PARTNER_TYPE_CHANNELS: dict[str, list[str]] = {
    "distributor": ["B2B distributor network", "Trade shows", "Industry associations"],
    "dealer": ["Regional dealers", "Local retail partnerships", "Field sales"],
    "importer": ["Import agents", "Customs brokers", "Wholesale importers"],
    "agent": ["Commission agents", "Trade missions", "Embassy trade desks"],
    "retail_chain": ["Retail chain buyers", "Category managers", "Private label"],
    "construction_company": ["Project tenders", "Contractor networks", "Spec-in sales"],
    "other": ["Direct B2B outreach", "LinkedIn", "Industry directories"],
}

_ANALYZE_SYSTEM = """\
You analyze B2B export potential for factory products in Central Asia and nearby markets.
Return ONLY JSON:
{
  "market_summary": "2-3 sentences on why this product is promising for export",
  "countries": [
    {
      "country": "string",
      "demand_level": "low|medium|high|very_high",
      "market_summary": "1-2 sentences for this country",
      "recommended_partner_types": ["distributor", "dealer", "importer", "agent", "retail_chain", "construction_company", "other"],
      "recommended_channels": ["channel name", "..."]
    }
  ],
  "insights": [
    {
      "insight_type": "market|buyer|channel|risk",
      "title": "short title",
      "description": "actionable advisory note — no outreach instructions",
      "confidence": 0.0 to 1.0
    }
  ]
}
Rules:
- Advisory only — never suggest automatic messaging or outreach
- Return up to 5 countries sorted by export potential
- Return up to 4 insights
- Base recommendations on product category, MOQ, price, and partner/lead signals provided
"""


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if len(t) >= 3}


def _text_overlap(a: str, b: str) -> float:
    ta, tb = _tokenize(a), _tokenize(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / max(len(ta), 1)


def _product_blob(product: Product) -> str:
    parts = [product.name, product.category or "", product.description or ""]
    if product.attributes_json:
        parts.extend(str(v) for v in product.attributes_json.values())
    return " ".join(parts)


def _lead_matches_product(lead: CrmLead, product: Product) -> bool:
    blob = " ".join(filter(None, [lead.interest, lead.notes, lead.company, lead.name]))
    return _text_overlap(blob, _product_blob(product)) >= 0.15


def _partner_matches_product(partner: Partner, product: Product) -> bool:
    industries = " ".join(partner.industries_json or [])
    blob = " ".join(filter(None, [industries, partner.notes or "", partner.company_name or partner.company or ""]))
    cat = product.category or ""
    if cat and cat.lower() in blob.lower():
        return True
    return _text_overlap(blob, _product_blob(product)) >= 0.12


def _compute_score(
    *,
    partner_count: int,
    lead_count: int,
    interest_count: int,
    activity_count: int,
    won_deals: int,
) -> tuple[float, dict[str, Any]]:
    partner_pts = min(30.0, partner_count * 6.0)
    lead_pts = min(25.0, lead_count * 5.0)
    industry_pts = min(25.0, interest_count * 8.0 + activity_count * 2.0)
    deal_pts = min(20.0, won_deals * 10.0)
    total = round(min(100.0, partner_pts + lead_pts + industry_pts + deal_pts), 1)
    return total, {
        "partner_count": partner_count,
        "lead_count": lead_count,
        "industry_activity": interest_count + activity_count,
        "historical_deals": won_deals,
        "breakdown": {
            "partners": round(partner_pts, 1),
            "leads": round(lead_pts, 1),
            "industry": round(industry_pts, 1),
            "deals": round(deal_pts, 1),
        },
    }


def _default_channels(partner_types: list[str]) -> list[str]:
    channels: list[str] = []
    for pt in partner_types:
        for ch in _PARTNER_TYPE_CHANNELS.get(pt, _PARTNER_TYPE_CHANNELS["other"]):
            if ch not in channels:
                channels.append(ch)
    return channels[:5] or ["B2B directories", "Trade fairs", "Partner referrals"]


def _opp_to_dict(opp: ExportOpportunity, product: Product | None = None, client: Client | None = None) -> dict[str, Any]:
    return {
        "id": opp.id,
        "client_id": opp.client_id,
        "product_id": opp.product_id,
        "country": opp.country,
        "score": float(opp.score or 0),
        "market_summary": opp.market_summary,
        "demand_level": opp.demand_level,
        "recommended_partner_types_json": opp.recommended_partner_types_json or [],
        "recommended_channels_json": opp.recommended_channels_json or [],
        "created_at": opp.created_at,
        "product_name": product.name if product else None,
        "product_category": product.category if product else None,
        "company_name": client.name if client else None,
    }


class ExportAgentService:
    @staticmethod
    async def list_opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        product_id: UUID | None = None,
        country: str | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> dict[str, Any]:
        q = (
            select(ExportOpportunity)
            .options(selectinload(ExportOpportunity.product), selectinload(ExportOpportunity.client))
            .order_by(ExportOpportunity.score.desc(), ExportOpportunity.created_at.desc())
        )
        count_q = select(func.count()).select_from(ExportOpportunity)
        if client_id:
            q = q.where(ExportOpportunity.client_id == client_id)
            count_q = count_q.where(ExportOpportunity.client_id == client_id)
        if product_id:
            q = q.where(ExportOpportunity.product_id == product_id)
            count_q = count_q.where(ExportOpportunity.product_id == product_id)
        if country:
            q = q.where(ExportOpportunity.country.ilike(country))
            count_q = count_q.where(ExportOpportunity.country.ilike(country))

        total_r = await db.execute(count_q)
        total = total_r.scalar_one()
        rows_r = await db.execute(q.offset(skip).limit(limit))
        rows = list(rows_r.scalars().all())
        items = [_opp_to_dict(o, o.product, o.client) for o in rows]
        logger.info("[Export Agent] listed: total=%s returned=%s", total, len(items))
        return {"items": items, "total": total}

    @staticmethod
    async def get_opportunity(db: AsyncSession, opportunity_id: UUID) -> dict[str, Any]:
        r = await db.execute(
            select(ExportOpportunity)
            .options(selectinload(ExportOpportunity.product), selectinload(ExportOpportunity.client))
            .where(ExportOpportunity.id == opportunity_id)
        )
        opp = r.scalar_one_or_none()
        if not opp:
            raise HTTPException(status_code=404, detail="Export opportunity not found")

        insights_r = await db.execute(
            select(ExportInsight)
            .where(ExportInsight.product_id == opp.product_id)
            .order_by(ExportInsight.created_at.desc())
            .limit(20)
        )
        insights = list(insights_r.scalars().all())

        partners_r = await db.execute(
            select(Partner).where(Partner.status == "active", Partner.country.ilike(opp.country))
        )
        partners = list(partners_r.scalars().all())
        leads_r = await db.execute(
            select(CrmLead).where(CrmLead.client_id == opp.client_id)
        )
        leads = [l for l in leads_r.scalars().all() if _lead_matches_product(l, opp.product)]
        interest_r = await db.execute(
            select(func.count()).select_from(PartnerProductInterest).where(
                PartnerProductInterest.product_id == opp.product_id
            )
        )
        activity_count = 0
        if partners:
            activity_r = await db.execute(
                select(func.count()).select_from(PartnerActivity).where(
                    PartnerActivity.partner_id.in_([p.id for p in partners])
                )
            )
            activity_count = int(activity_r.scalar_one() or 0)
        deals_r = await db.execute(
            select(func.count()).select_from(CrmDeal).where(
                CrmDeal.client_id == opp.client_id,
                CrmDeal.status.in_(("won", "closed_won")),
            )
        )
        score, factors = _compute_score(
            partner_count=len([p for p in partners if _partner_matches_product(p, opp.product)]),
            lead_count=len(leads),
            interest_count=int(interest_r.scalar_one() or 0),
            activity_count=activity_count,
            won_deals=int(deals_r.scalar_one() or 0),
        )
        data = _opp_to_dict(opp, opp.product, opp.client)
        data["insights"] = [
            {
                "id": i.id,
                "product_id": i.product_id,
                "insight_type": i.insight_type,
                "title": i.title,
                "description": i.description,
                "confidence": float(i.confidence) if i.confidence is not None else None,
                "created_at": i.created_at,
            }
            for i in insights
        ]
        data["score_factors"] = {**factors, "computed_score": score}
        return data

    @staticmethod
    async def dashboard(db: AsyncSession, *, limit: int = 10) -> dict[str, Any]:
        top_r = await db.execute(
            select(ExportOpportunity)
            .options(selectinload(ExportOpportunity.product), selectinload(ExportOpportunity.client))
            .order_by(ExportOpportunity.score.desc(), ExportOpportunity.created_at.desc())
            .limit(limit)
        )
        top = list(top_r.scalars().all())

        all_r = await db.execute(select(ExportOpportunity))
        all_opps = list(all_r.scalars().all())

        by_country: dict[str, list[float]] = defaultdict(list)
        for o in all_opps:
            by_country[o.country].append(float(o.score or 0))

        country_rankings = sorted(
            [
                {
                    "country": c,
                    "opportunity_count": len(scores),
                    "avg_score": round(sum(scores) / len(scores), 1),
                    "max_score": round(max(scores), 1),
                }
                for c, scores in by_country.items()
            ],
            key=lambda x: x["max_score"],
            reverse=True,
        )[:10]

        product_ids = {o.product_id for o in all_opps}
        avg_score = round(sum(float(o.score or 0) for o in all_opps) / len(all_opps), 1) if all_opps else 0.0

        from app.services.buyer_finder_service import BuyerFinderService
        top_buyers = await BuyerFinderService.top_opportunities(db, limit=limit)

        logger.info("[Export Agent] dashboard: opportunities=%s countries=%s", len(all_opps), len(country_rankings))
        return {
            "top_opportunities": [_opp_to_dict(o, o.product, o.client) for o in top],
            "country_rankings": country_rankings,
            "total_opportunities": len(all_opps),
            "avg_score": avg_score,
            "products_analyzed": len(product_ids),
            "top_buyer_opportunities": top_buyers,
        }

    @staticmethod
    async def _gather_signals(db: AsyncSession, product: Product) -> dict[str, Any]:
        partners_r = await db.execute(select(Partner).where(Partner.status == "active"))
        partners = list(partners_r.scalars().all())

        leads_r = await db.execute(select(CrmLead).where(CrmLead.client_id == product.client_id))
        leads = list(leads_r.scalars().all())

        interests_r = await db.execute(
            select(PartnerProductInterest).where(PartnerProductInterest.product_id == product.id)
        )
        interests = list(interests_r.scalars().all())

        deals_r = await db.execute(
            select(CrmDeal).where(
                CrmDeal.client_id == product.client_id,
                CrmDeal.status.in_(("won", "closed_won")),
            )
        )
        won_deals = list(deals_r.scalars().all())

        by_country: dict[str, dict[str, int]] = defaultdict(lambda: {
            "partners": 0, "leads": 0, "interests": 0, "activities": 0,
        })
        for p in partners:
            if p.country and _partner_matches_product(p, product):
                by_country[p.country]["partners"] += 1
        for l in leads:
            if _lead_matches_product(l, product):
                for c in by_country:
                    by_country[c]["leads"] += 1
        for _ in interests:
            for c in by_country:
                by_country[c]["interests"] += 1

        partner_countries = Counter(p.country for p in partners if p.country)
        candidate_countries = list(dict.fromkeys(
            list(partner_countries.keys()) + list(_DEFAULT_COUNTRIES)
        ))[:12]

        return {
            "partners": partners,
            "leads": leads,
            "interests": interests,
            "won_deals": won_deals,
            "by_country": dict(by_country),
            "candidate_countries": candidate_countries,
        }

    @staticmethod
    async def _ai_analyze(product: Product, signals: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        demo_mode = False
        partner_summary = [
            {
                "country": p.country,
                "type": p.partner_type,
                "industries": p.industries_json or [],
            }
            for p in signals["partners"][:40]
            if p.country
        ]
        lead_summary = [
            {"name": l.name, "interest": l.interest, "status": l.status}
            for l in signals["leads"][:20]
            if _lead_matches_product(l, product)
        ]
        context = {
            "product": {
                "name": product.name,
                "category": product.category,
                "description": product.description,
                "moq": product.moq,
                "unit_price": str(product.unit_price) if product.unit_price else None,
                "currency": product.currency,
            },
            "partner_count": len(signals["partners"]),
            "matching_leads": len(lead_summary),
            "product_interests": len(signals["interests"]),
            "won_deals": len(signals["won_deals"]),
            "partners_by_country": partner_summary,
            "leads": lead_summary,
            "candidate_countries": signals["candidate_countries"],
        }
        try:
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _ANALYZE_SYSTEM},
                    {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
                ],
                temperature=0.25,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
        except Exception as exc:
            demo_mode = True
            logger.info("[Export Analysis] fallback: %s", exc)
            parsed = ExportAgentService._fallback_analysis(product, signals)
        return parsed, demo_mode

    @staticmethod
    def _fallback_analysis(product: Product, signals: dict[str, Any]) -> dict[str, Any]:
        by_country = signals.get("by_country") or {}
        countries_out = []
        for country in signals["candidate_countries"][:5]:
            stats = by_country.get(country, {"partners": 0, "leads": 0, "interests": 0, "activities": 0})
            score, _ = _compute_score(
                partner_count=stats["partners"],
                lead_count=stats["leads"] or (1 if signals["leads"] else 0),
                interest_count=stats["interests"] or len(signals["interests"]),
                activity_count=stats["activities"],
                won_deals=len(signals["won_deals"]),
            )
            demand = "low"
            if score >= 75:
                demand = "very_high"
            elif score >= 55:
                demand = "high"
            elif score >= 35:
                demand = "medium"
            partner_types = ["distributor", "importer"]
            if (product.category or "").lower() in ("construction", "building", "materials"):
                partner_types = ["construction_company", "distributor"]
            countries_out.append({
                "country": country,
                "demand_level": demand,
                "market_summary": f"Score {score}/100 based on {stats['partners']} partners and catalog signals.",
                "recommended_partner_types": partner_types,
                "recommended_channels": _default_channels(partner_types),
            })
        return {
            "market_summary": (
                f"{product.name} shows export potential based on partner network density, "
                f"{len(signals['interests'])} product interests, and {len(signals['won_deals'])} historical wins."
            ),
            "countries": countries_out,
            "insights": [
                {
                    "insight_type": "market",
                    "title": "Partner network coverage",
                    "description": f"{len(signals['partners'])} active partners in directory — prioritize countries with distributor presence.",
                    "confidence": 0.65,
                },
                {
                    "insight_type": "buyer",
                    "title": "CRM lead signals",
                    "description": f"{len([l for l in signals['leads'] if _lead_matches_product(l, product)])} leads show related interest — review before targeting new markets.",
                    "confidence": 0.6,
                },
            ],
        }

    @staticmethod
    async def analyze_product(db: AsyncSession, product_id: UUID) -> dict[str, Any]:
        prod_r = await db.execute(
            select(Product).options(selectinload(Product.client)).where(Product.id == product_id)
        )
        product = prod_r.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        logger.info("[Export Analysis] start: product=%s", product_id)
        signals = await ExportAgentService._gather_signals(db, product)
        parsed, demo_mode = await ExportAgentService._ai_analyze(product, signals)

        market_summary = str(parsed.get("market_summary") or "")
        countries_data = parsed.get("countries") or []
        insights_data = parsed.get("insights") or []

        opportunities: list[dict[str, Any]] = []
        for cd in countries_data[:5]:
            country = str(cd.get("country") or "").strip()
            if not country:
                continue
            stats = signals["by_country"].get(country, {"partners": 0, "leads": 0, "interests": 0, "activities": 0})
            score, _ = _compute_score(
                partner_count=stats["partners"] or sum(
                    1 for p in signals["partners"]
                    if p.country and p.country.lower() == country.lower() and _partner_matches_product(p, product)
                ),
                lead_count=stats["leads"] or len([
                    l for l in signals["leads"] if _lead_matches_product(l, product)
                ]),
                interest_count=stats["interests"] or len(signals["interests"]),
                activity_count=stats["activities"],
                won_deals=len(signals["won_deals"]),
            )
            ai_boost = {"low": 0, "medium": 5, "high": 12, "very_high": 18}.get(
                str(cd.get("demand_level") or "medium"), 5
            )
            score = round(min(100.0, score + ai_boost), 1)
            partner_types = cd.get("recommended_partner_types") or ["distributor", "importer"]
            channels = cd.get("recommended_channels") or _default_channels(partner_types)
            demand = cd.get("demand_level") or "medium"
            if demand not in DEMAND_LEVELS:
                demand = "medium"

            existing_r = await db.execute(
                select(ExportOpportunity).where(
                    ExportOpportunity.product_id == product_id,
                    ExportOpportunity.country.ilike(country),
                )
            )
            row = existing_r.scalar_one_or_none()
            if row:
                row.score = score
                row.market_summary = str(cd.get("market_summary") or market_summary)
                row.demand_level = demand
                row.recommended_partner_types_json = partner_types
                row.recommended_channels_json = channels
                opp = row
            else:
                opp = ExportOpportunity(
                    client_id=product.client_id,
                    product_id=product_id,
                    country=country,
                    score=score,
                    market_summary=str(cd.get("market_summary") or market_summary),
                    demand_level=demand,
                    recommended_partner_types_json=partner_types,
                    recommended_channels_json=channels,
                )
                db.add(opp)
            await db.flush()
            opportunities.append(_opp_to_dict(opp, product, product.client))

        await db.execute(
            ExportInsight.__table__.delete().where(ExportInsight.product_id == product_id)
        )
        insights_out: list[dict[str, Any]] = []
        for ins in insights_data[:4]:
            insight = ExportInsight(
                product_id=product_id,
                insight_type=str(ins.get("insight_type") or "market"),
                title=str(ins.get("title") or "Export insight"),
                description=str(ins.get("description") or ""),
                confidence=float(ins.get("confidence") or 0.5),
            )
            db.add(insight)
            await db.flush()
            insights_out.append({
                "id": insight.id,
                "product_id": insight.product_id,
                "insight_type": insight.insight_type,
                "title": insight.title,
                "description": insight.description,
                "confidence": float(insight.confidence) if insight.confidence is not None else None,
                "created_at": insight.created_at,
            })

        await db.commit()
        opportunities.sort(key=lambda x: x["score"], reverse=True)
        overall = round(sum(o["score"] for o in opportunities) / len(opportunities), 1) if opportunities else 0.0

        top_countries = [o["country"] for o in opportunities[:3]]
        type_counter: Counter[str] = Counter()
        channel_counter: Counter[str] = Counter()
        for o in opportunities:
            for t in o.get("recommended_partner_types_json") or []:
                type_counter[t] += 1
            for c in o.get("recommended_channels_json") or []:
                channel_counter[c] += 1

        logger.info(
            "[Export Analysis] product=%s opportunities=%s demo=%s score=%s",
            product_id, len(opportunities), demo_mode, overall,
        )
        return {
            "product_id": product_id,
            "product_name": product.name,
            "overall_score": overall,
            "market_summary": market_summary,
            "top_countries": top_countries,
            "top_partner_types": [t for t, _ in type_counter.most_common(3)],
            "top_channels": [c for c, _ in channel_counter.most_common(3)],
            "opportunities": opportunities,
            "insights": insights_out,
            "demo_mode": demo_mode,
        }
