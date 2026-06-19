"""AI Buyer Finder — advisory buyer recommendations (no outreach)."""
from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.buyer_recommendation import BuyerRecommendation
from app.models.communication import CommunicationContact, CommunicationMessage, CommunicationThread
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.partner import Partner
from app.models.partner_network import PartnerActivity, PartnerProductInterest
from app.models.product import Product
from app.services.ai_service import _extract_json, _validate_api_key, get_openai
from app.services.export_agent_service import (
    _lead_matches_product,
    _partner_matches_product,
    _product_blob,
    _text_overlap,
)

logger = logging.getLogger(__name__)

FINDER_MARKER = "[Buyer Finder]"
REC_MARKER = "[Buyer Recommendation]"

RECOMMENDATION_TYPES = frozenset({"partner", "crm_lead", "contact", "industry_segment"})

_REASON_SYSTEM = """\
You write brief advisory buyer-fit reasons for B2B export products.
Return ONLY JSON:
{
  "reasons": [
    {"id": "candidate_key", "reason": "1-2 sentence advisory note"}
  ]
}
Rules:
- Advisory only — never suggest automatic messaging, outreach, or contacting buyers
- Be specific about category, country, and signal (deals, communication, partner interest)
- Example tone: "Construction companies in Uzbekistan have shown repeated interest in solar equipment."
"""


@dataclass
class _Candidate:
    key: str
    recommendation_type: str
    reference_id: UUID | None
    name: str
    country: str | None
    score: float
    signals: dict[str, Any] = field(default_factory=dict)


def _contact_matches_product(contact: CommunicationContact, product: Product) -> bool:
    blob = " ".join(filter(None, [contact.notes, contact.company, contact.name, contact.country]))
    return _text_overlap(blob, _product_blob(product)) >= 0.12


def _category_overlap(product: Product, text: str) -> float:
    cat = (product.category or "").strip()
    if cat and cat.lower() in (text or "").lower():
        return 1.0
    return _text_overlap(_product_blob(product), text or "")


def _compute_buyer_score(
    product: Product,
    *,
    entity_text: str,
    country: str | None,
    priority_countries: set[str],
    won_deals: int,
    comm_messages: int,
    has_partner_interest: bool,
) -> float:
    cat = _category_overlap(product, entity_text)
    category_pts = min(25.0, cat * 25.0)
    if country and priority_countries and country.lower() in {c.lower() for c in priority_countries}:
        country_pts = 20.0
    elif country:
        country_pts = 10.0
    else:
        country_pts = 0.0
    deal_pts = min(20.0, won_deals * 10.0)
    comm_pts = min(20.0, comm_messages * 4.0)
    interest_pts = 15.0 if has_partner_interest else 0.0
    return round(min(100.0, category_pts + country_pts + deal_pts + comm_pts + interest_pts), 1)


def _rule_reason(candidate: _Candidate, product: Product) -> str:
    cat = product.category or product.name
    country = candidate.country or "the region"
    sig = candidate.signals
    if candidate.recommendation_type == "partner":
        ptype = sig.get("partner_type") or "partner"
        if sig.get("has_interest"):
            return f"Active {ptype.replace('_', ' ')} in {country} with registered interest in {product.name}."
        return f"{ptype.replace('_', ' ').title()} in {country} aligns with {cat} based on industry profile."
    if candidate.recommendation_type == "crm_lead":
        if sig.get("won_deals"):
            return f"CRM lead in {country} has closed deals and interest notes matching {cat}."
        return f"Existing CRM lead from {country} shows interest overlap with {product.name}."
    if candidate.recommendation_type == "contact":
        msgs = sig.get("comm_messages", 0)
        if msgs:
            return f"Communication history ({msgs} messages) with this contact suggests buyer fit for {cat}."
        return f"Contact in {country} profile matches {cat} product category."
    segment = candidate.name
    count = sig.get("signal_count", 0)
    return f"{segment} in {country} — {count} matching signals in your CRM, partners, and communications."


def _display_company(partner: Partner) -> str | None:
    return partner.company_name or partner.company


async def _message_count_for_lead(db: AsyncSession, lead_id: UUID) -> int:
    r = await db.execute(
        select(func.count())
        .select_from(CommunicationMessage)
        .join(CommunicationThread, CommunicationMessage.thread_id == CommunicationThread.id)
        .where(CommunicationThread.lead_id == lead_id)
    )
    return int(r.scalar_one() or 0)


async def _message_count_for_contact(db: AsyncSession, contact_id: UUID) -> int:
    r = await db.execute(
        select(func.count())
        .select_from(CommunicationMessage)
        .join(CommunicationThread, CommunicationMessage.thread_id == CommunicationThread.id)
        .where(CommunicationThread.contact_id == contact_id)
    )
    return int(r.scalar_one() or 0)


