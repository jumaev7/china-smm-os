"""Buyer Acquisition Engine v1 — discovery, matching, pipeline, opportunities (read-only)."""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.buyer_network import BuyerNetworkProfile, BuyerRelationship
from app.models.client import Client
from app.models.communication import CommunicationContact
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmActivity, CrmLead
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.factory_profile import FactoryCatalogProduct, FactoryExportMarket
from app.services.buyer_discovery_service import BuyerDiscoveryService
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Buyer Acquisition Engine]"

PIPELINE_STATUSES: tuple[str, ...] = (
    "new",
    "contacted",
    "replied",
    "negotiating",
    "quotation_sent",
    "sample_sent",
    "won",
    "lost",
)

_PIPELINE_LABELS: dict[str, str] = {
    "new": "New",
    "contacted": "Contacted",
    "replied": "Replied",
    "negotiating": "Negotiating",
    "quotation_sent": "Quotation Sent",
    "sample_sent": "Sample Sent",
    "won": "Won",
    "lost": "Lost",
}

_CRM_TO_PIPELINE: dict[str, str] = {
    "new": "new",
    "contacted": "contacted",
    "qualified": "replied",
    "proposal": "quotation_sent",
    "negotiation": "negotiating",
    "hot": "negotiating",
    "won": "won",
    "lost": "lost",
}

_ACTIVE_PIPELINE = frozenset({
    "new", "contacted", "replied", "negotiating", "quotation_sent", "sample_sent",
})

