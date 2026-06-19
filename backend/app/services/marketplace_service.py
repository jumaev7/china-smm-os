"""Marketplace & Lead Exchange v1 — opportunity registry and tenant participation only."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.marketplace import (
    MarketplaceOpportunity,
    MarketplaceOpportunityClaim,
    MarketplaceOpportunityInterest,
    MarketplaceOpportunityView,
)
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

MARKER = "[Marketplace]"

OPPORTUNITY_TYPES = frozenset({
    "distributor", "importer", "wholesaler", "retailer", "project", "partnership",
})
STATUSES = frozenset({"open", "in_review", "claimed", "closed"})
VISIBILITIES = frozenset({"public", "private", "tenant_only"})
STRATEGIC_TYPES = frozenset({"partnership", "project", "distributor"})

_DEMO_OPPORTUNITIES = [
    {
        "title": "Electronics distributor — Central Asia",
        "description": "Regional distributor seeking OEM electronics supply from China.",
        "buyer_company": "Central Asia Tech Distribution",
        "country": "Kazakhstan",
        "industry": "electronics",
        "opportunity_type": "distributor",
        "estimated_value": Decimal("250000"),
        "visibility": "public",
    },
    {
        "title": "Construction materials importer",
        "description": "Importer evaluating long-term factory partnerships for building materials.",
        "buyer_company": "Gulf Build Imports LLC",
        "country": "UAE",
        "industry": "construction",
        "opportunity_type": "importer",
        "estimated_value": Decimal("180000"),
        "visibility": "public",
    },
    {
        "title": "Retail chain wholesale program",
        "description": "Multi-store retail group launching private-label household goods.",
        "buyer_company": "EuroRetail Group",
        "country": "Germany",
        "industry": "retail",
        "opportunity_type": "wholesaler",
        "estimated_value": Decimal("320000"),
        "visibility": "tenant_only",
    },
    {
        "title": "Smart factory partnership",
        "description": "Strategic co-manufacturing partnership for automotive components.",
        "buyer_company": "AutoParts Global",
        "country": "Turkey",
        "industry": "automotive",
        "opportunity_type": "partnership",
        "estimated_value": Decimal("500000"),
        "visibility": "public",
    },
    {
        "title": "Hospital equipment project tender",
        "description": "Government-linked hospital modernization project — phased procurement.",
        "buyer_company": "MedEquip Projects",
        "country": "Uzbekistan",
        "industry": "medical",
        "opportunity_type": "project",
        "estimated_value": Decimal("420000"),
        "visibility": "public",
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _compute_rank_score(opp: MarketplaceOpportunity) -> int:
    score = 20
    if opp.estimated_value:
        val = float(opp.estimated_value)
        if val >= 400000:
            score += 35
        elif val >= 200000:
            score += 25
        elif val >= 100000:
            score += 15
        else:
            score += 8
    if opp.opportunity_type in STRATEGIC_TYPES:
        score += 15
    if opp.status == "open":
        score += 10
    return min(100, score)


class MarketplaceService:
    """Factory partner marketplace — exchange only; no CRM/messaging/deal automation."""

    @staticmethod
    def _safety_notice() -> str:
        return (
            "Opportunity exchange only — no automatic messaging, CRM writes, or deal creation. "
            "Claims are manual."
        )

    @staticmethod
    def _opp_to_dict(
        opp: MarketplaceOpportunity,
        *,
        view_count: int = 0,
        interest_count: int = 0,
        claim_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "id": opp.id,
            "title": opp.title,
            "description": opp.description,
            "buyer_company": opp.buyer_company,
            "country": opp.country,
            "industry": opp.industry,
            "opportunity_type": opp.opportunity_type,
            "estimated_value": opp.estimated_value,
            "status": opp.status,
            "visibility": opp.visibility,
            "created_by_tenant": opp.created_by_tenant,
            "rank_score": opp.rank_score,
            "view_count": view_count,
            "interest_count": interest_count,
            "claim_count": claim_count,
            "created_at": opp.created_at,
            "updated_at": opp.updated_at,
        }

    @staticmethod
    async def _default_tenant_id(db: AsyncSession) -> UUID | None:
        result = await db.execute(select(Tenant.id).limit(1))
        return result.scalar_one_or_none()

    @staticmethod
    async def _ensure_demo_seed(db: AsyncSession) -> None:
        count = await db.scalar(select(func.count()).select_from(MarketplaceOpportunity)) or 0
        if count > 0:
            return
        tenant_id = await MarketplaceService._default_tenant_id(db)
        for row in _DEMO_OPPORTUNITIES:
            opp = MarketplaceOpportunity(
                title=row["title"],
                description=row["description"],
                buyer_company=row["buyer_company"],
                country=row["country"],
                industry=row["industry"],
                opportunity_type=row["opportunity_type"],
                estimated_value=row["estimated_value"],
                status="open",
                visibility=row["visibility"],
                created_by_tenant=tenant_id,
            )
            opp.rank_score = _compute_rank_score(opp)
            db.add(opp)
        await db.commit()
        logger.info("%s seeded %d demo opportunities", MARKER, len(_DEMO_OPPORTUNITIES))

    @staticmethod
    async def _participation_counts(
        db: AsyncSession,
        opportunity_ids: list[UUID],
    ) -> dict[UUID, dict[str, int]]:
        if not opportunity_ids:
            return {}
        views = await db.execute(
            select(
                MarketplaceOpportunityView.opportunity_id,
                func.count(),
            )
            .where(MarketplaceOpportunityView.opportunity_id.in_(opportunity_ids))
            .group_by(MarketplaceOpportunityView.opportunity_id),
        )
        interests = await db.execute(
            select(
                MarketplaceOpportunityInterest.opportunity_id,
                func.count(),
            )
            .where(MarketplaceOpportunityInterest.opportunity_id.in_(opportunity_ids))
            .group_by(MarketplaceOpportunityInterest.opportunity_id),
        )
        claims = await db.execute(
            select(
                MarketplaceOpportunityClaim.opportunity_id,
                func.count(),
            )
            .where(MarketplaceOpportunityClaim.opportunity_id.in_(opportunity_ids))
            .group_by(MarketplaceOpportunityClaim.opportunity_id),
        )
        out: dict[UUID, dict[str, int]] = {
            oid: {"views": 0, "interests": 0, "claims": 0} for oid in opportunity_ids
        }
        for oid, cnt in views.all():
            out[oid]["views"] = int(cnt)
        for oid, cnt in interests.all():
            out[oid]["interests"] = int(cnt)
        for oid, cnt in claims.all():
            out[oid]["claims"] = int(cnt)
        return out

    @staticmethod
    async def _load_opportunities(
        db: AsyncSession,
        *,
        country: str | None = None,
        industry: str | None = None,
        opportunity_type: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        status: str | None = None,
        visibility: str | None = None,
        viewer_tenant_id: UUID | None = None,
    ) -> list[MarketplaceOpportunity]:
        q = select(MarketplaceOpportunity).order_by(
            MarketplaceOpportunity.rank_score.desc(),
            MarketplaceOpportunity.created_at.desc(),
        )
        if country:
            q = q.where(func.lower(MarketplaceOpportunity.country) == country.lower())
        if industry:
            q = q.where(func.lower(MarketplaceOpportunity.industry) == industry.lower())
        if opportunity_type:
            q = q.where(MarketplaceOpportunity.opportunity_type == opportunity_type)
        if status:
            q = q.where(MarketplaceOpportunity.status == status)
        if min_value is not None:
            q = q.where(MarketplaceOpportunity.estimated_value >= min_value)
        if max_value is not None:
            q = q.where(MarketplaceOpportunity.estimated_value <= max_value)
        if visibility:
            q = q.where(MarketplaceOpportunity.visibility == visibility)
        elif viewer_tenant_id:
            q = q.where(
                (MarketplaceOpportunity.visibility == "public")
                | (
                    (MarketplaceOpportunity.visibility == "tenant_only")
                    & (MarketplaceOpportunity.created_by_tenant == viewer_tenant_id)
                )
            )
        else:
            q = q.where(MarketplaceOpportunity.visibility == "public")
        result = await db.execute(q)
        rows = list(result.scalars().all())
        if viewer_tenant_id:
            return [
                r for r in rows
                if r.visibility != "private" or r.created_by_tenant == viewer_tenant_id
            ]
        return [r for r in rows if r.visibility != "private"]

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

        from app.services.buyer_discovery_service import BuyerDiscoveryService
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.deal_risk_service import DealRiskService
        from app.services.revenue_forecast_service import RevenueForecastService

        await _probe(
            "buyer_discovery",
            lambda: BuyerDiscoveryService.overview(db),
            "Buyer Discovery feeds marketplace opportunity context",
        )
        await _probe(
            "buyer_intelligence",
            lambda: BuyerIntelligenceService.overview(db),
            "Buyer Intelligence available for opportunity ranking context",
        )
        await _probe(
            "deal_risk",
            lambda: DealRiskService.overview(db),
            "Deal Risk Engine integration probe (read-only)",
        )
        await _probe(
            "revenue_forecast",
            lambda: RevenueForecastService.overview(db),
            "Revenue Forecast integration probe (read-only)",
        )
        await _probe(
            "factory_platform",
            lambda: MarketplaceService.summary_widget(db),
            "Factory Platform can surface marketplace widget data",
        )
        await _probe(
            "customer_portal",
            lambda: MarketplaceService.summary_widget(db),
            "Customer Portal can surface buyer opportunity exchange data",
        )
        await _probe(
            "executive_copilot",
            lambda: MarketplaceService.executive_summary(db, limit=3),
            "Executive Copilot marketplace summary available",
        )
        return checks

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        await MarketplaceService._ensure_demo_seed(db)
        errors: list[str] = []
        opps = await MarketplaceService._load_opportunities(db, viewer_tenant_id=tenant_id)
        status_counts = {s: 0 for s in STATUSES}
        values: list[float] = []
        for o in opps:
            status_counts[o.status] = status_counts.get(o.status, 0) + 1
            if o.estimated_value:
                values.append(float(o.estimated_value))

        total_views = await db.scalar(select(func.count()).select_from(MarketplaceOpportunityView)) or 0
        total_interests = await db.scalar(
            select(func.count()).select_from(MarketplaceOpportunityInterest),
        ) or 0
        total_claims = await db.scalar(
            select(func.count()).select_from(MarketplaceOpportunityClaim),
        ) or 0

        integration = await safe_section(
            "marketplace_integrations",
            MarketplaceService.integration_checks(db),
            default=[],
            errors=errors,
            db=db,
        )

        avg_val = sum(values) / len(values) if values else 0.0
        return {
            "total_opportunities": len(opps),
            "open_opportunities": status_counts.get("open", 0),
            "in_review": status_counts.get("in_review", 0),
            "claimed": status_counts.get("claimed", 0),
            "closed": status_counts.get("closed", 0),
            "total_views": int(total_views),
            "total_interests": int(total_interests),
            "total_claims": int(total_claims),
            "average_estimated_value": round(avg_val, 2),
            "integration_checks": integration,
            "errors": errors,
            "safety_notice": MarketplaceService._safety_notice(),
        }

    @staticmethod
    async def list_opportunities(
        db: AsyncSession,
        *,
        country: str | None = None,
        industry: str | None = None,
        opportunity_type: str | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        status: str | None = None,
        tenant_id: UUID | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        await MarketplaceService._ensure_demo_seed(db)
        limit = clamp_limit(limit)
        opps = await MarketplaceService._load_opportunities(
            db,
            country=country,
            industry=industry,
            opportunity_type=opportunity_type,
            min_value=min_value,
            max_value=max_value,
            status=status,
            viewer_tenant_id=tenant_id,
        )
        ids = [o.id for o in opps]
        counts = await MarketplaceService._participation_counts(db, ids)
        items = []
        for o in opps[skip : skip + limit]:
            c = counts.get(o.id, {})
            items.append(
                MarketplaceService._opp_to_dict(
                    o,
                    view_count=c.get("views", 0),
                    interest_count=c.get("interests", 0),
                    claim_count=c.get("claims", 0),
                ),
            )
        return {"items": items, "total": len(opps)}

    @staticmethod
    def _ranking_item(opp: MarketplaceOpportunity, rank: int, metric: str) -> dict[str, Any]:
        return {
            "rank": rank,
            "opportunity_id": opp.id,
            "title": opp.title,
            "buyer_company": opp.buyer_company,
            "country": opp.country,
            "industry": opp.industry,
            "opportunity_type": opp.opportunity_type,
            "estimated_value": opp.estimated_value,
            "rank_score": opp.rank_score,
            "metric_label": metric,
        }

    @staticmethod
    async def top_opportunities(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        await MarketplaceService._ensure_demo_seed(db)
        limit = min(50, max(1, limit))
        errors: list[str] = []
        opps = await MarketplaceService._load_opportunities(db, viewer_tenant_id=tenant_id)
        best = sorted(opps, key=lambda o: (-o.rank_score, -float(o.estimated_value or 0)))[:limit]
        newest = sorted(opps, key=lambda o: o.created_at, reverse=True)[:limit]
        strategic = [
            o for o in opps if o.opportunity_type in STRATEGIC_TYPES
        ]
        strategic = sorted(
            strategic, key=lambda o: (-o.rank_score, -float(o.estimated_value or 0)),
        )[:limit]
        return {
            "best_opportunities": [
                MarketplaceService._ranking_item(o, i + 1, "Highest rank score")
                for i, o in enumerate(best)
            ],
            "newest_opportunities": [
                MarketplaceService._ranking_item(o, i + 1, "Recently listed")
                for i, o in enumerate(newest)
            ],
            "strategic_opportunities": [
                MarketplaceService._ranking_item(o, i + 1, "Strategic buyer type")
                for i, o in enumerate(strategic)
            ],
            "errors": errors,
        }

    @staticmethod
    def _segments(rows: list[tuple[str | None, int]], total: int) -> list[dict[str, Any]]:
        out = []
        for label, count in rows:
            if not label:
                continue
            out.append({
                "label": label,
                "count": count,
                "share_pct": round(100.0 * count / total, 1) if total else 0.0,
            })
        return out

    @staticmethod
    async def insights(db: AsyncSession, *, tenant_id: UUID | None = None) -> dict[str, Any]:
        await MarketplaceService._ensure_demo_seed(db)
        errors: list[str] = []
        opps = await MarketplaceService._load_opportunities(db, viewer_tenant_id=tenant_id)
        total = len(opps) or 1

        country_map: dict[str, int] = {}
        industry_map: dict[str, int] = {}
        for o in opps:
            if o.country:
                country_map[o.country] = country_map.get(o.country, 0) + 1
            if o.industry:
                industry_map[o.industry] = industry_map.get(o.industry, 0) + 1

        top_countries = MarketplaceService._segments(
            sorted(country_map.items(), key=lambda x: -x[1])[:8],
            len(opps),
        )
        top_industries = MarketplaceService._segments(
            sorted(industry_map.items(), key=lambda x: -x[1])[:8],
            len(opps),
        )

        tenant_activity = await db.execute(
            select(
                MarketplaceOpportunityInterest.tenant_id,
                func.count(),
            )
            .group_by(MarketplaceOpportunityInterest.tenant_id)
            .order_by(func.count().desc())
            .limit(5),
        )
        active_tenants = []
        for tid, cnt in tenant_activity.all():
            tenant = await db.get(Tenant, tid)
            active_tenants.append({
                "tenant_id": tid,
                "tenant_name": tenant.company_name if tenant else str(tid)[:8],
                "activity_count": int(cnt),
            })

        valuable = sorted(
            opps, key=lambda o: (-float(o.estimated_value or 0), -o.rank_score),
        )[:8]
        most_valuable = [
            MarketplaceService._ranking_item(o, i + 1, "Highest estimated value")
            for i, o in enumerate(valuable)
        ]

        return {
            "top_industries": top_industries,
            "top_countries": top_countries,
            "most_active_tenants": active_tenants,
            "most_valuable_opportunities": most_valuable,
            "total_opportunities": len(opps),
            "errors": errors,
        }

    @staticmethod
    async def activity(
        db: AsyncSession,
        *,
        limit: int = 50,
    ) -> dict[str, Any]:
        await MarketplaceService._ensure_demo_seed(db)
        limit = min(100, max(1, limit))
        errors: list[str] = []
        items: list[dict[str, Any]] = []

        opp_titles: dict[UUID, str] = {}
        result = await db.execute(select(MarketplaceOpportunity))
        for o in result.scalars().all():
            opp_titles[o.id] = o.title

        for row in (
            await db.execute(
                select(MarketplaceOpportunityView)
                .order_by(MarketplaceOpportunityView.viewed_at.desc())
                .limit(limit),
            )
        ).scalars().all():
            tenant = await db.get(Tenant, row.tenant_id)
            items.append({
                "id": row.id,
                "activity_type": "view",
                "opportunity_id": row.opportunity_id,
                "opportunity_title": opp_titles.get(row.opportunity_id, "Opportunity"),
                "tenant_id": row.tenant_id,
                "tenant_label": tenant.company_name if tenant else None,
                "occurred_at": row.viewed_at,
                "detail": None,
            })

        for row in (
            await db.execute(
                select(MarketplaceOpportunityInterest)
                .order_by(MarketplaceOpportunityInterest.expressed_at.desc())
                .limit(limit),
            )
        ).scalars().all():
            tenant = await db.get(Tenant, row.tenant_id)
            items.append({
                "id": row.id,
                "activity_type": "interest",
                "opportunity_id": row.opportunity_id,
                "opportunity_title": opp_titles.get(row.opportunity_id, "Opportunity"),
                "tenant_id": row.tenant_id,
                "tenant_label": tenant.company_name if tenant else None,
                "occurred_at": row.expressed_at,
                "detail": row.note,
            })

        for row in (
            await db.execute(
                select(MarketplaceOpportunityClaim)
                .order_by(MarketplaceOpportunityClaim.claimed_at.desc())
                .limit(limit),
            )
        ).scalars().all():
            tenant = await db.get(Tenant, row.tenant_id)
            items.append({
                "id": row.id,
                "activity_type": "claim",
                "opportunity_id": row.opportunity_id,
                "opportunity_title": opp_titles.get(row.opportunity_id, "Opportunity"),
                "tenant_id": row.tenant_id,
                "tenant_label": tenant.company_name if tenant else None,
                "occurred_at": row.claimed_at,
                "detail": "Manual claim recorded",
            })

        for o in sorted(opp_titles.keys(), key=lambda k: k, reverse=True)[:5]:
            opp = await db.get(MarketplaceOpportunity, o)
            if opp:
                items.append({
                    "id": opp.id,
                    "activity_type": "created",
                    "opportunity_id": opp.id,
                    "opportunity_title": opp.title,
                    "tenant_id": opp.created_by_tenant,
                    "tenant_label": None,
                    "occurred_at": opp.created_at,
                    "detail": f"Listed — {opp.buyer_company}",
                })

        items.sort(key=lambda x: x["occurred_at"], reverse=True)
        items = items[:limit]
        return {"items": items, "total": len(items), "errors": errors}

    @staticmethod
    async def summary_widget(db: AsyncSession, *, tenant_id: UUID | None = None) -> dict[str, Any]:
        overview = await MarketplaceService.overview(db, tenant_id=tenant_id)
        opps = await MarketplaceService._load_opportunities(db, viewer_tenant_id=tenant_id)
        top = max(opps, key=lambda o: float(o.estimated_value or 0), default=None)
        return {
            "total_opportunities": overview["total_opportunities"],
            "open_opportunities": overview["open_opportunities"],
            "total_interests": overview["total_interests"],
            "top_opportunity_title": top.title if top else None,
            "top_opportunity_value": float(top.estimated_value) if top and top.estimated_value else 0.0,
            "errors": overview.get("errors") or [],
        }

    @staticmethod
    async def executive_summary(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        overview = await MarketplaceService.overview(db, tenant_id=tenant_id)
        top = await MarketplaceService.top_opportunities(db, tenant_id=tenant_id, limit=limit)
        insights = await MarketplaceService.insights(db, tenant_id=tenant_id)
        return {
            "overview": overview,
            "best_opportunities": top.get("best_opportunities") or [],
            "strategic_opportunities": top.get("strategic_opportunities") or [],
            "top_industries": insights.get("top_industries") or [],
            "safety_notice": MarketplaceService._safety_notice(),
        }

    @staticmethod
    async def opportunity_recommendations(
        db: AsyncSession,
        *,
        limit: int = 3,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        top = await MarketplaceService.top_opportunities(db, tenant_id=tenant_id, limit=limit)
        items = []
        for row in top.get("best_opportunities") or []:
            items.append({
                "title": f"Marketplace: {row['title']} — {row['buyer_company']}",
                "priority": "high" if row.get("rank_score", 0) >= 70 else "medium",
                "source": "marketplace",
                "opportunity_id": row.get("opportunity_id"),
                "metric_label": row.get("metric_label"),
            })
        return {"items": items, "safety_notice": MarketplaceService._safety_notice()}

    @staticmethod
    async def create_opportunity(
        db: AsyncSession,
        *,
        title: str,
        buyer_company: str,
        description: str | None = None,
        country: str | None = None,
        industry: str | None = None,
        opportunity_type: str = "distributor",
        estimated_value: Decimal | None = None,
        visibility: str = "public",
        created_by_tenant: UUID | None = None,
    ) -> dict[str, Any]:
        if opportunity_type not in OPPORTUNITY_TYPES:
            opportunity_type = "distributor"
        if visibility not in VISIBILITIES:
            visibility = "public"
        if not created_by_tenant:
            created_by_tenant = await MarketplaceService._default_tenant_id(db)

        opp = MarketplaceOpportunity(
            title=title,
            description=description,
            buyer_company=buyer_company,
            country=country,
            industry=industry,
            opportunity_type=opportunity_type,
            estimated_value=estimated_value,
            status="open",
            visibility=visibility,
            created_by_tenant=created_by_tenant,
        )
        opp.rank_score = _compute_rank_score(opp)
        db.add(opp)
        await db.commit()
        await db.refresh(opp)
        return {
            "opportunity": MarketplaceService._opp_to_dict(opp),
            "message": "Opportunity registered — no automatic CRM or messaging.",
            "errors": [],
        }

    @staticmethod
    async def express_interest(
        db: AsyncSession,
        *,
        opportunity_id: UUID,
        tenant_id: UUID,
        note: str | None = None,
    ) -> dict[str, Any]:
        opp = await db.get(MarketplaceOpportunity, opportunity_id)
        if not opp:
            return {
                "recorded": False,
                "message": "Opportunity not found",
                "errors": ["not_found"],
            }
        if opp.status == "closed":
            return {
                "recorded": False,
                "message": "Opportunity is closed",
                "errors": ["closed"],
            }

        existing = await db.execute(
            select(MarketplaceOpportunityInterest).where(
                MarketplaceOpportunityInterest.opportunity_id == opportunity_id,
                MarketplaceOpportunityInterest.tenant_id == tenant_id,
            ),
        )
        if existing.scalar_one_or_none():
            return {
                "recorded": True,
                "message": "Interest already recorded — no automatic outreach triggered.",
                "errors": [],
            }

        db.add(
            MarketplaceOpportunityInterest(
                opportunity_id=opportunity_id,
                tenant_id=tenant_id,
                note=note,
            ),
        )
        if opp.status == "open":
            opp.status = "in_review"
        await db.commit()
        return {
            "recorded": True,
            "message": "Interest recorded manually — no automatic messaging or CRM writes.",
            "errors": [],
        }

    @staticmethod
    async def claim_opportunity(
        db: AsyncSession,
        *,
        opportunity_id: UUID,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        opp = await db.get(MarketplaceOpportunity, opportunity_id)
        if not opp:
            return {
                "claimed": False,
                "opportunity": None,
                "message": "Opportunity not found",
                "errors": ["not_found"],
            }
        if opp.status == "claimed":
            return {
                "claimed": False,
                "opportunity": MarketplaceService._opp_to_dict(opp),
                "message": "Opportunity already claimed — manual follow-up only.",
                "errors": ["already_claimed"],
            }
        if opp.status == "closed":
            return {
                "claimed": False,
                "opportunity": MarketplaceService._opp_to_dict(opp),
                "message": "Opportunity is closed",
                "errors": ["closed"],
            }

        db.add(
            MarketplaceOpportunityClaim(
                opportunity_id=opportunity_id,
                tenant_id=tenant_id,
            ),
        )
        opp.status = "claimed"
        opp.updated_at = _now()
        await db.commit()
        await db.refresh(opp)
        counts = await MarketplaceService._participation_counts(db, [opp.id])
        c = counts.get(opp.id, {})
        return {
            "claimed": True,
            "opportunity": MarketplaceService._opp_to_dict(
                opp,
                view_count=c.get("views", 0),
                interest_count=c.get("interests", 0),
                claim_count=c.get("claims", 0),
            ),
            "message": "Manual claim recorded — no automatic deal or CRM creation.",
            "errors": [],
        }

    @staticmethod
    async def record_view(
        db: AsyncSession,
        *,
        opportunity_id: UUID,
        tenant_id: UUID,
    ) -> None:
        db.add(
            MarketplaceOpportunityView(
                opportunity_id=opportunity_id,
                tenant_id=tenant_id,
            ),
        )
        await db.commit()