async def _won_deals_for_lead(db: AsyncSession, lead_id: UUID) -> int:
    r = await db.execute(
        select(func.count()).select_from(CrmDeal).where(
            CrmDeal.lead_id == lead_id,
            CrmDeal.status.in_(("won", "closed_won")),
        )
    )
    return int(r.scalar_one() or 0)


class BuyerFinderService:
    @staticmethod
    async def _load_product(db: AsyncSession, product_id: UUID) -> Product:
        r = await db.execute(select(Product).where(Product.id == product_id))
        product = r.scalar_one_or_none()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")
        return product

    @staticmethod
    async def _gather_priority_countries(
        db: AsyncSession,
        product: Product,
        partners: list[Partner],
        leads: list[CrmLead],
    ) -> set[str]:
        countries: Counter[str] = Counter()
        for p in partners:
            if p.country and _partner_matches_product(p, product):
                countries[p.country] += 2
        for l in leads:
            if _lead_matches_product(l, product):
                for part in (l.notes, l.interest, l.company):
                    for c in ("Uzbekistan", "Kazakhstan", "Kyrgyzstan", "Tajikistan", "Russia", "China", "Turkey", "UAE"):
                        if part and c.lower() in part.lower():
                            countries[c] += 1
        if not countries:
            return {"Uzbekistan", "Kazakhstan"}
        return {c for c, _ in countries.most_common(5)}

    @staticmethod
    async def _build_candidates(db: AsyncSession, product: Product) -> list[_Candidate]:
        partners_r = await db.execute(select(Partner).where(Partner.status == "active"))
        partners = list(partners_r.scalars().all())

        leads_r = await db.execute(select(CrmLead).where(CrmLead.client_id == product.client_id))
        leads = list(leads_r.scalars().all())

        contacts_r = await db.execute(
            select(CommunicationContact).where(CommunicationContact.client_id == product.client_id)
        )
        contacts = list(contacts_r.scalars().all())

        interests_r = await db.execute(
            select(PartnerProductInterest).where(PartnerProductInterest.product_id == product.id)
        )
        interests = {i.partner_id: i for i in interests_r.scalars().all()}

        priority_countries = await BuyerFinderService._gather_priority_countries(db, product, partners, leads)
        candidates: list[_Candidate] = []

        for p in partners:
            if not _partner_matches_product(p, product):
                continue
            entity_text = " ".join(filter(None, [
                p.name, _display_company(p), " ".join(p.industries_json or []), p.notes,
            ]))
            activity_r = await db.execute(
                select(func.count()).select_from(PartnerActivity).where(PartnerActivity.partner_id == p.id)
            )
            activities = int(activity_r.scalar_one() or 0)
            has_interest = p.id in interests
            score = _compute_buyer_score(
                product,
                entity_text=entity_text,
                country=p.country,
                priority_countries=priority_countries,
                won_deals=0,
                comm_messages=activities,
                has_partner_interest=has_interest,
            )
            if score < 20:
                continue
            candidates.append(_Candidate(
                key=f"partner:{p.id}",
                recommendation_type="partner",
                reference_id=p.id,
                name=p.name + (f" · {_display_company(p)}" if _display_company(p) else ""),
                country=p.country,
                score=score,
                signals={"partner_type": p.partner_type, "has_interest": has_interest, "activities": activities},
            ))

        for l in leads:
            if not _lead_matches_product(l, product):
                continue
            entity_text = " ".join(filter(None, [l.interest, l.notes, l.company, l.name]))
            country = None
            for c in priority_countries:
                if entity_text and c.lower() in entity_text.lower():
                    country = c
                    break
            won = await _won_deals_for_lead(db, l.id)
            msgs = await _message_count_for_lead(db, l.id)
            score = _compute_buyer_score(
                product,
                entity_text=entity_text,
                country=country,
                priority_countries=priority_countries,
                won_deals=won,
                comm_messages=msgs,
                has_partner_interest=False,
            )
            if score < 15:
                continue
            candidates.append(_Candidate(
                key=f"crm_lead:{l.id}",
                recommendation_type="crm_lead",
                reference_id=l.id,
                name=l.name + (f" · {l.company}" if l.company else ""),
                country=country,
                score=score,
                signals={"won_deals": won, "comm_messages": msgs},
            ))

        for c in contacts:
            if not _contact_matches_product(c, product):
                continue
            entity_text = " ".join(filter(None, [c.notes, c.company, c.name]))
            msgs = await _message_count_for_contact(db, c.id)
            score = _compute_buyer_score(
                product,
                entity_text=entity_text,
                country=c.country,
                priority_countries=priority_countries,
                won_deals=0,
                comm_messages=msgs,
                has_partner_interest=False,
            )
            if score < 15:
                continue
            candidates.append(_Candidate(
                key=f"contact:{c.id}",
                recommendation_type="contact",
                reference_id=c.id,
                name=c.name + (f" · {c.company}" if c.company else ""),
                country=c.country,
                score=score,
                signals={"comm_messages": msgs},
            ))

        segment_signals: dict[tuple[str, str], int] = defaultdict(int)
        cat = (product.category or product.name).strip()
        for p in partners:
            if not p.country or not _partner_matches_product(p, product):
                continue
            for ind in p.industries_json or []:
                segment_signals[(p.country, str(ind))] += 1
            if p.partner_type:
                segment_signals[(p.country, p.partner_type.replace("_", " "))] += 1
        for l in leads:
            if not _lead_matches_product(l, product):
                continue
            country = None
            for pc in priority_countries:
                blob = " ".join(filter(None, [l.notes, l.interest, l.company]))
                if blob and pc.lower() in blob.lower():
                    country = pc
                    break
            if not country:
                continue
            if l.company:
                segment_signals[(country, l.company)] += 1
            elif cat:
                segment_signals[(country, f"{cat} buyers")] += 1

        for (country, segment), count in segment_signals.items():
            if count < 1:
                continue
            score = _compute_buyer_score(
                product,
                entity_text=f"{segment} {cat} {country}",
                country=country,
                priority_countries=priority_countries,
                won_deals=min(2, count),
                comm_messages=min(5, count),
                has_partner_interest=False,
            )
            score = min(100.0, score + min(15.0, count * 3.0))
            if score < 25:
                continue
            label = segment if segment.lower().endswith("buyers") else f"{segment} ({cat})"
            candidates.append(_Candidate(
                key=f"segment:{country}:{segment}",
                recommendation_type="industry_segment",
                reference_id=None,
                name=label,
                country=country,
                score=round(score, 1),
                signals={"signal_count": count, "segment": segment},
            ))

        candidates.sort(key=lambda x: x.score, reverse=True)
        return candidates

    @staticmethod
    async def _apply_ai_reasons(product: Product, candidates: list[_Candidate]) -> tuple[list[_Candidate], bool]:
        if not candidates:
            return candidates, False
        top = candidates[:20]
        demo_mode = False
        reason_map: dict[str, str] = {}

        try:
            if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
                raise ValueError("AI unavailable")
            _validate_api_key()
            payload = [
                {
                    "id": c.key,
                    "type": c.recommendation_type,
                    "name": c.name,
                    "country": c.country,
                    "score": c.score,
                    "signals": c.signals,
                }
                for c in top
            ]
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _REASON_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"Product: {product.name}\n"
                            f"Category: {product.category or 'general'}\n"
                            f"Description: {(product.description or '')[:400]}\n\n"
                            f"Candidates:\n{json.dumps(payload, ensure_ascii=False)}"
                        ),
                    },
                ],
                temperature=0.25,
                max_tokens=1200,
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(response.choices[0].message.content or "{}")
            for item in parsed.get("reasons") or []:
                rid = str(item.get("id", ""))
                reason = str(item.get("reason", "")).strip()
                if rid and reason:
                    reason_map[rid] = reason
        except Exception as exc:
            demo_mode = True
            logger.info("%s AI reasons fallback: %s", FINDER_MARKER, exc)

        for c in top:
            c.signals["reason"] = reason_map.get(c.key) or _rule_reason(c, product)
        return top, demo_mode

    @staticmethod
    async def _serialize_rows(
        db: AsyncSession,
        rows: list[BuyerRecommendation],
        *,
        product_names: dict[UUID, str] | None = None,
    ) -> list[dict[str, Any]]:
        if not rows:
            return []

        partner_ids = {r.reference_id for r in rows if r.recommendation_type == "partner" and r.reference_id}
        lead_ids = {r.reference_id for r in rows if r.recommendation_type == "crm_lead" and r.reference_id}
        contact_ids = {r.reference_id for r in rows if r.recommendation_type == "contact" and r.reference_id}

        partner_names: dict[UUID, str] = {}
        if partner_ids:
            pr = await db.execute(select(Partner.id, Partner.name, Partner.company, Partner.company_name).where(Partner.id.in_(partner_ids)))
            for pid, name, company, company_name in pr.all():
                co = company_name or company
                partner_names[pid] = name + (f" · {co}" if co else "")

        lead_names: dict[UUID, str] = {}
        if lead_ids:
            lr = await db.execute(select(CrmLead.id, CrmLead.name, CrmLead.company).where(CrmLead.id.in_(lead_ids)))
            for lid, name, company in lr.all():
                lead_names[lid] = name + (f" · {company}" if company else "")

        contact_names: dict[UUID, str] = {}
        if contact_ids:
            cr = await db.execute(
                select(CommunicationContact.id, CommunicationContact.name, CommunicationContact.company)
                .where(CommunicationContact.id.in_(contact_ids))
            )
            for cid, name, company in cr.all():
                contact_names[cid] = name + (f" · {company}" if company else "")

        items: list[dict[str, Any]] = []
        for row in rows:
            if row.recommendation_type == "partner" and row.reference_id:
                name = partner_names.get(row.reference_id, "Partner")
            elif row.recommendation_type == "crm_lead" and row.reference_id:
                name = lead_names.get(row.reference_id, "CRM lead")
            elif row.recommendation_type == "contact" and row.reference_id:
                name = contact_names.get(row.reference_id, "Contact")
            else:
                name = row.reason.split(".")[0].strip()[:100] if row.recommendation_type == "industry_segment" else "Buyer segment"

            item = {
                "id": row.id,
                "client_id": row.client_id,
                "product_id": row.product_id,
                "recommendation_type": row.recommendation_type,
                "reference_id": row.reference_id,
                "name": name,
                "score": float(row.score or 0),
                "reason": row.reason,
                "country": row.country,
                "created_at": row.created_at,
            }
            if product_names and row.product_id in product_names:
                item["product_name"] = product_names[row.product_id]
            items.append(item)
        return items

    @staticmethod
    async def get_for_product(db: AsyncSession, product_id: UUID) -> dict[str, Any]:
        product = await BuyerFinderService._load_product(db, product_id)
        r = await db.execute(
            select(BuyerRecommendation)
            .where(BuyerRecommendation.product_id == product_id)
            .order_by(BuyerRecommendation.score.desc(), BuyerRecommendation.created_at.desc())
        )
        rows = list(r.scalars().all())
        items = await BuyerFinderService._serialize_rows(db, rows)
        logger.info("%s listed: product=%s count=%s", FINDER_MARKER, product_id, len(items))
        return {
            "product_id": product.id,
            "product_name": product.name,
            "product_category": product.category,
            "client_id": product.client_id,
            "items": items,
            "total": len(items),
            "demo_mode": False,
        }

    @staticmethod
    async def analyze_product(db: AsyncSession, product_id: UUID) -> dict[str, Any]:
        product = await BuyerFinderService._load_product(db, product_id)
        logger.info("%s analyze start: product=%s", FINDER_MARKER, product_id)

        candidates = await BuyerFinderService._build_candidates(db, product)
        scored, demo_mode = await BuyerFinderService._apply_ai_reasons(product, candidates)

        await db.execute(delete(BuyerRecommendation).where(BuyerRecommendation.product_id == product_id))

        saved: list[BuyerRecommendation] = []
        for c in scored[:25]:
            reason = c.signals.get("reason") or _rule_reason(c, product)
            if c.recommendation_type == "industry_segment" and not reason.startswith(c.name):
                reason = f"{c.name}. {reason}"
            rec = BuyerRecommendation(
                client_id=product.client_id,
                product_id=product.id,
                recommendation_type=c.recommendation_type,
                reference_id=c.reference_id,
                score=c.score,
                reason=reason,
                country=c.country,
            )
            db.add(rec)
            saved.append(rec)

        await db.commit()
        for rec in saved:
            await db.refresh(rec)

        items = await BuyerFinderService._serialize_rows(db, saved)
        logger.info(
            "%s analyze complete: product=%s saved=%s demo=%s",
            FINDER_MARKER, product_id, len(saved), demo_mode,
        )
        for item in items[:5]:
            logger.info(
                "%s created: type=%s name=%s score=%s",
                REC_MARKER, item["recommendation_type"], item["name"], item["score"],
            )

        return {
            "product_id": product.id,
            "product_name": product.name,
            "analyzed_count": len(saved),
            "items": items,
            "demo_mode": demo_mode,
        }

    @staticmethod
    async def top_opportunities(db: AsyncSession, *, limit: int = 10) -> list[dict[str, Any]]:
        r = await db.execute(
            select(BuyerRecommendation, Product.name)
            .join(Product, BuyerRecommendation.product_id == Product.id)
            .order_by(BuyerRecommendation.score.desc(), BuyerRecommendation.created_at.desc())
            .limit(limit)
        )
        rows = list(r.all())
        if not rows:
            return []

        recs = [row[0] for row in rows]
        product_names = {row[0].product_id: row[1] for row in rows}
        items = await BuyerFinderService._serialize_rows(db, recs, product_names=product_names)
        logger.info("%s top opportunities: count=%s", FINDER_MARKER, len(items))
        return items