_ACTION_SPECS: tuple[tuple[str, str, str, str], ...] = (
    (
        "open_factory_platform",
        "Open Factory Platform",
        "Review factory profile, catalog, and export markets for buyer matching.",
        "/factory-platform",
    ),
    (
        "open_customer_portal",
        "Open Customer Portal",
        "Preview customer-facing buyer opportunities and deals.",
        "/customer-portal-v2",
    ),
    (
        "open_crm",
        "Open CRM",
        "Review leads and pipeline in CRM — manual actions only.",
        "/crm",
    ),
    (
        "open_real_factory_pilot",
        "Open Real Factory Pilot",
        "Check pilot readiness including buyer acquisition seed step.",
        "/real-factory-pilot",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Read-only intelligence and lead management — no automatic outreach, scraping, "
        "external integrations, messaging, or CRM writes."
    )


def _normalize_key(company_name: str, country: str | None) -> str:
    name = re.sub(r"\s+", " ", (company_name or "").strip().lower())
    c = (country or "").strip().lower()
    return f"{name}|{c}" if c else name


def _as_str_list(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(x).strip().lower() for x in val if x]
    return [str(val).strip().lower()]


def _decimal_float(val: Decimal | None) -> float:
    if val is None:
        return 0.0
    return float(val)


class BuyerAcquisitionEngineService:
    _cache: dict[str, Any] | None = None
    _cache_at: datetime | None = None
    _cache_key: str | None = None

    @staticmethod
    def _invalidate_cache() -> None:
        BuyerAcquisitionEngineService._cache = None
        BuyerAcquisitionEngineService._cache_at = None
        BuyerAcquisitionEngineService._cache_key = None

    @staticmethod
    def _scope_key(client_id: UUID | None, tenant_id: UUID | None) -> str:
        return f"c={client_id}|t={tenant_id}"

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
    async def _factory_context(
        db: AsyncSession,
        client_id: UUID | None,
    ) -> dict[str, Any]:
        industries: list[str] = []
        products: list[str] = []
        categories: list[str] = []
        markets: list[str] = []
        tenant_id: UUID | None = None

        if not client_id:
            return {
                "industries": industries,
                "products": products,
                "categories": categories,
                "markets": markets,
                "tenant_id": tenant_id,
            }

        client = await db.get(Client, client_id)
        if client:
            tenant_id = client.tenant_id
            industries = _as_str_list(client.business_category)

        if tenant_id:
            profile_row = await db.execute(
                select(FactoryPlatformProfile).where(
                    FactoryPlatformProfile.tenant_id == tenant_id,
                ),
            )
            profile = profile_row.scalar_one_or_none()
            if profile:
                industries = _as_str_list(profile.industries) or industries
                categories = _as_str_list(profile.product_categories)
                markets = _as_str_list(profile.markets) or _as_str_list(profile.export_regions)

            catalog_rows = await db.execute(
                select(FactoryCatalogProduct.category, FactoryCatalogProduct.product_name)
                .where(FactoryCatalogProduct.tenant_id == tenant_id)
                .limit(100),
            )
            for cat, name in catalog_rows.all():
                if cat:
                    products.append(str(cat).strip().lower())
                if name:
                    products.append(str(name).strip().lower())

            market_rows = await db.execute(
                select(FactoryExportMarket.country)
                .where(FactoryExportMarket.tenant_id == tenant_id),
            )
            for (country_name,) in market_rows.all():
                if country_name:
                    markets.append(str(country_name).strip().lower())

        return {
            "industries": list(dict.fromkeys(industries)),
            "products": list(dict.fromkeys(products + categories)),
            "categories": list(dict.fromkeys(categories)),
            "markets": list(dict.fromkeys(markets)),
            "tenant_id": tenant_id,
        }

    @staticmethod
    def _pipeline_from_lead(
        lead: CrmLead,
        *,
        activities: list[CrmActivity] | None = None,
        deal_statuses: list[str] | None = None,
    ) -> str:
        stage = _CRM_TO_PIPELINE.get(lead.status or "new", "new")
        blob = " ".join(
            filter(None, [lead.notes, lead.interest, *(a.content for a in (activities or []))]),
        ).lower()
        if "sample" in blob and stage not in ("won", "lost"):
            return "sample_sent"
        if deal_statuses:
            if any(s == "won" for s in deal_statuses):
                return "won"
            if any(s in ("negotiation", "closing") for s in deal_statuses):
                return "negotiating"
            if any(s == "proposal" for s in deal_statuses):
                return "quotation_sent"
        return stage

    @staticmethod
    def _buyer_status(pipeline: str, *, has_contact: bool) -> str:
        if pipeline == "won":
            return "customer"
        if pipeline == "lost":
            return "inactive"
        if pipeline in ("negotiating", "quotation_sent", "sample_sent", "replied"):
            return "engaged"
        if pipeline == "contacted":
            return "active"
        if has_contact:
            return "prospect"
        return "unknown"

    @staticmethod
    def _compute_match_score(
        *,
        industry: str | None,
        country: str | None,
        product_interest: str | None,
        factory_industries: list[str],
        factory_products: list[str],
        factory_markets: list[str],
        buyer_score: int = 0,
        opportunity_score: int = 0,
    ) -> tuple[int, dict[str, Any]]:
        factors: dict[str, Any] = {
            "industry_match": 0,
            "product_match": 0,
            "market_match": 0,
            "category_match": 0,
            "intelligence_boost": 0,
        }
        score = 15
        ind = (industry or "").lower()
        cty = (country or "").lower()
        interest = (product_interest or "").lower()

        if ind and factory_industries:
            if any(t in ind or ind in t for t in factory_industries):
                factors["industry_match"] = 25
                score += 25
            else:
                factors["industry_match"] = 8
                score += 8
        elif ind:
            factors["industry_match"] = 10
            score += 10

        if factory_products:
            matched = False
            for prod in factory_products:
                if prod and (prod in interest or prod in ind or interest in prod):
                    matched = True
                    break
            if matched:
                factors["product_match"] = 20
                score += 20
            elif interest:
                factors["product_match"] = 8
                score += 8

        if cty and factory_markets:
            if any(t in cty or cty in t for t in factory_markets):
                factors["market_match"] = 25
                score += 25
            else:
                factors["market_match"] = 8
                score += 8
        elif cty:
            factors["market_match"] = 10
            score += 10

        if factory_products and interest:
            cat_hits = sum(1 for p in factory_products if p in interest)
            if cat_hits:
                factors["category_match"] = min(15, cat_hits * 5)
                score += factors["category_match"]

        intel = int((buyer_score * 0.1) + (opportunity_score * 0.1))
        factors["intelligence_boost"] = intel
        score += intel

        return _clamp(score), factors

    @staticmethod
    async def _load_contacts_by_lead(
        db: AsyncSession,
        lead_ids: list[UUID],
    ) -> dict[UUID, CommunicationContact]:
        if not lead_ids:
            return {}
        rows = await db.execute(
            select(CommunicationContact).where(CommunicationContact.lead_id.in_(lead_ids)),
        )
        out: dict[UUID, CommunicationContact] = {}
        for contact in rows.scalars().all():
            if contact.lead_id and contact.lead_id not in out:
                out[contact.lead_id] = contact
        return out

    @staticmethod
    async def _load_deals_by_lead(
        db: AsyncSession,
        lead_ids: list[UUID],
    ) -> dict[UUID, list[CrmDeal]]:
        if not lead_ids:
            return {}
        rows = await db.execute(select(CrmDeal).where(CrmDeal.lead_id.in_(lead_ids)))
        out: dict[UUID, list[CrmDeal]] = {}
        for deal in rows.scalars().all():
            out.setdefault(deal.lead_id, []).append(deal)
        return out

    @staticmethod
    async def _build_buyer_database(
        db: AsyncSession,
        *,
        client_id: UUID | None,
        client_ids: list[UUID] | None,
        factory_ctx: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        errors: list[str] = []
        merged: dict[str, dict[str, Any]] = {}

        def _upsert(key: str, company_name: str) -> dict[str, Any]:
            if key not in merged:
                merged[key] = {
                    "buyer_id": key,
                    "company_name": company_name,
                    "country": None,
                    "industry": None,
                    "website": None,
                    "email": None,
                    "phone": None,
                    "whatsapp": None,
                    "wechat": None,
                    "status": "unknown",
                    "pipeline_status": "new",
                    "match_score": 0,
                    "match_factors": {},
                    "sources": [],
                    "crm_lead_id": None,
                    "discovery_id": None,
                    "network_id": None,
                    "client_id": client_id,
                    "estimated_value": 0.0,
                }
            return merged[key]

        scope_ids = client_ids or ([client_id] if client_id else None)

        if scope_ids:
            try:
                lead_q = select(CrmLead).where(CrmLead.client_id.in_(scope_ids))
                lead_rows = await db.execute(lead_q)
                leads = list(lead_rows.scalars().all())
                lead_ids = [l.id for l in leads]
                contacts = await BuyerAcquisitionEngineService._load_contacts_by_lead(db, lead_ids)
                deals_map = await BuyerAcquisitionEngineService._load_deals_by_lead(db, lead_ids)

                for lead in leads:
                    company = (lead.company or lead.name or "Unknown").strip()
                    key = _normalize_key(company, None)
                    rec = _upsert(key, company)
                    rec["sources"].append("crm")
                    rec["crm_lead_id"] = lead.id
                    rec["client_id"] = lead.client_id
                    rec["email"] = lead.email or rec["email"]
                    rec["phone"] = lead.phone or rec["phone"]
                    if lead.interest:
                        rec["industry"] = rec["industry"] or lead.interest[:100]

                    contact = contacts.get(lead.id)
                    if contact:
                        rec["email"] = rec["email"] or contact.email
                        rec["phone"] = rec["phone"] or contact.phone
                        rec["whatsapp"] = contact.whatsapp
                        rec["wechat"] = contact.wechat or contact.wechat_id
                        rec["country"] = rec["country"] or contact.country

                    deals = deals_map.get(lead.id) or []
                    deal_statuses = [d.status for d in deals]
                    pipeline = BuyerAcquisitionEngineService._pipeline_from_lead(
                        lead, deal_statuses=deal_statuses,
                    )
                    rec["pipeline_status"] = pipeline
                    rec["status"] = BuyerAcquisitionEngineService._buyer_status(
                        pipeline, has_contact=bool(rec["email"] or rec["phone"]),
                    )
                    if deals:
                        rec["estimated_value"] = max(
                            rec["estimated_value"],
                            sum(_decimal_float(d.expected_value or d.deal_amount) for d in deals),
                        )

                    buyer_score = int(lead.lead_score or 0)
                    match_score, factors = BuyerAcquisitionEngineService._compute_match_score(
                        industry=rec.get("industry"),
                        country=rec.get("country"),
                        product_interest=lead.interest,
                        factory_industries=factory_ctx["industries"],
                        factory_products=factory_ctx["products"],
                        factory_markets=factory_ctx["markets"],
                        buyer_score=buyer_score,
                    )
                    rec["match_score"] = max(rec["match_score"], match_score)
                    rec["match_factors"] = factors
            except Exception as exc:
                logger.info("%s crm load: %s", MARKER, exc)
                errors.append(f"crm: {exc}")

            try:
                disc_q = select(BuyerDiscoveryEntry).where(
                    BuyerDiscoveryEntry.client_id.in_(scope_ids),
                )
                disc_rows = await db.execute(disc_q)
                for entry in disc_rows.scalars().all():
                    key = _normalize_key(entry.company_name, entry.country)
                    rec = _upsert(key, entry.company_name)
                    if "discovery" not in rec["sources"]:
                        rec["sources"].append("discovery")
                    rec["discovery_id"] = entry.id
                    rec["country"] = entry.country or rec["country"]
                    rec["industry"] = entry.industry or rec["industry"]
                    rec["website"] = entry.website or rec["website"]
                    rec["client_id"] = entry.client_id
                    opp = int(entry.opportunity_score or 0)
                    match_score, factors = BuyerAcquisitionEngineService._compute_match_score(
                        industry=rec.get("industry"),
                        country=rec.get("country"),
                        product_interest=None,
                        factory_industries=factory_ctx["industries"],
                        factory_products=factory_ctx["products"],
                        factory_markets=factory_ctx["markets"],
                        opportunity_score=opp,
                    )
                    rec["match_score"] = max(rec["match_score"], match_score)
                    rec["match_factors"] = factors
            except Exception as exc:
                logger.info("%s discovery load: %s", MARKER, exc)
                errors.append(f"discovery: {exc}")

        tenant_id = factory_ctx.get("tenant_id")
        if tenant_id:
            try:
                rel_rows = await db.execute(
                    select(BuyerRelationship, BuyerNetworkProfile)
                    .join(BuyerNetworkProfile, BuyerRelationship.buyer_id == BuyerNetworkProfile.id)
                    .where(BuyerRelationship.tenant_id == tenant_id),
                )
                for rel, profile in rel_rows.all():
                    key = _normalize_key(profile.company_name, profile.country)
                    rec = _upsert(key, profile.company_name)
                    if "network" not in rec["sources"]:
                        rec["sources"].append("network")
                    rec["network_id"] = profile.id
                    rec["country"] = profile.country or rec["country"]
                    rec["industry"] = profile.industry or rec["industry"]
                    rec["website"] = profile.website or rec["website"]
                    match_score, factors = BuyerAcquisitionEngineService._compute_match_score(
                        industry=rec.get("industry"),
                        country=rec.get("country"),
                        product_interest=None,
                        factory_industries=factory_ctx["industries"],
                        factory_products=factory_ctx["products"],
                        factory_markets=factory_ctx["markets"],
                        opportunity_score=int(profile.opportunity_score or 0),
                    )
                    rec["match_score"] = max(rec["match_score"], match_score)
                    rec["match_factors"] = factors
                    if rel.relationship_type == "customer":
                        rec["pipeline_status"] = "won"
                        rec["status"] = "customer"
                    elif rel.relationship_type in ("active", "strategic"):
                        rec["pipeline_status"] = "negotiating"
                        rec["status"] = "engaged"
                    elif rel.relationship_type == "contacted":
                        rec["pipeline_status"] = "contacted"
                        rec["status"] = "active"
            except Exception as exc:
                logger.info("%s network load: %s", MARKER, exc)
                errors.append(f"network: {exc}")

        buyers = list(merged.values())
        for b in buyers:
            b["sources"] = list(dict.fromkeys(b["sources"]))
        buyers.sort(key=lambda x: (-x["match_score"], x["company_name"]))
        return buyers, errors

    @staticmethod
    def _pipeline_counts(buyers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        counts: Counter[str] = Counter()
        for b in buyers:
            st = b.get("pipeline_status") or "new"
            if st not in PIPELINE_STATUSES:
                st = "new"
            counts[st] += 1
        return [
            {"status": st, "label": _PIPELINE_LABELS[st], "count": counts.get(st, 0)}
            for st in PIPELINE_STATUSES
        ]

    @staticmethod
    def _crm_summary(buyers: list[dict[str, Any]]) -> dict[str, Any]:
        total = len(buyers)
        active = sum(1 for b in buyers if b.get("pipeline_status") in _ACTIVE_PIPELINE)
        won = sum(1 for b in buyers if b.get("pipeline_status") == "won")
        lost = sum(1 for b in buyers if b.get("pipeline_status") == "lost")
        pipeline_value = sum(float(b.get("estimated_value") or 0) for b in buyers)
        avg_match = int(round(sum(b.get("match_score", 0) for b in buyers) / total)) if total else 0
        return {
            "total_leads": total,
            "active_leads": active,
            "won_deals": won,
            "lost_deals": lost,
            "pipeline_value": round(pipeline_value, 2),
            "average_match_score": avg_match,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _build_opportunities(buyers: list[dict[str, Any]]) -> dict[str, Any]:
        buyer_opps: list[dict[str, Any]] = []
        for i, b in enumerate(buyers[:20]):
            if b.get("match_score", 0) < 40:
                continue
            buyer_opps.append({
                "opportunity_id": f"buyer-{b['buyer_id']}",
                "opportunity_type": "buyer",
                "title": b["company_name"],
                "subtitle": f"Match score {b['match_score']}",
                "country": b.get("country"),
                "industry": b.get("industry"),
                "buyer_company": b["company_name"],
                "score": b.get("match_score", 0),
                "lead_count": 1,
                "estimated_value": b.get("estimated_value") or None,
                "recommended_action": "Review buyer profile in CRM — manual outreach only",
            })

        country_groups: Counter[str] = Counter()
        country_scores: dict[str, list[int]] = {}
        country_value: dict[str, float] = {}
        for b in buyers:
            c = b.get("country")
            if not c:
                continue
            country_groups[c] += 1
            country_scores.setdefault(c, []).append(b.get("match_score", 0))
            country_value[c] = country_value.get(c, 0) + float(b.get("estimated_value") or 0)

        country_opps = [
            {
                "opportunity_id": f"country-{c.lower().replace(' ', '-')}",
                "opportunity_type": "country",
                "title": c,
                "subtitle": f"{count} buyer(s)",
                "country": c,
                "industry": None,
                "buyer_company": None,
                "score": _clamp(int(sum(country_scores[c]) / len(country_scores[c]))),
                "lead_count": count,
                "estimated_value": round(country_value.get(c, 0), 2) or None,
                "recommended_action": "Prioritize export market outreach for this country",
            }
            for c, count in country_groups.most_common(12)
        ]

        industry_groups: Counter[str] = Counter()
        industry_scores: dict[str, list[int]] = {}
        for b in buyers:
            ind = b.get("industry")
            if not ind:
                continue
            industry_groups[ind] += 1
            industry_scores.setdefault(ind, []).append(b.get("match_score", 0))

        industry_opps = [
            {
                "opportunity_id": f"industry-{ind.lower().replace(' ', '-')[:40]}",
                "opportunity_type": "industry",
                "title": ind,
                "subtitle": f"{count} buyer(s)",
                "country": None,
                "industry": ind,
                "buyer_company": None,
                "score": _clamp(int(sum(industry_scores[ind]) / len(industry_scores[ind]))),
                "lead_count": count,
                "estimated_value": None,
                "recommended_action": "Align product catalog messaging for this industry",
            }
            for ind, count in industry_groups.most_common(12)
        ]

        total = len(buyer_opps) + len(country_opps) + len(industry_opps)
        return {
            "buyer_opportunities": buyer_opps,
            "country_opportunities": country_opps,
            "industry_opportunities": industry_opps,
            "total": total,
            "errors": [],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _readiness_score(buyers: list[dict[str, Any]], factory_ctx: dict[str, Any]) -> int:
        if not buyers:
            return 15
        high_match = sum(1 for b in buyers if b.get("match_score", 0) >= 60)
        active = sum(1 for b in buyers if b.get("pipeline_status") in _ACTIVE_PIPELINE)
        profile_bonus = 0
        if factory_ctx.get("industries"):
            profile_bonus += 10
        if factory_ctx.get("products"):
            profile_bonus += 10
        if factory_ctx.get("markets"):
            profile_bonus += 10
        base = min(40, len(buyers) * 5) + min(30, high_match * 8) + min(20, active * 4) + profile_bonus
        return _clamp(base)

    @staticmethod
    def _guided_actions(
        *,
        tenant_id: UUID | None,
        client_id: UUID | None,
    ) -> list[dict[str, Any]]:
        tenant_q = f"?tenant_id={tenant_id}" if tenant_id else ""
        items: list[dict[str, Any]] = []
        for key, title, desc, route in _ACTION_SPECS:
            full_route = route
            if key == "open_factory_platform" and tenant_q:
                full_route = f"{route}{tenant_q}"
            elif key == "open_customer_portal" and tenant_q:
                full_route = f"{route}{tenant_q}"
            enabled = True
            if key == "open_real_factory_pilot":
                enabled = True
            items.append({
                "key": key,
                "title": title,
                "description": desc,
                "route": full_route,
                "enabled": enabled,
            })
        return items

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        async def _probe(module: str, coro: Any, message: str) -> None:
            try:
                await coro
                checks.append({"module": module, "status": "ok", "message": message, "details": {}})
            except Exception as exc:
                checks.append({
                    "module": module,
                    "status": "degraded",
                    "message": str(exc)[:200],
                    "details": {},
                })

        await _probe(
            "buyer_discovery",
            BuyerDiscoveryService.overview(db),
            "Buyer Discovery overview reachable",
        )
        await _probe(
            "buyer_intelligence",
            BuyerIntelligenceService.overview(db),
            "Buyer Intelligence overview reachable",
        )
        return checks

    @staticmethod
    async def _snapshot(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        resolved_id, client_ids = await BuyerAcquisitionEngineService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        factory_ctx = await BuyerAcquisitionEngineService._factory_context(db, resolved_id)
        buyers, errors = await BuyerAcquisitionEngineService._build_buyer_database(
            db,
            client_id=resolved_id,
            client_ids=client_ids,
            factory_ctx=factory_ctx,
        )
        crm = BuyerAcquisitionEngineService._crm_summary(buyers)
        opps = BuyerAcquisitionEngineService._build_opportunities(buyers)
        readiness = BuyerAcquisitionEngineService._readiness_score(buyers, factory_ctx)
        high_match = sum(1 for b in buyers if b.get("match_score", 0) >= 60)
        active_pipe = sum(1 for b in buyers if b.get("pipeline_status") in _ACTIVE_PIPELINE)

        match_items = [
            {
                "buyer_id": b["buyer_id"],
                "company_name": b["company_name"],
                "country": b.get("country"),
                "industry": b.get("industry"),
                "match_score": b.get("match_score", 0),
                "match_factors": b.get("match_factors") or {},
                "pipeline_status": b.get("pipeline_status", "new"),
                "recommended_action": "Review in CRM — manual outreach only",
            }
            for b in buyers
        ]

        lead_counts = {s["status"]: s["count"] for s in BuyerAcquisitionEngineService._pipeline_counts(buyers)}

        return {
            "buyers": buyers,
            "errors": errors,
            "factory_ctx": factory_ctx,
            "crm_summary": crm,
            "opportunities": opps,
            "readiness_score": readiness,
            "high_match": high_match,
            "active_pipe": active_pipe,
            "match_items": match_items,
            "lead_counts": lead_counts,
            "resolved_client_id": resolved_id,
            "tenant_id": factory_ctx.get("tenant_id") or tenant_id,
        }

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        buyers = snap["buyers"]
        checks = await BuyerAcquisitionEngineService.integration_checks(db)
        guided = BuyerAcquisitionEngineService._guided_actions(
            tenant_id=snap.get("tenant_id"),
            client_id=snap.get("resolved_client_id"),
        )
        avg_match = snap["crm_summary"]["average_match_score"]
        best = snap["match_items"][:8]
        top = sorted(snap["match_items"], key=lambda x: -x["match_score"])[:5]

        return {
            "total_buyers": len(buyers),
            "database_buyers": len(buyers),
            "matched_buyers": snap["high_match"],
            "high_match_buyers": snap["high_match"],
            "active_pipeline_leads": snap["active_pipe"],
            "total_opportunities": snap["opportunities"]["total"],
            "average_match_score": avg_match,
            "readiness_score": snap["readiness_score"],
            "factory_view": {
                "top_buyers": top,
                "best_matches": best,
                "active_opportunities": snap["opportunities"]["total"],
                "lead_counts": snap["lead_counts"],
            },
            "crm_summary": snap["crm_summary"],
            "integration_checks": checks,
            "guided_actions": guided,
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def list_buyers(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        min_match_score: int | None = None,
        pipeline_status: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        items = snap["buyers"]
        if min_match_score is not None:
            items = [b for b in items if b.get("match_score", 0) >= min_match_score]
        if pipeline_status:
            items = [b for b in items if b.get("pipeline_status") == pipeline_status]
        total = len(items)
        limit = clamp_limit(limit)
        page = items[skip: skip + limit]
        return {
            "items": page,
            "total": total,
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def matches(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        min_score: int = 0,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        items = [m for m in snap["match_items"] if m["match_score"] >= min_score]
        total = len(items)
        limit = clamp_limit(limit)
        page = items[skip: skip + limit]
        avg = int(round(sum(m["match_score"] for m in items) / total)) if total else 0
        ctx = snap["factory_ctx"]
        return {
            "items": page,
            "total": total,
            "average_match_score": avg,
            "factory_industries": ctx.get("industries") or [],
            "factory_products": ctx.get("products") or [],
            "export_markets": ctx.get("markets") or [],
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def pipeline(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        stages = BuyerAcquisitionEngineService._pipeline_counts(snap["buyers"])
        total = sum(s["count"] for s in stages)
        active = sum(s["count"] for s in stages if s["status"] in _ACTIVE_PIPELINE)
        return {
            "stages": stages,
            "total": total,
            "active_count": active,
            "errors": snap["errors"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        out = snap["opportunities"]
        out["errors"] = snap["errors"]
        return out

    @staticmethod
    async def summary(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return snap["crm_summary"]

    @staticmethod
    async def guided_actions(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            "items": BuyerAcquisitionEngineService._guided_actions(
                tenant_id=snap.get("tenant_id"),
                client_id=snap.get("resolved_client_id"),
            ),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def refresh(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        BuyerAcquisitionEngineService._invalidate_cache()
        t0 = time.perf_counter()
        snap = await BuyerAcquisitionEngineService._snapshot(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        logger.info("%s refresh %.0fms buyers=%s", MARKER, (time.perf_counter() - t0) * 1000, len(snap["buyers"]))
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": snap["readiness_score"],
            "total_buyers": len(snap["buyers"]),
            "matched_buyers": snap["high_match"],
            "active_pipeline_leads": snap["active_pipe"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await BuyerAcquisitionEngineService.overview(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        top = (overview.get("factory_view") or {}).get("top_buyers") or []
        top_buyer = top[0] if top else None
        return {
            "readiness_score": overview["readiness_score"],
            "total_buyers": overview["total_buyers"],
            "matched_buyers": overview["matched_buyers"],
            "active_pipeline_leads": overview["active_pipeline_leads"],
            "average_match_score": overview["average_match_score"],
            "top_buyer_name": top_buyer["company_name"] if top_buyer else None,
            "top_buyer_score": top_buyer["match_score"] if top_buyer else 0,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def executive_summary(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await BuyerAcquisitionEngineService.overview(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            "readiness_score": overview["readiness_score"],
            "total_buyers": overview["total_buyers"],
            "matched_buyers": overview["matched_buyers"],
            "active_pipeline_leads": overview["active_pipeline_leads"],
            "average_match_score": overview["average_match_score"],
            "pipeline_value": overview["crm_summary"]["pipeline_value"],
            "top_buyers": (overview.get("factory_view") or {}).get("top_buyers") or [],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def readiness_panel(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await BuyerAcquisitionEngineService.overview(db, tenant_id=tenant_id)
        return {
            "readiness_score": overview["readiness_score"],
            "total_buyers": overview["total_buyers"],
            "matched_buyers": overview["matched_buyers"],
            "high_match_buyers": overview["high_match_buyers"],
            "active_pipeline_leads": overview["active_pipeline_leads"],
            "average_match_score": overview["average_match_score"],
            "message": (
                f"Buyer acquisition engine readiness {overview['readiness_score']}/100 — "
                f"{overview['matched_buyers']} high-match buyer(s)"
            ),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def top_buyer_opportunities(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        client_id: UUID | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        opps = await BuyerAcquisitionEngineService.opportunities(
            db, tenant_id=tenant_id, client_id=client_id,
        )
        buyer_opps = (opps.get("buyer_opportunities") or [])[:limit]
        return {
            "items": buyer_opps,
            "total": len(buyer_opps),
            "country_count": len(opps.get("country_opportunities") or []),
            "industry_count": len(opps.get("industry_opportunities") or []),
            "safety_notice": _safety_notice(),
        }
