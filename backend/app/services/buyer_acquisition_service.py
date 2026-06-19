"""Buyer Acquisition Platform Consolidation v1 — unified read-only aggregation layer."""
from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.services.buyer_discovery_service import BuyerDiscoveryService
from app.services.buyer_intelligence_service import BuyerIntelligenceService
from app.services.buyer_network_service import BuyerNetworkService
from app.services.marketplace_service import MarketplaceService

logger = logging.getLogger(__name__)

MARKER = "[Buyer Acquisition]"

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

_RELATIONSHIP_TO_PIPELINE = {
    "discovered": "discovered",
    "contacted": "contacted",
    "active": "opportunity",
    "customer": "customer",
    "strategic": "opportunity",
}

_STAGE_ORDER = {stage: idx for idx, stage in enumerate(PIPELINE_STAGES)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _normalize_key(company_name: str, country: str | None) -> str:
    name = re.sub(r"\s+", " ", (company_name or "").strip().lower())
    c = (country or "").strip().lower()
    return f"{name}|{c}" if c else name


def _empty_buyer(key: str, company_name: str) -> dict[str, Any]:
    return {
        "unified_key": key,
        "company_name": company_name,
        "country": None,
        "city": None,
        "industry": None,
        "website": None,
        "opportunity_score": 0,
        "buyer_score": 0,
        "network_strength": 0,
        "relationship_status": "unknown",
        "pipeline_stage": "discovered",
        "classification": None,
        "sources": [],
        "discovery_id": None,
        "network_id": None,
        "intelligence_id": None,
        "client_id": None,
        "discovered_at": None,
    }


def _merge_stage(current: str, candidate: str) -> str:
    if _STAGE_ORDER.get(candidate, 0) > _STAGE_ORDER.get(current, 0):
        return candidate
    return current


def _segment_share(counts: Counter[str], limit: int = 8) -> list[dict[str, Any]]:
    total = sum(counts.values()) or 1
    return [
        {
            "label": label,
            "count": count,
            "share_pct": round(count / total * 100, 1),
        }
        for label, count in counts.most_common(limit)
    ]


class BuyerAcquisitionService:
    """Unified buyer acquisition workspace — aggregates discovery, network, marketplace, intelligence."""

    @staticmethod
    def _safety_notice() -> str:
        return (
            "Read-only aggregation — no automatic outreach, messaging, or CRM writes."
        )

    @staticmethod
    async def integration_checks(db: Any) -> list[dict[str, Any]]:
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
            "buyer_network",
            BuyerNetworkService.overview(db),
            "Buyer Network overview reachable",
        )
        await _probe(
            "marketplace",
            MarketplaceService.overview(db),
            "Marketplace overview reachable",
        )
        await _probe(
            "buyer_intelligence",
            BuyerIntelligenceService.overview(db),
            "Buyer Intelligence overview reachable",
        )
        return checks

    @staticmethod
    async def _load_intelligence_buyers(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 500,
    ) -> dict[str, Any]:
        resolved_id, client_ids = await BuyerIntelligenceService._resolve_scope(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        leads = await BuyerIntelligenceService._load_buyers(
            db, client_id=resolved_id, client_ids=client_ids,
        )
        items: list[dict[str, Any]] = []
        for lead in leads[:limit]:
            try:
                ev = await BuyerIntelligenceService.evaluate_buyer(db, lead)
                sig = ev["signals"]
                items.append({
                    "buyer_id": lead.id,
                    "name": lead.name,
                    "company": lead.company,
                    "country": sig.get("country"),
                    "industry": sig.get("industry"),
                    "buyer_score": ev["buyer_score"],
                    "classification": ev["classification"],
                    "client_id": lead.client_id,
                })
            except Exception as exc:
                logger.info("%s intel skip: lead=%s err=%s", MARKER, lead.id, exc)
        return {"items": items, "total": len(items)}

    @staticmethod
    async def _build_unified_buyers(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 500,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        errors: list[str] = []
        merged: dict[str, dict[str, Any]] = {}

        def _get_or_create(key: str, company_name: str) -> dict[str, Any]:
            if key not in merged:
                merged[key] = _empty_buyer(key, company_name)
            return merged[key]

        discovery_data = await safe_section(
            "buyer_discovery_buyers",
            BuyerDiscoveryService.list_buyers(
                db, client_id=client_id, tenant_id=tenant_id, limit=limit,
            ),
            default={"items": [], "total": 0},
            errors=errors,
            db=db,
        )
        for row in discovery_data.get("items") or []:
            key = _normalize_key(row.get("company_name") or "Unknown", row.get("country"))
            item = _get_or_create(key, row.get("company_name") or "Unknown")
            item["country"] = item["country"] or row.get("country")
            item["city"] = item["city"] or row.get("city")
            item["industry"] = item["industry"] or row.get("industry")
            item["website"] = item["website"] or row.get("website")
            item["opportunity_score"] = max(item["opportunity_score"], _clamp(row.get("opportunity_score", 0)))
            item["pipeline_stage"] = _merge_stage(item["pipeline_stage"], row.get("pipeline_stage") or "discovered")
            item["classification"] = item["classification"] or row.get("category")
            item["discovery_id"] = item["discovery_id"] or row.get("id")
            item["client_id"] = item["client_id"] or row.get("client_id")
            item["discovered_at"] = item["discovered_at"] or row.get("discovered_at")
            if "discovery" not in item["sources"]:
                item["sources"].append("discovery")

        network_data = await safe_section(
            "buyer_network_profiles",
            BuyerNetworkService.list_profiles(
                db, tenant_id=tenant_id, limit=limit,
            ),
            default={"items": [], "total": 0},
            errors=errors,
            db=db,
        )
        for row in network_data.get("items") or []:
            key = _normalize_key(row.get("company_name") or "Unknown", row.get("country"))
            item = _get_or_create(key, row.get("company_name") or "Unknown")
            item["country"] = item["country"] or row.get("country")
            item["city"] = item["city"] or row.get("city")
            item["industry"] = item["industry"] or row.get("industry")
            item["website"] = item["website"] or row.get("website")
            item["opportunity_score"] = max(item["opportunity_score"], _clamp(row.get("opportunity_score", 0)))
            item["network_strength"] = max(item["network_strength"], _clamp(row.get("network_strength", 0)))
            rel = row.get("relationship_type") or row.get("buyer_status") or "discovered"
            if rel in ("discovered", "contacted", "active", "customer", "strategic"):
                item["relationship_status"] = rel
            item["pipeline_stage"] = _merge_stage(
                item["pipeline_stage"],
                _RELATIONSHIP_TO_PIPELINE.get(str(rel), "discovered"),
            )
            item["classification"] = item["classification"] or row.get("classification")
            item["network_id"] = item["network_id"] or row.get("id")
            if "network" not in item["sources"]:
                item["sources"].append("network")

        intel_data = await safe_section(
            "buyer_intelligence_buyers",
            BuyerAcquisitionService._load_intelligence_buyers(
                db, client_id=client_id, tenant_id=tenant_id, limit=limit,
            ),
            default={"items": [], "total": 0},
            errors=errors,
            db=db,
        )
        for row in intel_data.get("items") or []:
            company = row.get("company") or row.get("name") or "Unknown"
            key = _normalize_key(company, row.get("country"))
            item = _get_or_create(key, company)
            item["country"] = item["country"] or row.get("country")
            item["industry"] = item["industry"] or row.get("industry")
            item["buyer_score"] = max(item["buyer_score"], _clamp(row.get("buyer_score", 0)))
            item["opportunity_score"] = max(
                item["opportunity_score"],
                _clamp(row.get("buyer_score", 0)),
            )
            item["classification"] = item["classification"] or row.get("classification")
            item["intelligence_id"] = item["intelligence_id"] or row.get("buyer_id")
            item["client_id"] = item["client_id"] or row.get("client_id")
            cls = str(row.get("classification") or "")
            if "strategic" in cls:
                item["relationship_status"] = "strategic"
                item["pipeline_stage"] = _merge_stage(item["pipeline_stage"], "opportunity")
            elif "hot" in cls or "high_potential" in cls:
                item["pipeline_stage"] = _merge_stage(item["pipeline_stage"], "qualified")
            if "intelligence" not in item["sources"]:
                item["sources"].append("intelligence")

        marketplace_data = await safe_section(
            "marketplace_opportunities",
            MarketplaceService.list_opportunities(db, tenant_id=tenant_id, limit=limit),
            default={"items": [], "total": 0},
            errors=errors,
            db=db,
        )
        for row in marketplace_data.get("items") or []:
            company = row.get("buyer_company") or row.get("title") or "Unknown"
            key = _normalize_key(company, row.get("country"))
            item = _get_or_create(key, company)
            item["country"] = item["country"] or row.get("country")
            item["industry"] = item["industry"] or row.get("industry")
            rank = _clamp(int(row.get("rank_score") or 0))
            item["opportunity_score"] = max(item["opportunity_score"], rank)
            item["pipeline_stage"] = _merge_stage(item["pipeline_stage"], "opportunity")
            if "marketplace" not in item["sources"]:
                item["sources"].append("marketplace")

        buyers = list(merged.values())
        buyers.sort(
            key=lambda b: (b["opportunity_score"], b["buyer_score"], b["network_strength"]),
            reverse=True,
        )
        return buyers, errors

    @staticmethod
    async def overview(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        errors: list[str] = []
        buyers, merge_errors = await BuyerAcquisitionService._build_unified_buyers(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        errors.extend(merge_errors)

        discovery_overview = await safe_section(
            "buyer_discovery_overview",
            BuyerDiscoveryService.overview(db, client_id=client_id, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        network_overview = await safe_section(
            "buyer_network_overview",
            BuyerNetworkService.overview(db, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        intel_overview = await safe_section(
            "buyer_intelligence_overview",
            BuyerIntelligenceService.overview(db, client_id=client_id, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        marketplace_overview = await safe_section(
            "marketplace_overview",
            MarketplaceService.overview(db, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )

        strategic = sum(
            1 for b in buyers
            if b.get("relationship_status") == "strategic"
            or (b.get("classification") or "").find("strategic") >= 0
        )
        high_potential = sum(
            1 for b in buyers
            if b.get("opportunity_score", 0) >= 70
            or (b.get("classification") or "").find("high_potential") >= 0
        )
        opp_scores = [b["opportunity_score"] for b in buyers if b["opportunity_score"]]
        buyer_scores = [b["buyer_score"] for b in buyers if b["buyer_score"]]
        net_scores = [b["network_strength"] for b in buyers if b["network_strength"]]

        network_opps = sum(
            1 for b in buyers
            if "network" in b.get("sources", [])
            and b.get("opportunity_score", 0) >= 50
        )

        integration = await safe_section(
            "buyer_acquisition_integrations",
            BuyerAcquisitionService.integration_checks(db),
            default=[],
            errors=errors,
            db=db,
        )

        return {
            "total_buyers": len(buyers),
            "strategic_buyers": strategic,
            "high_potential_buyers": high_potential,
            "marketplace_opportunities": int(marketplace_overview.get("open_opportunities") or 0),
            "network_opportunities": network_opps,
            "discovery_buyers": int(discovery_overview.get("total_buyers") or 0),
            "network_profiles": int(network_overview.get("total_profiles") or 0),
            "intelligence_buyers": int(intel_overview.get("total_buyers") or 0),
            "average_opportunity_score": int(sum(opp_scores) / len(opp_scores)) if opp_scores else 0,
            "average_buyer_score": int(sum(buyer_scores) / len(buyer_scores)) if buyer_scores else 0,
            "average_network_strength": int(sum(net_scores) / len(net_scores)) if net_scores else 0,
            "integration_checks": integration,
            "errors": errors,
            "safety_notice": BuyerAcquisitionService._safety_notice(),
        }

    @staticmethod
    async def list_buyers(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        min_score: int | None = None,
        pipeline_stage: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        buyers, errors = await BuyerAcquisitionService._build_unified_buyers(
            db, client_id=client_id, tenant_id=tenant_id, limit=500,
        )
        if min_score is not None:
            buyers = [b for b in buyers if b["opportunity_score"] >= min_score]
        if pipeline_stage and pipeline_stage in PIPELINE_STAGES:
            buyers = [b for b in buyers if b["pipeline_stage"] == pipeline_stage]
        total = len(buyers)
        page = buyers[skip : skip + limit]
        return {"items": page, "total": total, "errors": errors}

    @staticmethod
    async def list_opportunities(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        source: str | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        limit = clamp_limit(limit)
        errors: list[str] = []
        items: list[dict[str, Any]] = []

        if source in (None, "marketplace"):
            marketplace_data = await safe_section(
                "marketplace_list",
                MarketplaceService.list_opportunities(db, tenant_id=tenant_id, limit=100),
                default={"items": []},
                errors=errors,
                db=db,
            )
            for row in marketplace_data.get("items") or []:
                items.append({
                    "opportunity_id": str(row.get("id") or row.get("opportunity_id") or uuid4()),
                    "title": row.get("title") or "Marketplace opportunity",
                    "source": "marketplace",
                    "buyer_company": row.get("buyer_company"),
                    "country": row.get("country"),
                    "industry": row.get("industry"),
                    "score": _clamp(int(row.get("rank_score") or 0)),
                    "opportunity_type": row.get("opportunity_type"),
                    "estimated_value": row.get("estimated_value"),
                    "status": row.get("status"),
                    "description": row.get("description"),
                })

        if source in (None, "discovery"):
            discovery_data = await safe_section(
                "discovery_opportunities",
                BuyerDiscoveryService.top_opportunities(
                    db, client_id=client_id, tenant_id=tenant_id, limit=50,
                ),
                default={},
                errors=errors,
                db=db,
            )
            seen: set[str] = set()
            for bucket in ("top_buyers", "highest_opportunity", "strategic_buyers", "fastest_growing"):
                for row in discovery_data.get(bucket) or []:
                    key = _normalize_key(row.get("company_name") or "", row.get("country"))
                    if key in seen:
                        continue
                    seen.add(key)
                    items.append({
                        "opportunity_id": str(row.get("buyer_id") or uuid4()),
                        "title": f"Discovery: {row.get('company_name') or 'Buyer'}",
                        "source": "discovery",
                        "buyer_company": row.get("company_name"),
                        "country": row.get("country"),
                        "industry": row.get("industry"),
                        "score": _clamp(int(row.get("opportunity_score") or 0)),
                        "opportunity_type": row.get("category"),
                        "estimated_value": None,
                        "status": row.get("pipeline_stage"),
                        "description": f"Category: {row.get('category') or 'new'}",
                    })

        if source in (None, "network"):
            network_data = await safe_section(
                "network_opportunities",
                BuyerNetworkService.insights(db, tenant_id=tenant_id, limit=30),
                default={},
                errors=errors,
                db=db,
            )
            seen_net: set[str] = set()
            for bucket in ("strategic_buyers", "underutilized_buyers", "strongest_buyers"):
                for row in network_data.get(bucket) or []:
                    key = _normalize_key(row.get("company_name") or "", row.get("country"))
                    if key in seen_net:
                        continue
                    seen_net.add(key)
                    items.append({
                        "opportunity_id": str(row.get("buyer_id") or uuid4()),
                        "title": f"Network: {row.get('company_name') or 'Buyer'}",
                        "source": "network",
                        "buyer_company": row.get("company_name"),
                        "country": row.get("country"),
                        "industry": row.get("industry"),
                        "score": _clamp(int(row.get("opportunity_score") or row.get("network_strength") or 0)),
                        "opportunity_type": row.get("buyer_status"),
                        "estimated_value": None,
                        "status": row.get("buyer_status"),
                        "description": row.get("metric_label") or "Network relationship opportunity",
                    })

        if source and source not in ("marketplace", "discovery", "network"):
            items = []

        items.sort(key=lambda x: x["score"], reverse=True)
        marketplace_count = sum(1 for i in items if i["source"] == "marketplace")
        discovery_count = sum(1 for i in items if i["source"] == "discovery")
        network_count = sum(1 for i in items if i["source"] == "network")
        total = len(items)
        page = items[skip : skip + limit]
        return {
            "items": page,
            "total": total,
            "marketplace_count": marketplace_count,
            "discovery_count": discovery_count,
            "network_count": network_count,
            "errors": errors,
        }

    @staticmethod
    async def pipeline(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        buyers, errors = await BuyerAcquisitionService._build_unified_buyers(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        counts = {s: 0 for s in PIPELINE_STAGES}
        for b in buyers:
            stage = b.get("pipeline_stage") or "discovered"
            if stage in counts:
                counts[stage] += 1
        stages = [
            {"stage": stage, "count": counts[stage], "label": _PIPELINE_LABELS[stage]}
            for stage in PIPELINE_STAGES
        ]
        return {"stages": stages, "total": len(buyers), "errors": errors}

    @staticmethod
    async def insights(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        limit = min(20, max(1, limit))
        errors: list[str] = []
        buyers, merge_errors = await BuyerAcquisitionService._build_unified_buyers(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        errors.extend(merge_errors)

        def _insight(row: dict[str, Any], rank: int, source: str) -> dict[str, Any]:
            return {
                "rank": rank,
                "company_name": row["company_name"],
                "country": row.get("country"),
                "industry": row.get("industry"),
                "score": max(row["opportunity_score"], row["buyer_score"], row["network_strength"]),
                "buyer_score": row["buyer_score"],
                "network_strength": row["network_strength"],
                "opportunity_score": row["opportunity_score"],
                "relationship_status": row.get("relationship_status"),
                "source": source,
                "buyer_id": str(row.get("intelligence_id") or row.get("discovery_id") or row.get("network_id") or ""),
            }

        by_combined = sorted(
            buyers,
            key=lambda b: (b["opportunity_score"] + b["buyer_score"] + b["network_strength"]),
            reverse=True,
        )
        by_net = sorted(buyers, key=lambda b: b["network_strength"], reverse=True)
        by_opp = sorted(buyers, key=lambda b: b["opportunity_score"], reverse=True)

        country_counts: Counter[str] = Counter()
        industry_counts: Counter[str] = Counter()
        for b in buyers:
            if b.get("country"):
                country_counts[b["country"]] += 1
            if b.get("industry"):
                industry_counts[b["industry"]] += 1

        return {
            "top_buyers": [_insight(b, i + 1, "combined") for i, b in enumerate(by_combined[:limit])],
            "strongest_relationships": [
                _insight(b, i + 1, "network") for i, b in enumerate(by_net[:limit]) if b["network_strength"] > 0
            ],
            "highest_opportunity_buyers": [
                _insight(b, i + 1, "opportunity") for i, b in enumerate(by_opp[:limit])
            ],
            "best_countries": _segment_share(country_counts, limit),
            "best_industries": _segment_share(industry_counts, limit),
            "errors": errors,
            "safety_notice": BuyerAcquisitionService._safety_notice(),
        }

    @staticmethod
    async def summary_widget(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        overview = await BuyerAcquisitionService.overview(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        insights = await BuyerAcquisitionService.insights(
            db, client_id=client_id, tenant_id=tenant_id, limit=1,
        )
        top = (insights.get("top_buyers") or [None])[0]
        return {
            "total_buyers": overview["total_buyers"],
            "strategic_buyers": overview["strategic_buyers"],
            "high_potential_buyers": overview["high_potential_buyers"],
            "marketplace_opportunities": overview["marketplace_opportunities"],
            "network_opportunities": overview["network_opportunities"],
            "top_buyer_name": top["company_name"] if top else None,
            "top_buyer_score": top["score"] if top else 0,
            "errors": overview.get("errors") or [],
        }

    @staticmethod
    async def executive_overview(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 5,
    ) -> dict[str, Any]:
        overview = await BuyerAcquisitionService.overview(
            db, client_id=client_id, tenant_id=tenant_id,
        )
        insights = await BuyerAcquisitionService.insights(
            db, client_id=client_id, tenant_id=tenant_id, limit=limit,
        )
        return {
            "overview": overview,
            "top_buyers": insights.get("top_buyers") or [],
            "strongest_relationships": insights.get("strongest_relationships") or [],
            "highest_opportunity_buyers": insights.get("highest_opportunity_buyers") or [],
            "best_countries": insights.get("best_countries") or [],
            "best_industries": insights.get("best_industries") or [],
            "safety_notice": BuyerAcquisitionService._safety_notice(),
        }

    @staticmethod
    async def acquisition_recommendations(
        db: Any,
        *,
        client_id: UUID | None = None,
        tenant_id: UUID | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        errors: list[str] = []
        items: list[dict[str, Any]] = []
        try:
            overview = await BuyerAcquisitionService.overview(
                db, client_id=client_id, tenant_id=tenant_id,
            )
            if overview["high_potential_buyers"] > 0:
                items.append({
                    "title": f"{overview['high_potential_buyers']} high-potential unified buyer(s)",
                    "description": "Review unified buyer profiles across discovery, network, and intelligence.",
                    "priority": "high",
                    "source": "buyer_acquisition",
                })
            if overview["marketplace_opportunities"] > 0:
                items.append({
                    "title": f"{overview['marketplace_opportunities']} open marketplace opportunit"
                    f"{'y' if overview['marketplace_opportunities'] == 1 else 'ies'}",
                    "description": "Evaluate marketplace exchange opportunities manually.",
                    "priority": "medium",
                    "source": "buyer_acquisition",
                })
            if overview["network_opportunities"] > 0:
                items.append({
                    "title": f"{overview['network_opportunities']} network relationship opportunit"
                    f"{'y' if overview['network_opportunities'] == 1 else 'ies'}",
                    "description": "Strengthen underutilized network relationships.",
                    "priority": "medium",
                    "source": "buyer_acquisition",
                })
            insights = await BuyerAcquisitionService.insights(
                db, client_id=client_id, tenant_id=tenant_id, limit=3,
            )
            for row in insights.get("highest_opportunity_buyers") or []:
                items.append({
                    "title": f"Acquisition: {row['company_name']} (score {row['opportunity_score']})",
                    "description": "Unified high-opportunity buyer — manual outreach only.",
                    "priority": "high",
                    "source": "buyer_acquisition",
                })
        except Exception as exc:
            errors.append(str(exc)[:200])
            logger.info("%s recommendations error: %s", MARKER, exc)

        return {
            "items": items[:limit],
            "errors": errors,
            "safety_notice": BuyerAcquisitionService._safety_notice(),
        }
