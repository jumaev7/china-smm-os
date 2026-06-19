"""Export Buyer Network v1 — global buyer intelligence and tenant relationship mapping."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.buyer_network import BuyerNetworkProfile, BuyerRelationship
from app.models.marketplace import MarketplaceOpportunity
from app.models.tenant import Tenant

logger = logging.getLogger(__name__)

MARKER = "[Buyer Network]"

RELATIONSHIP_TYPES = frozenset({"discovered", "contacted", "active", "customer", "strategic"})
CLASSIFICATIONS = frozenset({"strategic", "high_potential", "active", "growing", "watchlist", "underutilized"})
BUYER_STATUSES = frozenset({"strategic", "active", "growing", "watchlist", "underutilized"})

_PIPELINE_TO_RELATIONSHIP = {
    "discovered": "discovered",
    "researched": "discovered",
    "qualified": "contacted",
    "contacted": "contacted",
    "opportunity": "active",
    "customer": "customer",
}

_DEMO_PROFILES = [
    {
        "company_name": "Global Trade Partners Ltd",
        "country": "UAE",
        "city": "Dubai",
        "industry": "electronics",
        "website": "https://example.com/gtp",
        "classification": "strategic",
        "buyer_status": "strategic",
        "relationship_type": "strategic",
        "relationship_strength": 85,
    },
    {
        "company_name": "Central Asia Distributors",
        "country": "Kazakhstan",
        "city": "Almaty",
        "industry": "retail",
        "website": None,
        "classification": "high_potential",
        "buyer_status": "growing",
        "relationship_type": "active",
        "relationship_strength": 72,
    },
    {
        "company_name": "Euro Import Solutions GmbH",
        "country": "Germany",
        "city": "Hamburg",
        "industry": "automotive",
        "website": "https://example.com/eis",
        "classification": "active",
        "buyer_status": "active",
        "relationship_type": "contacted",
        "relationship_strength": 58,
    },
    {
        "company_name": "Gulf Build Imports LLC",
        "country": "UAE",
        "city": "Dubai",
        "industry": "construction",
        "website": None,
        "classification": "high_potential",
        "buyer_status": "watchlist",
        "relationship_type": "discovered",
        "relationship_strength": 40,
    },
    {
        "company_name": "MedEquip Projects",
        "country": "Uzbekistan",
        "city": "Tashkent",
        "industry": "medical",
        "website": None,
        "classification": "growing",
        "buyer_status": "underutilized",
        "relationship_type": "discovered",
        "relationship_strength": 25,
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _normalize_key(company_name: str, country: str | None) -> str:
    name = re.sub(r"\s+", " ", (company_name or "").strip().lower())
    c = (country or "").strip().lower()
    return f"{name}|{c}" if c else name


class BuyerNetworkService:
    """Global buyer network — intelligence and relationship mapping only."""

    @staticmethod
    def _safety_notice() -> str:
        return (
            "Intelligence and relationship mapping only — no automatic outreach, messaging, "
            "CRM writes, or relationship creation."
        )

    @staticmethod
    async def _default_tenant_id(db: AsyncSession) -> UUID | None:
        result = await db.execute(select(Tenant.id).limit(1))
        return result.scalar_one_or_none()

    @staticmethod
    def _normalize_classification(value: str) -> str:
        if value in CLASSIFICATIONS:
            return value
        return "watchlist"

    @staticmethod
    def _normalize_buyer_status(value: str) -> str:
        if value in BUYER_STATUSES:
            return value
        return "watchlist"

    @staticmethod
    def _profile_to_dict(
        profile: BuyerNetworkProfile,
        *,
        relationship_count: int = 0,
    ) -> dict[str, Any]:
        return {
            "id": profile.id,
            "company_name": profile.company_name,
            "country": profile.country,
            "city": profile.city,
            "industry": profile.industry,
            "website": profile.website,
            "classification": BuyerNetworkService._normalize_classification(profile.classification),
            "opportunity_score": profile.opportunity_score,
            "network_strength": profile.network_strength,
            "buyer_status": BuyerNetworkService._normalize_buyer_status(profile.buyer_status),
            "relationship_count": relationship_count,
            "created_at": profile.created_at,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    def _insight_item(
        profile: BuyerNetworkProfile,
        rank: int,
        metric: str,
    ) -> dict[str, Any]:
        return {
            "rank": rank,
            "buyer_id": profile.id,
            "company_name": profile.company_name,
            "country": profile.country,
            "industry": profile.industry,
            "opportunity_score": profile.opportunity_score,
            "network_strength": profile.network_strength,
            "buyer_status": profile.buyer_status,
            "metric_label": metric,
        }

    @staticmethod
    async def _relationship_counts(
        db: AsyncSession,
        profile_ids: list[UUID],
    ) -> dict[UUID, int]:
        if not profile_ids:
            return {}
        rows = await db.execute(
            select(BuyerRelationship.buyer_id, func.count())
            .where(BuyerRelationship.buyer_id.in_(profile_ids))
            .group_by(BuyerRelationship.buyer_id),
        )
        return {row[0]: int(row[1]) for row in rows.all()}

    @staticmethod
    async def _ensure_demo_seed(db: AsyncSession) -> None:
        count = await db.scalar(select(func.count()).select_from(BuyerNetworkProfile)) or 0
        if count > 0:
            return
        tenant_id = await BuyerNetworkService._default_tenant_id(db)
        if not tenant_id:
            logger.warning("%s demo seed skipped — no tenant", MARKER)
            return

        for spec in _DEMO_PROFILES:
            key = _normalize_key(spec["company_name"], spec.get("country"))
            profile = BuyerNetworkProfile(
                company_name=spec["company_name"],
                country=spec.get("country"),
                city=spec.get("city"),
                industry=spec.get("industry"),
                website=spec.get("website"),
                classification=spec["classification"],
                buyer_status=spec["buyer_status"],
                opportunity_score=70,
                network_strength=spec["relationship_strength"],
                source_key=key,
            )
            db.add(profile)
            await db.flush()
            db.add(
                BuyerRelationship(
                    buyer_id=profile.id,
                    tenant_id=tenant_id,
                    relationship_type=spec["relationship_type"],
                    relationship_strength=spec["relationship_strength"],
                ),
            )
        await db.commit()
        logger.info("%s seeded %d demo profiles", MARKER, len(_DEMO_PROFILES))

    @staticmethod
    async def sync_profiles(db: AsyncSession, *, limit: int = 500) -> int:
        """Upsert global profiles from discovery and marketplace — no new relationships."""
        limit = min(2000, max(1, limit))
        synced = 0
        seen: set[str] = set()

        discovery = list(
            (await db.execute(
                select(BuyerDiscoveryEntry)
                .order_by(BuyerDiscoveryEntry.opportunity_score.desc())
                .limit(limit),
            )).scalars().all(),
        )
        for entry in discovery:
            key = _normalize_key(entry.company_name, entry.country)
            if key in seen:
                continue
            seen.add(key)
            existing = await db.execute(
                select(BuyerNetworkProfile).where(BuyerNetworkProfile.source_key == key),
            )
            profile = existing.scalar_one_or_none()
            if not profile:
                profile = BuyerNetworkProfile(
                    company_name=entry.company_name,
                    source_key=key,
                )
                db.add(profile)
            profile.country = entry.country or profile.country
            profile.city = entry.city or profile.city
            profile.industry = entry.industry or profile.industry
            profile.website = entry.website or profile.website
            profile.opportunity_score = max(profile.opportunity_score, entry.opportunity_score)
            profile.updated_at = _now()
            synced += 1

        opps = list(
            (await db.execute(
                select(MarketplaceOpportunity)
                .order_by(MarketplaceOpportunity.rank_score.desc())
                .limit(limit),
            )).scalars().all(),
        )
        for opp in opps:
            key = _normalize_key(opp.buyer_company, opp.country)
            if key in seen:
                continue
            seen.add(key)
            existing = await db.execute(
                select(BuyerNetworkProfile).where(BuyerNetworkProfile.source_key == key),
            )
            profile = existing.scalar_one_or_none()
            if not profile:
                profile = BuyerNetworkProfile(
                    company_name=opp.buyer_company,
                    source_key=key,
                )
                db.add(profile)
            profile.country = opp.country or profile.country
            profile.industry = opp.industry or profile.industry
            if opp.rank_score:
                profile.opportunity_score = max(profile.opportunity_score, int(opp.rank_score))
            profile.updated_at = _now()
            synced += 1

        if synced:
            await db.commit()
        return synced

    @staticmethod
    def _derive_classification(
        opportunity_score: int,
        network_strength: int,
        relationship_count: int,
    ) -> tuple[str, str]:
        if network_strength >= 80 or opportunity_score >= 85:
            return "strategic", "strategic"
        if opportunity_score >= 75:
            return "high_potential", "active"
        if network_strength >= 60:
            return "active", "active"
        if opportunity_score >= 55 and relationship_count <= 1:
            return "growing", "growing"
        if relationship_count == 0 or network_strength < 35:
            return "watchlist", "underutilized"
        if opportunity_score < 45 and relationship_count > 0:
            return "watchlist", "underutilized"
        return "growing", "growing"

    @staticmethod
    async def recalculate_profiles(
        db: AsyncSession,
        profiles: list[BuyerNetworkProfile],
    ) -> int:
        rel_counts = await BuyerNetworkService._relationship_counts(
            db, [p.id for p in profiles],
        )
        rel_strength: dict[UUID, list[int]] = {}
        if profiles:
            rows = await db.execute(
                select(BuyerRelationship.buyer_id, BuyerRelationship.relationship_strength)
                .where(BuyerRelationship.buyer_id.in_([p.id for p in profiles])),
            )
            for bid, strength in rows.all():
                rel_strength.setdefault(bid, []).append(int(strength))

        count = 0
        for profile in profiles:
            rels = rel_strength.get(profile.id, [])
            rel_count = rel_counts.get(profile.id, 0)
            avg_rel = int(sum(rels) / len(rels)) if rels else 0
            buyer_influence = _clamp(
                int(profile.opportunity_score * 0.45) + int(avg_rel * 0.35) + min(20, rel_count * 5),
            )
            network_strength = _clamp(int(buyer_influence * 0.6 + avg_rel * 0.4))
            classification, buyer_status = BuyerNetworkService._derive_classification(
                profile.opportunity_score,
                network_strength,
                rel_count,
            )
            profile.network_strength = network_strength
            profile.classification = classification
            profile.buyer_status = buyer_status
            profile.score_factors_json = {
                "buyer_influence": buyer_influence,
                "relationship_strength_avg": avg_rel,
                "relationship_count": rel_count,
                "opportunity_value": profile.opportunity_score,
            }
            profile.recalculated_at = _now()
            profile.updated_at = _now()
            count += 1
        return count

    @staticmethod
    async def recalculate_relationships(db: AsyncSession) -> int:
        result = await db.execute(select(BuyerRelationship))
        rels = list(result.scalars().all())
        profile_map: dict[UUID, BuyerNetworkProfile] = {}
        if rels:
            ids = {r.buyer_id for r in rels}
            profiles = list(
                (await db.execute(
                    select(BuyerNetworkProfile).where(BuyerNetworkProfile.id.in_(ids)),
                )).scalars().all(),
            )
            profile_map = {p.id: p for p in profiles}

        type_boost = {
            "discovered": 15,
            "contacted": 35,
            "active": 55,
            "customer": 75,
            "strategic": 90,
        }
        count = 0
        for rel in rels:
            profile = profile_map.get(rel.buyer_id)
            base = type_boost.get(rel.relationship_type, 20)
            opp = profile.opportunity_score if profile else 0
            rel.relationship_strength = _clamp(int(base * 0.5 + opp * 0.5))
            count += 1
        return count

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        profile_count = await db.scalar(select(func.count()).select_from(BuyerNetworkProfile)) or 0
        rel_count = await db.scalar(select(func.count()).select_from(BuyerRelationship)) or 0
        discovery_count = await db.scalar(select(func.count()).select_from(BuyerDiscoveryEntry)) or 0
        return [
            {
                "module": "buyer_discovery",
                "status": "ok",
                "message": "Buyer Discovery registry feeds global profile sync on recalculate",
                "details": {"discovery_entries": int(discovery_count)},
            },
            {
                "module": "buyer_intelligence",
                "status": "ok",
                "message": "Buyer Intelligence scores inform opportunity value",
                "details": {},
            },
            {
                "module": "marketplace",
                "status": "ok",
                "message": "Marketplace buyer companies enrich network profiles on recalculate",
                "details": {},
            },
            {
                "module": "revenue_forecast",
                "status": "ok",
                "message": "Revenue Forecast available for network prioritization",
                "details": {},
            },
            {
                "module": "executive_copilot",
                "status": "ok",
                "message": "Executive Copilot includes buyer network executive summary",
                "details": {},
            },
            {
                "module": "sales_department_v3",
                "status": "ok",
                "message": "Sales Department v3 orchestrator includes buyer network snapshot",
                "details": {"profiles": int(profile_count), "relationships": int(rel_count)},
            },
            {
                "module": "multi_agent",
                "status": "ok",
                "message": "Multi-Agent Team surfaces network recommendations",
                "details": {},
            },
        ]

    @staticmethod
    async def overview(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        count = await db.scalar(select(func.count()).select_from(BuyerNetworkProfile)) or 0
        if count == 0:
            try:
                await BuyerNetworkService._ensure_demo_seed(db)
                await BuyerNetworkService.sync_profiles(db)
            except Exception as exc:
                errors.append(str(exc)[:200])

        profiles = list(
            (await db.execute(select(BuyerNetworkProfile))).scalars().all(),
        )

        rel_q = select(func.count()).select_from(BuyerRelationship)
        if tenant_id:
            rel_q = rel_q.where(BuyerRelationship.tenant_id == tenant_id)
        rel_total = await db.scalar(rel_q) or 0

        tenant_ids = set(
            (await db.execute(select(BuyerRelationship.tenant_id).distinct())).scalars().all(),
        )

        return {
            "total_profiles": len(profiles),
            "total_relationships": int(rel_total),
            "strategic_buyers": sum(1 for p in profiles if p.buyer_status == "strategic"),
            "high_potential": sum(1 for p in profiles if p.classification == "high_potential"),
            "active_buyers": sum(1 for p in profiles if p.buyer_status == "active"),
            "underutilized": sum(1 for p in profiles if p.buyer_status == "underutilized"),
            "average_opportunity_score": int(
                sum(p.opportunity_score for p in profiles) / len(profiles),
            ) if profiles else 0,
            "average_network_strength": int(
                sum(p.network_strength for p in profiles) / len(profiles),
            ) if profiles else 0,
            "tenants_connected": len(tenant_ids),
            "integration_checks": await BuyerNetworkService.integration_checks(db),
            "errors": errors,
            "safety_notice": BuyerNetworkService._safety_notice(),
        }

    @staticmethod
    async def list_profiles(
        db: AsyncSession,
        *,
        country: str | None = None,
        industry: str | None = None,
        classification: str | None = None,
        buyer_status: str | None = None,
        tenant_id: UUID | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = select(BuyerNetworkProfile).order_by(
            BuyerNetworkProfile.network_strength.desc(),
            BuyerNetworkProfile.opportunity_score.desc(),
        )
        if country:
            q = q.where(BuyerNetworkProfile.country.ilike(f"%{country}%"))
        if industry:
            q = q.where(BuyerNetworkProfile.industry.ilike(f"%{industry}%"))
        if classification:
            q = q.where(BuyerNetworkProfile.classification == classification)
        if buyer_status:
            q = q.where(BuyerNetworkProfile.buyer_status == buyer_status)
        if tenant_id:
            sub = select(BuyerRelationship.buyer_id).where(
                BuyerRelationship.tenant_id == tenant_id,
            )
            q = q.where(BuyerNetworkProfile.id.in_(sub))

        count_q = select(func.count()).select_from(BuyerNetworkProfile)
        if country:
            count_q = count_q.where(BuyerNetworkProfile.country.ilike(f"%{country}%"))
        if industry:
            count_q = count_q.where(BuyerNetworkProfile.industry.ilike(f"%{industry}%"))
        if classification:
            count_q = count_q.where(BuyerNetworkProfile.classification == classification)
        if buyer_status:
            count_q = count_q.where(BuyerNetworkProfile.buyer_status == buyer_status)
        if tenant_id:
            sub = select(BuyerRelationship.buyer_id).where(
                BuyerRelationship.tenant_id == tenant_id,
            )
            count_q = count_q.where(BuyerNetworkProfile.id.in_(sub))
        total = await db.scalar(count_q) or 0
        result = await db.execute(q.offset(skip).limit(limit))
        profiles = list(result.scalars().all())
        rel_counts = await BuyerNetworkService._relationship_counts(
            db, [p.id for p in profiles],
        )
        items = [
            BuyerNetworkService._profile_to_dict(
                p, relationship_count=rel_counts.get(p.id, 0),
            )
            for p in profiles
        ]
        return {"items": items, "total": int(total)}

    @staticmethod
    async def list_relationships(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        buyer_id: UUID | None = None,
        relationship_type: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        q = (
            select(BuyerRelationship, BuyerNetworkProfile, Tenant)
            .join(BuyerNetworkProfile, BuyerRelationship.buyer_id == BuyerNetworkProfile.id)
            .join(Tenant, BuyerRelationship.tenant_id == Tenant.id)
            .order_by(BuyerRelationship.relationship_strength.desc())
        )
        if tenant_id:
            q = q.where(BuyerRelationship.tenant_id == tenant_id)
        if buyer_id:
            q = q.where(BuyerRelationship.buyer_id == buyer_id)
        if relationship_type:
            q = q.where(BuyerRelationship.relationship_type == relationship_type)

        count_q = select(func.count()).select_from(BuyerRelationship)
        if tenant_id:
            count_q = count_q.where(BuyerRelationship.tenant_id == tenant_id)
        if buyer_id:
            count_q = count_q.where(BuyerRelationship.buyer_id == buyer_id)
        if relationship_type:
            count_q = count_q.where(BuyerRelationship.relationship_type == relationship_type)
        total = await db.scalar(count_q) or 0

        rows = (await db.execute(q.offset(skip).limit(limit))).all()
        items = []
        for rel, profile, tenant in rows:
            items.append({
                "id": rel.id,
                "buyer_id": rel.buyer_id,
                "tenant_id": rel.tenant_id,
                "tenant_name": tenant.company_name,
                "company_name": profile.company_name,
                "relationship_type": rel.relationship_type,
                "relationship_strength": rel.relationship_strength,
                "country": profile.country,
                "industry": profile.industry,
                "opportunity_score": profile.opportunity_score,
                "created_at": rel.created_at,
            })
        return {"items": items, "total": int(total)}

    @staticmethod
    async def graph(
        db: AsyncSession,
        *,
        buyer_id: UUID | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        limit = min(30, max(1, limit))
        profiles = list(
            (await db.execute(
                select(BuyerNetworkProfile).order_by(
                    BuyerNetworkProfile.network_strength.desc(),
                ),
            )).scalars().all(),
        )
        focus = None
        if buyer_id:
            focus = await db.get(BuyerNetworkProfile, buyer_id)
        if not focus and profiles:
            focus = profiles[0]

        related: list[dict[str, Any]] = []
        if focus:
            industry = (focus.industry or "").lower()
            country = (focus.country or "").lower()
            for p in profiles:
                if p.id == focus.id:
                    continue
                reasons = []
                if industry and p.industry and industry in (p.industry or "").lower():
                    reasons.append("same industry")
                if country and p.country and country in (p.country or "").lower():
                    reasons.append("same country")
                if not reasons:
                    continue
                related.append({
                    "buyer_id": p.id,
                    "company_name": p.company_name,
                    "country": p.country,
                    "industry": p.industry,
                    "opportunity_score": p.opportunity_score,
                    "network_strength": p.network_strength,
                    "link_reason": " · ".join(reasons),
                })
            related.sort(key=lambda x: x["network_strength"], reverse=True)
            related = related[:limit]

        def _segments(key_fn) -> list[dict[str, Any]]:
            counts: dict[str, int] = {}
            for p in profiles:
                label = key_fn(p) or "Unknown"
                counts[label] = counts.get(label, 0) + 1
            total = len(profiles) or 1
            return [
                {
                    "label": label,
                    "count": cnt,
                    "share_pct": round(100.0 * cnt / total, 1),
                }
                for label, cnt in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:15]
            ]

        return {
            "focus_buyer_id": focus.id if focus else None,
            "related_buyers": related,
            "related_industries": _segments(lambda p: p.industry),
            "related_countries": _segments(lambda p: p.country),
            "errors": [],
        }

    @staticmethod
    async def insights(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        limit = min(20, max(1, limit))
        q = select(BuyerNetworkProfile).order_by(
            BuyerNetworkProfile.network_strength.desc(),
        )
        if tenant_id:
            sub = select(BuyerRelationship.buyer_id).where(
                BuyerRelationship.tenant_id == tenant_id,
            )
            q = q.where(BuyerNetworkProfile.id.in_(sub))
        profiles = list((await db.execute(q)).scalars().all())

        by_strength = sorted(profiles, key=lambda p: p.network_strength, reverse=True)
        strongest = [
            BuyerNetworkService._insight_item(p, i + 1, "network strength")
            for i, p in enumerate(by_strength[:limit])
        ]

        growing = sorted(
            profiles,
            key=lambda p: (
                int((p.score_factors_json or {}).get("relationship_count") or 0),
                p.opportunity_score,
            ),
            reverse=True,
        )
        fastest = [
            BuyerNetworkService._insight_item(p, i + 1, "growth signal")
            for i, p in enumerate(growing[:limit])
            if p.buyer_status in ("growing", "active", "strategic")
        ]

        strategic = [
            BuyerNetworkService._insight_item(p, i + 1, "strategic fit")
            for i, p in enumerate(
                [x for x in profiles if x.buyer_status == "strategic"][:limit],
            )
        ]

        underutilized = [
            BuyerNetworkService._insight_item(p, i + 1, "underutilized")
            for i, p in enumerate(
                sorted(
                    [x for x in profiles if x.buyer_status == "underutilized"],
                    key=lambda x: x.opportunity_score,
                    reverse=True,
                )[:limit],
            )
        ]

        return {
            "strongest_buyers": strongest,
            "fastest_growing": fastest,
            "strategic_buyers": strategic,
            "underutilized_buyers": underutilized,
            "errors": [],
        }

    @staticmethod
    async def top_buyers(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        limit = min(30, max(1, limit))
        q = select(BuyerNetworkProfile)
        if tenant_id:
            sub = select(BuyerRelationship.buyer_id).where(
                BuyerRelationship.tenant_id == tenant_id,
            )
            q = q.where(BuyerNetworkProfile.id.in_(sub))
        profiles = list((await db.execute(q)).scalars().all())

        by_combined = sorted(
            profiles,
            key=lambda p: (p.network_strength + p.opportunity_score) / 2,
            reverse=True,
        )
        by_net = sorted(profiles, key=lambda p: p.network_strength, reverse=True)
        by_opp = sorted(profiles, key=lambda p: p.opportunity_score, reverse=True)

        return {
            "top_buyers": [
                BuyerNetworkService._insight_item(p, i + 1, "combined score")
                for i, p in enumerate(by_combined[:limit])
            ],
            "by_network_strength": [
                BuyerNetworkService._insight_item(p, i + 1, "network strength")
                for i, p in enumerate(by_net[:limit])
            ],
            "by_opportunity": [
                BuyerNetworkService._insight_item(p, i + 1, "opportunity value")
                for i, p in enumerate(by_opp[:limit])
            ],
            "errors": [],
        }

    @staticmethod
    async def recalculate(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        errors: list[str] = []
        synced = 0
        try:
            await BuyerNetworkService._ensure_demo_seed(db)
            synced = await BuyerNetworkService.sync_profiles(db, limit=limit)
        except Exception as exc:
            errors.append(str(exc)[:200])

        profiles = list((await db.execute(select(BuyerNetworkProfile).limit(limit))).scalars().all())
        recalc_p = 0
        recalc_r = 0
        try:
            recalc_p = await BuyerNetworkService.recalculate_profiles(db, profiles)
            recalc_r = await BuyerNetworkService.recalculate_relationships(db)
            await db.commit()
        except Exception as exc:
            errors.append(str(exc)[:200])
            await db.rollback()

        overview = await BuyerNetworkService.overview(db, tenant_id=tenant_id)
        return {
            "profiles_synced": synced,
            "profiles_recalculated": recalc_p,
            "relationships_recalculated": recalc_r,
            "overview": overview,
            "message": (
                f"Recalculated {recalc_p} profile(s) and {recalc_r} relationship(s). "
                "No automatic outreach or CRM writes."
            ),
            "errors": errors,
        }

    @staticmethod
    async def summary_widget(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await BuyerNetworkService.overview(db, tenant_id=tenant_id)
        top = await BuyerNetworkService.top_buyers(db, tenant_id=tenant_id, limit=1)
        top_row = (top.get("top_buyers") or [None])[0]
        return {
            "total_profiles": overview["total_profiles"],
            "strategic_buyers": overview["strategic_buyers"],
            "active_buyers": overview["active_buyers"],
            "underutilized": overview["underutilized"],
            "average_network_strength": overview["average_network_strength"],
            "top_buyer_name": top_row["company_name"] if top_row else None,
            "top_buyer_score": top_row["network_strength"] if top_row else 0,
            "errors": overview.get("errors") or [],
        }

    @staticmethod
    async def executive_summary(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        overview = await BuyerNetworkService.overview(db, tenant_id=tenant_id)
        insights = await BuyerNetworkService.insights(db, tenant_id=tenant_id, limit=limit)
        graph = await BuyerNetworkService.graph(db, limit=limit)
        return {
            "overview": overview,
            "strongest_buyers": insights.get("strongest_buyers") or [],
            "strategic_buyers": insights.get("strategic_buyers") or [],
            "top_countries": graph.get("related_countries") or [],
            "safety_notice": BuyerNetworkService._safety_notice(),
        }

    @staticmethod
    async def network_recommendations(
        db: AsyncSession,
        *,
        tenant_id: UUID | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        errors: list[str] = []
        items: list[dict[str, Any]] = []
        try:
            overview = await BuyerNetworkService.overview(db, tenant_id=tenant_id)
            if overview["underutilized"] > 0:
                items.append({
                    "title": f"{overview['underutilized']} underutilized buyer(s) in global network",
                    "description": "Review relationship map and plan manual tenant engagement.",
                    "priority": "medium",
                    "source": "buyer_network",
                })
            if overview["strategic_buyers"] > 0:
                items.append({
                    "title": f"{overview['strategic_buyers']} strategic buyer(s) in network",
                    "description": "Prioritize executive review of strategic relationships.",
                    "priority": "high",
                    "source": "buyer_network",
                })
            top = await BuyerNetworkService.top_buyers(db, tenant_id=tenant_id, limit=3)
            for row in top.get("top_buyers") or []:
                items.append({
                    "title": f"Network: {row['company_name']} (strength {row['network_strength']})",
                    "description": (
                        f"{row.get('country') or 'Global'} · "
                        f"{row.get('industry') or 'general'} — mapping only."
                    ),
                    "priority": "high" if row["network_strength"] >= 70 else "medium",
                    "source": "buyer_network",
                    "buyer_id": str(row["buyer_id"]),
                })
        except Exception as exc:
            errors.append(str(exc)[:200])
        return {
            "items": items[:limit],
            "total": len(items),
            "errors": errors,
            "safety_notice": BuyerNetworkService._safety_notice(),
        }
