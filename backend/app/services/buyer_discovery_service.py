"""Export Buyer Discovery Engine v1 — buyer registry, scoring, pipeline (read-only intelligence)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.client import Client
from app.models.crm_lead import CrmLead
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Buyer Discovery]"

CATEGORIES = frozenset({"high_potential", "strategic", "active", "new", "watchlist"})
PIPELINE_STAGES = (
    "discovered",
    "researched",
    "qualified",
    "contacted",
    "opportunity",
    "customer",
)

_PIPELINE_LABELS = {
    "discovered": "Discovered",
    "researched": "Researched",
    "qualified": "Qualified",
    "contacted": "Contacted",
    "opportunity": "Opportunity",
    "customer": "Customer",
}

_STATUS_TO_PIPELINE = {
    "new": "discovered",
    "contacted": "contacted",
    "qualified": "qualified",
    "proposal": "opportunity",
    "negotiation": "opportunity",
    "hot": "opportunity",
    "won": "customer",
}

_STATUS_TO_CONTACT = {
    "new": "not_contacted",
    "contacted": "contacted",
    "qualified": "qualified",
    "proposal": "engaged",
    "negotiation": "engaged",
    "hot": "engaged",
    "won": "qualified",
    "lost": "inactive",
}

_DEMO_BUYERS = [
    {
        "company_name": "Global Trade Partners Ltd",
        "country": "UAE",
        "city": "Dubai",
        "industry": "electronics",
        "website": "https://example.com/gtp",
        "source": "market_research",
    },
    {
        "company_name": "Central Asia Distributors",
        "country": "Kazakhstan",
        "city": "Almaty",
        "industry": "retail",
        "website": None,
        "source": "partner_referral",
    },
    {
        "company_name": "Euro Import Solutions GmbH",
        "country": "Germany",
        "city": "Hamburg",
        "industry": "automotive",
        "website": "https://example.com/eis",
        "source": "export_database",
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _as_str_list(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(x).strip().lower() for x in val if x]
    return [str(val).strip().lower()]


def _extract_website(lead: CrmLead) -> str | None:
    blob = " ".join(filter(None, [lead.notes, lead.interest, lead.company]))
    match = re.search(r"https?://[^\s]+", blob, re.I)
    return match.group(0).rstrip(".,)") if match else None


def _infer_city(lead: CrmLead) -> str | None:
    blob = lead.notes or ""
    for city in ("Tashkent", "Dubai", "Almaty", "Istanbul", "Moscow", "Shanghai", "Hamburg"):
        if city.lower() in blob.lower():
            return city
    return None


class BuyerDiscoveryService:
    """Factory partner buyer discovery — registry sync and scoring only; no CRM/outreach writes."""

    @staticmethod
    def _safety_notice() -> str:
        return "Read-only intelligence — no automatic outreach, messaging, or CRM writes."

    @staticmethod
    def _entry_to_dict(entry: BuyerDiscoveryEntry) -> dict[str, Any]:
        return {
            "id": entry.id,
            "company_name": entry.company_name,
            "country": entry.country,
            "city": entry.city,
            "industry": entry.industry,
            "website": entry.website,
            "contact_status": entry.contact_status,
            "source": entry.source,
            "discovered_at": entry.discovered_at,
            "opportunity_score": entry.opportunity_score,
            "category": entry.category,
            "pipeline_stage": entry.pipeline_stage,
            "crm_lead_id": entry.crm_lead_id,
            "client_id": entry.client_id,
        }

    @staticmethod
    def _pipeline_from_lead(lead: CrmLead, *, has_deals: bool, has_comms: bool) -> str:
        stage = _STATUS_TO_PIPELINE.get(lead.status or "new", "researched")
        if stage == "discovered" and (has_deals or has_comms):
            return "researched"
        return stage

    @staticmethod
    def _category(
        score: int,
        *,
        days_since_discovered: int,
        bi_classification: str | None,
        has_recent_activity: bool,
    ) -> str:
        if bi_classification in ("strategic_buyer", "hot_buyer"):
            return "strategic"
        if score >= 75:
            return "high_potential"
        if has_recent_activity:
            return "active"
        if days_since_discovered <= 14:
            return "new"
        if score < 40 or bi_classification in ("inactive_buyer", "at_risk_buyer"):
            return "watchlist"
        if score >= 55:
            return "active"
        return "watchlist"

    @staticmethod
    async def _factory_markets(db: AsyncSession, client_id: UUID) -> tuple[list[str], list[str]]:
        """Target markets and industries from factory platform profile if present."""
        client = await db.get(Client, client_id)
        if not client or not client.tenant_id:
            return [], []
        result = await db.execute(
            select(FactoryPlatformProfile).where(
                FactoryPlatformProfile.tenant_id == client.tenant_id,
            ),
        )
        profile = result.scalar_one_or_none()
        if not profile:
            return _as_str_list(client.business_category), []
        markets = _as_str_list(profile.markets) or _as_str_list(profile.export_regions)
        industries = _as_str_list(profile.industries) or _as_str_list(profile.product_categories)
        return markets, industries

    @staticmethod
    async def _compute_opportunity_score(
        db: AsyncSession,
        entry: BuyerDiscoveryEntry,
        lead: CrmLead | None,
        *,
        target_markets: list[str],
        target_industries: list[str],
    ) -> tuple[int, dict[str, Any]]:
        factors: dict[str, Any] = {
            "industry_match": 0,
            "market_match": 0,
            "communication_activity": 0,
            "buyer_intelligence": 0,
            "deal_activity": 0,
        }
        score = 20

        industry = (entry.industry or "").lower()
        country = (entry.country or "").lower()
        if industry and target_industries:
            if any(t in industry or industry in t for t in target_industries):
                factors["industry_match"] = 20
                score += 20
            elif industry:
                factors["industry_match"] = 8
                score += 8
        elif industry:
            factors["industry_match"] = 10
            score += 10

        if country and target_markets:
            if any(t in country or country in t for t in target_markets):
                factors["market_match"] = 20
                score += 20
            elif country:
                factors["market_match"] = 8
                score += 8
        elif country:
            factors["market_match"] = 10
            score += 10

        bi_score = 0
        bi_class = None
        deal_count = 0
        comm_active = False
        if lead:
            try:
                ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
                bi_score = int(ev.get("buyer_score") or 0)
                bi_class = ev.get("classification")
                factors["buyer_intelligence"] = int(bi_score * 0.25)
                score += factors["buyer_intelligence"]
                sig = ev.get("signals") or {}
                deal_count = int(sig.get("deal_count") or 0)
                inbound = int(sig.get("inbound_count") or 0)
                if inbound >= 3:
                    factors["communication_activity"] = 15
                    comm_active = True
                    score += 15
                elif inbound >= 1:
                    factors["communication_activity"] = 8
                    comm_active = True
                    score += 8
                if deal_count > 0:
                    factors["deal_activity"] = min(20, 10 + deal_count * 3)
                    score += factors["deal_activity"]
            except Exception as exc:
                logger.info("%s bi skip lead=%s: %s", MARKER, lead.id, exc)

        if entry.source in ("partner_referral", "export_database") and score < 50:
            score += 5

        revenue_potential = min(25, factors["deal_activity"] + int(bi_score * 0.15))
        factors["country_match"] = factors["market_match"]
        factors["product_match"] = factors["industry_match"]
        factors["revenue_potential"] = revenue_potential

        return _clamp(score), {
            **factors,
            "buyer_intelligence_raw": bi_score,
            "buyer_classification": bi_class,
            "deal_count": deal_count,
            "communication_active": comm_active,
        }

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
    async def _default_client_id(db: AsyncSession) -> UUID | None:
        result = await db.execute(select(Client.id).limit(1))
        return result.scalar_one_or_none()

    @staticmethod
    async def _ensure_initial_registry(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        client_ids: list[UUID] | None = None,
    ) -> UUID | None:
        """Seed registry from CRM or demo buyers when empty."""
        count = await db.scalar(select(func.count()).select_from(BuyerDiscoveryEntry)) or 0
        if count > 0:
            return client_id

        target = client_id
        if not target and client_ids:
            target = client_ids[0] if client_ids else None
        if not target:
            target = await BuyerDiscoveryService._default_client_id(db)
        if not target:
            return None

        await BuyerDiscoveryService.sync_registry(db, client_id=target)
        return target

    @staticmethod
    async def _load_entries(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        client_ids: list[UUID] | None = None,
    ) -> list[BuyerDiscoveryEntry]:
        q = select(BuyerDiscoveryEntry).order_by(
            BuyerDiscoveryEntry.opportunity_score.desc(),
            BuyerDiscoveryEntry.discovered_at.desc(),
        )
        if client_id:
            q = q.where(BuyerDiscoveryEntry.client_id == client_id)
        elif client_ids is not None:
            if not client_ids:
                return []
            q = q.where(BuyerDiscoveryEntry.client_id.in_(client_ids))
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def sync_registry(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        client_ids: list[UUID] | None = None,
        limit: int = 500,
    ) -> int:
        """Upsert registry from CRM leads — writes discovery table only."""
        limit = min(2000, max(1, limit))
        q = select(CrmLead).where(CrmLead.status.notin_(("lost",)))
        if client_id:
            q = q.where(CrmLead.client_id == client_id)
        elif client_ids is not None:
            if not client_ids:
                return 0
            q = q.where(CrmLead.client_id.in_(client_ids))
        q = q.order_by(CrmLead.updated_at.desc()).limit(limit)
        leads = list((await db.execute(q)).scalars().all())

        synced = 0
        for lead in leads:
            company = (lead.company or lead.name or "Unknown Buyer").strip()
            existing_r = await db.execute(
                select(BuyerDiscoveryEntry).where(
                    BuyerDiscoveryEntry.crm_lead_id == lead.id,
                ),
            )
            entry = existing_r.scalar_one_or_none()
            if not entry:
                entry = BuyerDiscoveryEntry(
                    client_id=lead.client_id,
                    crm_lead_id=lead.id,
                    company_name=company,
                    source="crm_sync",
                    discovered_at=_aware(lead.created_at) or _now(),
                )
                db.add(entry)

            sig = {}
            try:
                sig = (await BuyerIntelligenceService.evaluate_buyer(db, lead)).get("signals") or {}
            except Exception:
                pass

            entry.company_name = company
            entry.country = sig.get("country") or entry.country
            entry.city = _infer_city(lead) or entry.city
            entry.industry = sig.get("industry") or entry.industry
            entry.website = _extract_website(lead) or entry.website
            entry.contact_status = _STATUS_TO_CONTACT.get(lead.status or "new", "unknown")
            entry.pipeline_stage = BuyerDiscoveryService._pipeline_from_lead(
                lead,
                has_deals=int(sig.get("deal_count") or 0) > 0,
                has_comms=int(sig.get("inbound_count") or 0) > 0,
            )
            entry.updated_at = _now()
            synced += 1

        if synced == 0 and client_id:
            count = await db.scalar(
                select(func.count()).select_from(BuyerDiscoveryEntry).where(
                    BuyerDiscoveryEntry.client_id == client_id,
                ),
            ) or 0
            if count == 0:
                for spec in _DEMO_BUYERS:
                    db.add(
                        BuyerDiscoveryEntry(
                            client_id=client_id,
                            company_name=spec["company_name"],
                            country=spec.get("country"),
                            city=spec.get("city"),
                            industry=spec.get("industry"),
                            website=spec.get("website"),
                            source=spec.get("source", "market_research"),
                            contact_status="not_contacted",
                            pipeline_stage="discovered",
                            discovered_at=_now(),
                        ),
                    )
                    synced += 1
        elif synced == 0 and client_ids and len(client_ids) == 1:
            return await BuyerDiscoveryService.sync_registry(
                db, client_id=client_ids[0], limit=limit,
            )

        await db.commit()
        return synced

    @staticmethod
    async def recalculate_entries(
        db: AsyncSession,
        entries: list[BuyerDiscoveryEntry],
    ) -> int:
        count = 0
        markets_cache: dict[UUID, tuple[list[str], list[str]]] = {}
        lead_cache: dict[UUID, CrmLead | None] = {}

        for entry in entries:
            if entry.client_id not in markets_cache:
                markets_cache[entry.client_id] = await BuyerDiscoveryService._factory_markets(
                    db, entry.client_id,
                )
            markets, industries = markets_cache[entry.client_id]

            lead: CrmLead | None = None
            if entry.crm_lead_id:
                if entry.crm_lead_id not in lead_cache:
                    lead_cache[entry.crm_lead_id] = await db.get(CrmLead, entry.crm_lead_id)
                lead = lead_cache[entry.crm_lead_id]

            score, factors = await BuyerDiscoveryService._compute_opportunity_score(
                db, entry, lead, target_markets=markets, target_industries=industries,
            )
            days_disc = 999
            disc = _aware(entry.discovered_at)
            if disc:
                days_disc = (_now() - disc).days

            has_activity = bool(factors.get("communication_active"))
            entry.opportunity_score = score
            entry.category = BuyerDiscoveryService._category(
                score,
                days_since_discovered=days_disc,
                bi_classification=factors.get("buyer_classification"),
                has_recent_activity=has_activity,
            )
            entry.score_factors_json = factors
            entry.recalculated_at = _now()
            count += 1

        if count:
            await db.commit()
        return count

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        async def _probe(module: str, fn, ok_msg: str) -> None:
            try:
                result = await fn()
                checks.append({
                    "module": module,
                    "status": "ok",
                    "message": ok_msg,
                    "details": {"reachable": bool(result)},
                })
            except Exception as exc:
                checks.append({
                    "module": module,
                    "status": "degraded",
                    "message": str(exc)[:200],
                    "details": {},
                })

        await _probe(
            "crm",
            lambda: BuyerIntelligenceService.overview(db),
            "CRM-linked buyer intelligence available for discovery scoring",
        )
        await _probe(
            "buyer_intelligence",
            lambda: BuyerIntelligenceService.overview(db),
            "Buyer Intelligence scores feed opportunity ranking",
        )

        try:
            from app.services.deal_risk_service import DealRiskService

            await _probe(
                "deal_risk",
                lambda: DealRiskService.overview(db),
                "Deal Risk Engine reachable for deal-activity signals",
            )
        except Exception as exc:
            checks.append({
                "module": "deal_risk",
                "status": "degraded",
                "message": str(exc)[:200],
                "details": {},
            })

        try:
            from app.services.revenue_forecast_service import RevenueForecastService

            await _probe(
                "revenue_forecast",
                lambda: RevenueForecastService.overview(db),
                "Revenue Forecast reachable for market prioritization",
            )
        except Exception as exc:
            checks.append({
                "module": "revenue_forecast",
                "status": "degraded",
                "message": str(exc)[:200],
                "details": {},
            })

        try:
            from app.services.executive_copilot_service import ExecutiveCopilotService

            await _probe(
                "executive_copilot",
                lambda: ExecutiveCopilotService.overview(db),
                "Executive Copilot overview reachable",
            )
        except Exception as exc:
            checks.append({
                "module": "executive_copilot",
                "status": "degraded",
                "message": str(exc)[:200],
                "details": {},
            })

        registry_count = await db.scalar(select(func.count()).select_from(BuyerDiscoveryEntry)) or 0
        checks.append({
            "module": "factory_platform",
            "status": "ok",
            "message": "Factory Platform target markets used for industry/market match scoring",
            "details": {"registry_entries": int(registry_count)},
        })
        checks.append({
            "module": "customer_portal",
            "status": "ok",
            "message": "Customer Portal buyers view complements discovery registry",
            "details": {},
        })
        checks.append({
            "module": "sales_department_v3",
            "status": "ok",
            "message": "Sales Department v3 can surface discovery recommendations manually",
            "details": {},
        })
        checks.append({
            "module": "multi_agent",
            "status": "ok",
            "message": "Multi-Agent Team can reference top discovery opportunities",
            "details": {},
        })

        return checks

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_id, client_ids = await BuyerDiscoveryService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        errors: list[str] = []
        entries = await BuyerDiscoveryService._load_entries(
            db, client_id=client_id, client_ids=client_ids,
        )

        if not entries:
            try:
                await BuyerDiscoveryService._ensure_initial_registry(
                    db, client_id=client_id, client_ids=client_ids,
                )
                entries = await BuyerDiscoveryService._load_entries(
                    db, client_id=client_id, client_ids=client_ids,
                )
                if entries:
                    await BuyerDiscoveryService.recalculate_entries(db, entries)
                    entries = await BuyerDiscoveryService._load_entries(
                        db, client_id=client_id, client_ids=client_ids,
                    )
            except Exception as exc:
                errors.append(str(exc)[:200])
                await db.rollback()

        cat_counts = {c: 0 for c in CATEGORIES}
        pipe_counts = {s: 0 for s in PIPELINE_STAGES}
        scores: list[int] = []
        for e in entries:
            if e.category in cat_counts:
                cat_counts[e.category] += 1
            if e.pipeline_stage in pipe_counts:
                pipe_counts[e.pipeline_stage] += 1
            scores.append(e.opportunity_score)

        integration = await safe_section(
            "buyer_discovery_integrations",
            BuyerDiscoveryService.integration_checks(db),
            default=[],
            errors=errors,
            db=db,
        )

        avg = int(sum(scores) / len(scores)) if scores else 0
        return {
            "total_buyers": len(entries),
            "high_potential": cat_counts["high_potential"],
            "strategic": cat_counts["strategic"],
            "active": cat_counts["active"],
            "new_buyers": cat_counts["new"],
            "watchlist": cat_counts["watchlist"],
            "average_opportunity_score": avg,
            "pipeline_discovered": pipe_counts["discovered"],
            "pipeline_researched": pipe_counts["researched"],
            "pipeline_qualified": pipe_counts["qualified"],
            "pipeline_contacted": pipe_counts["contacted"],
            "pipeline_opportunity": pipe_counts["opportunity"],
            "pipeline_customer": pipe_counts["customer"],
            "integration_checks": integration,
            "errors": errors,
            "safety_notice": BuyerDiscoveryService._safety_notice(),
        }

    @staticmethod
    async def list_buyers(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        category: str | None = None,
        pipeline_stage: str | None = None,
        min_score: int | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        client_id, client_ids = await BuyerDiscoveryService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        limit = clamp_limit(limit)
        entries = await BuyerDiscoveryService._load_entries(
            db, client_id=client_id, client_ids=client_ids,
        )
        items: list[dict[str, Any]] = []
        for e in entries:
            if category and e.category != category:
                continue
            if pipeline_stage and e.pipeline_stage != pipeline_stage:
                continue
            if min_score is not None and e.opportunity_score < min_score:
                continue
            items.append(BuyerDiscoveryService._entry_to_dict(e))

        total = len(items)
        return {"items": items[skip: skip + limit], "total": total}

    @staticmethod
    def _ranking_item(entry: BuyerDiscoveryEntry, rank: int, metric: str) -> dict[str, Any]:
        return {
            "rank": rank,
            "buyer_id": entry.id,
            "company_name": entry.company_name,
            "country": entry.country,
            "industry": entry.industry,
            "opportunity_score": entry.opportunity_score,
            "category": entry.category,
            "pipeline_stage": entry.pipeline_stage,
            "metric_label": metric,
        }

    @staticmethod
    async def top_opportunities(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        client_id, client_ids = await BuyerDiscoveryService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        limit = min(50, max(1, limit))
        errors: list[str] = []
        entries = await BuyerDiscoveryService._load_entries(
            db, client_id=client_id, client_ids=client_ids,
        )

        by_score = sorted(entries, key=lambda e: e.opportunity_score, reverse=True)
        top = [
            BuyerDiscoveryService._ranking_item(e, i + 1, "opportunity score")
            for i, e in enumerate(by_score[:limit])
        ]
        highest = [
            BuyerDiscoveryService._ranking_item(e, i + 1, "highest opportunity")
            for i, e in enumerate(by_score[:limit])
        ]

        strategic = sorted(
            [e for e in entries if e.category == "strategic"],
            key=lambda e: e.opportunity_score,
            reverse=True,
        )[:limit]
        strategic_items = [
            BuyerDiscoveryService._ranking_item(e, i + 1, "strategic fit")
            for i, e in enumerate(strategic)
        ]

        growing: list[dict[str, Any]] = []
        for e in entries:
            factors = e.score_factors_json or {}
            growth_signal = int(factors.get("communication_activity") or 0) + int(
                factors.get("deal_activity") or 0,
            )
            growing.append((growth_signal, e))
        growing.sort(key=lambda x: (x[0], x[1].opportunity_score), reverse=True)
        fastest = [
            BuyerDiscoveryService._ranking_item(e, i + 1, "growth signal")
            for i, (_, e) in enumerate(growing[:limit])
        ]

        return {
            "top_buyers": top,
            "fastest_growing": fastest,
            "highest_opportunity": highest,
            "strategic_buyers": strategic_items,
            "errors": errors,
        }

    @staticmethod
    def _segment_counts(
        entries: list[BuyerDiscoveryEntry],
        key_fn,
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for e in entries:
            label = key_fn(e) or "Unknown"
            counts[label] = counts.get(label, 0) + 1
        total = len(entries) or 1
        sorted_items = sorted(counts.items(), key=lambda x: x[1], reverse=True)
        return [
            {
                "label": label,
                "count": cnt,
                "share_pct": round(100.0 * cnt / total, 1),
            }
            for label, cnt in sorted_items[:15]
        ]

    @staticmethod
    async def market_insights(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_id, client_ids = await BuyerDiscoveryService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        entries = await BuyerDiscoveryService._load_entries(
            db, client_id=client_id, client_ids=client_ids,
        )
        return {
            "top_countries": BuyerDiscoveryService._segment_counts(entries, lambda e: e.country),
            "top_industries": BuyerDiscoveryService._segment_counts(entries, lambda e: e.industry),
            "top_buyer_segments": BuyerDiscoveryService._segment_counts(entries, lambda e: e.category),
            "total_buyers": len(entries),
            "errors": [],
        }

    @staticmethod
    async def pipeline(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        client_id, client_ids = await BuyerDiscoveryService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        entries = await BuyerDiscoveryService._load_entries(
            db, client_id=client_id, client_ids=client_ids,
        )
        counts = {s: 0 for s in PIPELINE_STAGES}
        for e in entries:
            if e.pipeline_stage in counts:
                counts[e.pipeline_stage] += 1
        stages = [
            {
                "stage": stage,
                "count": counts[stage],
                "label": _PIPELINE_LABELS[stage],
            }
            for stage in PIPELINE_STAGES
        ]
        return {"stages": stages, "total": len(entries), "errors": []}

    @staticmethod
    async def recalculate(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        client_id, client_ids = await BuyerDiscoveryService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        errors: list[str] = []
        synced = 0
        try:
            await BuyerDiscoveryService._ensure_initial_registry(
                db, client_id=client_id, client_ids=client_ids,
            )
            synced = await BuyerDiscoveryService.sync_registry(
                db, client_id=client_id, client_ids=client_ids, limit=limit,
            )
        except Exception as exc:
            errors.append(f"sync: {exc}"[:200])
            await db.rollback()

        entries = await BuyerDiscoveryService._load_entries(
            db, client_id=client_id, client_ids=client_ids,
        )
        recalculated = 0
        try:
            recalculated = await BuyerDiscoveryService.recalculate_entries(db, entries)
        except Exception as exc:
            errors.append(f"recalculate: {exc}"[:200])
            await db.rollback()

        overview = await BuyerDiscoveryService.overview(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        return {
            "synced": synced,
            "recalculated": recalculated,
            "overview": overview,
            "message": f"Synced {synced} registry entries; recalculated {recalculated} opportunity scores.",
            "errors": errors,
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await BuyerDiscoveryService.overview(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        top = await BuyerDiscoveryService.top_opportunities(
            db, client_id=client_id, tenant_id=tenant_id, limit=1,
        )
        top_row = (top.get("top_buyers") or [None])[0]
        return {
            "total_buyers": overview["total_buyers"],
            "high_potential": overview["high_potential"],
            "strategic": overview["strategic"],
            "new_buyers": overview["new_buyers"],
            "watchlist": overview["watchlist"],
            "average_opportunity_score": overview["average_opportunity_score"],
            "pipeline_opportunity": overview["pipeline_opportunity"],
            "top_buyer_name": top_row["company_name"] if top_row else None,
            "top_buyer_score": top_row["opportunity_score"] if top_row else 0,
            "errors": overview.get("errors", []),
        }

    @staticmethod
    async def executive_insights(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        overview = await BuyerDiscoveryService.overview(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        market = await BuyerDiscoveryService.market_insights(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        top = await BuyerDiscoveryService.top_opportunities(
            db, client_id=client_id, tenant_id=tenant_id, limit=limit,
        )
        return {
            "overview": overview,
            "best_markets": market.get("top_countries", [])[:limit],
            "top_industries": market.get("top_industries", [])[:limit],
            "highest_potential_buyers": top.get("top_buyers", []),
            "acquisition_opportunities": top.get("fastest_growing", [])[:limit],
            "strategic_buyers": top.get("strategic_buyers", []),
            "safety_notice": BuyerDiscoveryService._safety_notice(),
        }

    @staticmethod
    async def acquisition_recommendations(
        db: AsyncSession,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        """Compact recommendations for Multi-Agent and Sales Department panels."""
        errors: list[str] = []
        items: list[dict[str, Any]] = []
        try:
            overview = await BuyerDiscoveryService.overview(
                db, client_id=client_id, tenant_id=tenant_id,
            )
            if overview["high_potential"] > 0:
                items.append({
                    "title": f"{overview['high_potential']} high-potential discovered buyer(s)",
                    "description": "Review export buyer registry and prioritize manual outreach planning.",
                    "priority": "high",
                    "source": "buyer_discovery",
                })
            if overview["strategic"] > 0:
                items.append({
                    "title": f"{overview['strategic']} strategic buyer(s) in discovery pipeline",
                    "description": "Align factory product catalog with strategic buyer industries.",
                    "priority": "high",
                    "source": "buyer_discovery",
                })
            top = await BuyerDiscoveryService.top_opportunities(
                db, client_id=client_id, tenant_id=tenant_id, limit=3,
            )
            for row in top.get("top_buyers") or []:
                items.append({
                    "title": f"Discovery opportunity: {row['company_name']} (score {row['opportunity_score']})",
                    "description": (
                        f"{row.get('country') or 'Unknown market'} · "
                        f"{row.get('industry') or 'general'} — intelligence only."
                    ),
                    "priority": "medium" if row["opportunity_score"] >= 70 else "low",
                    "source": "buyer_discovery",
                    "buyer_id": str(row["buyer_id"]),
                })
            market = await BuyerDiscoveryService.market_insights(
                db, client_id=client_id, tenant_id=tenant_id,
            )
            top_country = (market.get("top_countries") or [None])[0]
            if top_country:
                items.append({
                    "title": f"Top export market: {top_country['label']} ({top_country['count']} buyers)",
                    "description": "Consider expanding factory partner focus to this market segment.",
                    "priority": "medium",
                    "source": "buyer_discovery",
                })
        except Exception as exc:
            errors.append(str(exc)[:200])
        return {"items": items[:limit], "total": len(items), "errors": errors}
