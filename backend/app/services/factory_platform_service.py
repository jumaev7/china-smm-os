"""Factory Partner Platform v1 — tenant-scoped business workspace for approved factory partners."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.models.client import Client
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.customer_portal_account import CustomerPortalAccount
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.product import Product, ProductImportJob
from app.models.proposal_document import ProposalDocument
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Factory Platform]"

_ACTIVE_LEAD_STATUSES = frozenset({
    "new", "contacted", "qualified", "proposal", "negotiation", "hot",
})

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})

_HIGH_RISK_LEVELS = frozenset({"at_risk", "critical", "stalled", "lost_probability_high"})


def _as_str_list(val: Any) -> list[str]:
    if not val:
        return []
    if isinstance(val, list):
        return [str(x) for x in val if x]
    return [str(val)]


class FactoryPlatformService:
    """Tenant-isolated factory workspace — no admin or cross-tenant access."""

    @staticmethod
    async def resolve_scope(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        tenant = await TenantService.validate_tenant_active(db, tenant_id)
        client_ids = await TenantService.get_client_ids_for_tenant(db, tenant_id)
        if not client_ids:
            raise HTTPException(
                status_code=400,
                detail="Tenant has no company clients. Create client and link tenant first.",
            )
        company_id = client_ids[0]
        client = await db.get(Client, company_id)
        if not client:
            raise HTTPException(status_code=404, detail="Primary company client not found")
        return {
            "tenant": tenant,
            "tenant_id": tenant_id,
            "company_id": company_id,
            "company_name": client.company_name,
            "tenant_status": tenant.status,
            "client_ids": client_ids,
            "client": client,
        }

    @staticmethod
    def _tenant_ref(scope: dict[str, Any]) -> dict[str, Any]:
        company_name = scope.get("company_name")
        if not company_name:
            client = scope.get("client")
            tenant = scope.get("tenant")
            company_name = (
                client.company_name if client else (tenant.company_name if tenant else "Unknown")
            )
        tenant_status = scope.get("tenant_status")
        if not tenant_status:
            tenant = scope.get("tenant")
            tenant_status = tenant.status if tenant else "unknown"
        return {
            "tenant_id": scope["tenant_id"],
            "company_id": scope["company_id"],
            "company_name": company_name,
            "tenant_status": tenant_status,
        }

    @staticmethod
    async def _get_or_seed_profile(db: AsyncSession, scope: dict[str, Any]) -> FactoryPlatformProfile:
        tenant_id = scope["tenant_id"]
        company_id = scope["company_id"]
        client = scope["client"]

        result = await db.execute(
            select(FactoryPlatformProfile).where(FactoryPlatformProfile.tenant_id == tenant_id),
        )
        profile = result.scalar_one_or_none()
        if profile:
            return profile

        app: FactoryPartnerApplication | None = None
        app_r = await db.execute(
            select(FactoryPartnerApplication)
            .where(
                (FactoryPartnerApplication.tenant_id == tenant_id)
                | (FactoryPartnerApplication.created_client_id == company_id),
            )
            .order_by(FactoryPartnerApplication.updated_at.desc())
            .limit(1),
        )
        app = app_r.scalar_one_or_none()

        markets = _as_str_list(app.target_markets if app else None)
        industries = [app.industry] if app and app.industry else []
        if app and app.product_categories:
            categories = _as_str_list(app.product_categories)
        else:
            categories = []

        profile = FactoryPlatformProfile(
            tenant_id=tenant_id,
            company_id=company_id,
            company_name=client.company_name,
            country=app.country if app else None,
            city=app.city if app else None,
            website=app.website if app else None,
            industry=app.industry if app else client.business_category,
            company_description=app.company_description if app else client.business_description,
            contact_name=app.contact_name if app else None,
            contact_email=app.contact_email if app else None,
            contact_phone=app.contact_phone if app else None,
            markets=markets,
            industries=industries,
            export_regions=markets,
            product_categories=categories,
        )
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        logger.info("%s seeded profile tenant=%s company=%s", MARKER, tenant_id, company_id)
        return profile

    @staticmethod
    def _serialize_profile(profile: FactoryPlatformProfile, client: Client) -> dict[str, Any]:
        return {
            "company_id": profile.company_id,
            "company_name": profile.company_name,
            "country": profile.country,
            "city": profile.city,
            "website": profile.website,
            "industry": profile.industry,
            "company_description": profile.company_description or client.business_description,
            "contact_name": profile.contact_name,
            "contact_email": profile.contact_email,
            "contact_phone": profile.contact_phone,
            "markets": _as_str_list(profile.markets),
            "industries": _as_str_list(profile.industries) or (
                [profile.industry] if profile.industry else []
            ),
            "export_regions": _as_str_list(profile.export_regions),
            "product_categories": _as_str_list(profile.product_categories),
            "business_category": client.business_category,
            "updated_at": profile.updated_at,
        }

    @staticmethod
    async def _count_leads(db: AsyncSession, client_ids: list[UUID]) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(CrmLead)
                .where(
                    CrmLead.client_id.in_(client_ids),
                    CrmLead.status.in_(tuple(_ACTIVE_LEAD_STATUSES)),
                ),
            ) or 0,
        )

    @staticmethod
    async def _count_deals(db: AsyncSession, client_ids: list[UUID]) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(CrmDeal)
                .where(
                    CrmDeal.client_id.in_(client_ids),
                    CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)),
                ),
            ) or 0,
        )

    @staticmethod
    async def _count_proposals(db: AsyncSession, client_ids: list[UUID]) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(ProposalDocument)
                .where(ProposalDocument.client_id.in_(client_ids)),
            ) or 0,
        )

    @staticmethod
    async def _recent_proposals(
        db: AsyncSession,
        client_ids: list[UUID],
        *,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        result = await db.execute(
            select(ProposalDocument, CrmLead.name)
            .outerjoin(CrmLead, ProposalDocument.lead_id == CrmLead.id)
            .where(ProposalDocument.client_id.in_(client_ids))
            .order_by(ProposalDocument.updated_at.desc())
            .limit(limit),
        )
        return [
            {
                "proposal_id": row[0].id,
                "title": row[0].title,
                "status": row[0].status,
                "buyer_name": row[1],
                "created_at": row[0].created_at,
            }
            for row in result.all()
        ]

    @staticmethod
    async def company(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryPlatformService._get_or_seed_profile(db, scope)
        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "profile": FactoryPlatformService._serialize_profile(profile, scope["client"]),
            "errors": [],
        }

    @staticmethod
    async def dashboard(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.revenue_attribution_service import RevenueAttributionService
        from app.services.subscription_service import SubscriptionService

        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryPlatformService._get_or_seed_profile(db, scope)
        client_ids = scope["client_ids"]
        company_id = scope["company_id"]
        errors: list[str] = []

        active_leads = await FactoryPlatformService._count_leads(db, client_ids)
        active_deals = await FactoryPlatformService._count_deals(db, client_ids)
        proposals_count = await FactoryPlatformService._count_proposals(db, client_ids)
        proposals = await FactoryPlatformService._recent_proposals(db, client_ids)

        buyer_overview = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.overview(
                db, client_id=company_id, tenant_id=tenant_id,
            ),
            default={"active_buyers": 0},
            errors=errors,
            db=db,
        )
        active_buyers = int(buyer_overview.get("active_buyers") or 0)

        revenue_data = await safe_section(
            "revenue_attribution",
            RevenueAttributionService.overview(db, client_id=company_id),
            default={},
            errors=errors,
            db=db,
        )
        revenue_summary = {
            "total_revenue": revenue_data.get("total_revenue", 0),
            "deals_won": revenue_data.get("deals_won", 0),
            "avg_deal_size": revenue_data.get("avg_deal_size", 0),
            "conversion_rate": revenue_data.get("conversion_rate", 0.0),
            "currency": revenue_data.get("currency", "UZS"),
        }

        billing_summary: dict[str, Any] = {}
        billing_data = await safe_section(
            "subscription_billing",
            SubscriptionService.summary(db, tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        if billing_data:
            billing_summary = billing_data

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "company_profile": FactoryPlatformService._serialize_profile(profile, scope["client"]),
            "active_buyers": active_buyers,
            "active_leads": active_leads,
            "active_deals": active_deals,
            "proposals_count": proposals_count,
            "proposals": proposals,
            "revenue_summary": revenue_summary,
            "billing_summary": billing_summary,
            "errors": errors,
        }

    @staticmethod
    async def products(
        db: AsyncSession,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        from app.services.product_catalog_service import ProductCatalogService

        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        company_id = scope["company_id"]
        errors: list[str] = []
        limit = clamp_limit(limit)

        categories = await safe_section(
            "product_catalog",
            ProductCatalogService.list_categories(db, client_id=company_id),
            default=[],
            errors=errors,
            db=db,
        )

        catalog = await safe_section(
            "product_catalog",
            ProductCatalogService.list_products(
                db, client_id=company_id, skip=skip, limit=limit,
            ),
            default={"items": [], "total": 0},
            errors=errors,
            db=db,
        )
        products = [
            {
                "product_id": row.get("id"),
                "name": row.get("name"),
                "sku": row.get("sku"),
                "category": row.get("category"),
                "description": row.get("description"),
                "moq": row.get("moq"),
                "unit_price": row.get("unit_price"),
                "currency": row.get("currency", "USD"),
                "active": row.get("active", True),
            }
            for row in catalog.get("items") or []
        ]

        jobs_r = await db.execute(
            select(ProductImportJob)
            .where(ProductImportJob.client_id == company_id)
            .order_by(ProductImportJob.created_at.desc())
            .limit(20),
        )
        catalog_records = [
            {
                "job_id": j.id,
                "source_type": j.source_type,
                "status": j.status,
                "created_at": j.created_at,
            }
            for j in jobs_r.scalars().all()
        ]

        profile = await FactoryPlatformService._get_or_seed_profile(db, scope)
        if not categories and profile.product_categories:
            categories = _as_str_list(profile.product_categories)

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "categories": categories,
            "products": products,
            "products_total": int(catalog.get("total") or len(products)),
            "catalog_records": catalog_records,
            "errors": errors,
        }

    @staticmethod
    async def reports(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.deal_risk_service import DealRiskService
        from app.services.revenue_attribution_service import RevenueAttributionService
        from app.services.revenue_forecast_service import RevenueForecastService

        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        company_id = scope["company_id"]
        errors: list[str] = []

        buyer_intel = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.overview(db, client_id=company_id, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )

        top_data = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.top_buyers(db, client_id=company_id, limit=8),
            default={"top_buyers": []},
            errors=errors,
            db=db,
        )
        top_buyers = [
            {
                "buyer_id": row.get("buyer_id"),
                "name": row.get("name") or "Unknown",
                "buyer_score": row.get("buyer_score", 0),
                "classification": row.get("classification") or "active_buyer",
                "risk_level": row.get("risk_level", "low"),
                "annual_potential": row.get("annual_potential", 0),
            }
            for row in top_data.get("top_buyers") or []
        ]

        deal_risk = await safe_section(
            "deal_risk",
            DealRiskService.overview(db, client_id=company_id, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )

        high_risk_data = await safe_section(
            "deal_risk",
            DealRiskService.list_deals(
                db, client_id=company_id, risk_level=None, skip=0, limit=50,
            ),
            default={"items": []},
            errors=errors,
            db=db,
        )
        high_risk_deals = [
            {
                "deal_id": row.get("deal_id"),
                "title": row.get("title") or "Deal",
                "risk_level": row.get("risk_level"),
                "deal_health_score": row.get("deal_health_score", 0),
                "close_probability": row.get("close_probability", 0.0),
                "revenue": row.get("revenue", 0),
            }
            for row in high_risk_data.get("items") or []
            if row.get("risk_level") in _HIGH_RISK_LEVELS
        ][:8]

        forecast_data = await safe_section(
            "revenue_forecast",
            RevenueForecastService.overview(db, client_id=company_id, tenant_id=tenant_id),
            default={"forecasts": [], "confidence": "medium"},
            errors=errors,
            db=db,
        )
        revenue_forecast = [
            {
                "period": f.get("period"),
                "best_case": f.get("best_case", 0),
                "expected_case": f.get("expected_case", 0),
                "worst_case": f.get("worst_case", 0),
                "currency": f.get("currency", "UZS"),
            }
            for f in forecast_data.get("forecasts") or []
        ]

        revenue_data = await safe_section(
            "revenue_attribution",
            RevenueAttributionService.overview(db, client_id=company_id),
            default={},
            errors=errors,
            db=db,
        )
        revenue_attribution = {
            "total_revenue": revenue_data.get("total_revenue", 0),
            "deals_won": revenue_data.get("deals_won", 0),
            "avg_deal_size": revenue_data.get("avg_deal_size", 0),
            "conversion_rate": revenue_data.get("conversion_rate", 0.0),
            "currency": revenue_data.get("currency", "UZS"),
        }

        from app.services.buyer_discovery_service import BuyerDiscoveryService
        from app.services.marketplace_service import MarketplaceService

        discovery_data = await safe_section(
            "buyer_discovery",
            BuyerDiscoveryService.executive_insights(
                db, client_id=company_id, tenant_id=tenant_id, limit=8,
            ),
            default={},
            errors=errors,
            db=db,
        )
        discovery_opportunities = [
            {
                "buyer_id": row.get("buyer_id"),
                "company_name": row.get("company_name") or "Unknown",
                "opportunity_score": row.get("opportunity_score", 0),
                "category": row.get("category") or "new",
                "country": row.get("country"),
                "industry": row.get("industry"),
            }
            for row in discovery_data.get("highest_potential_buyers") or []
        ]

        marketplace_data = await safe_section(
            "marketplace",
            MarketplaceService.top_opportunities(db, tenant_id=tenant_id, limit=8),
            default={"best_opportunities": []},
            errors=errors,
            db=db,
        )
        marketplace_opportunities = [
            {
                "opportunity_id": row.get("opportunity_id"),
                "title": row.get("title") or "Opportunity",
                "buyer_company": row.get("buyer_company"),
                "country": row.get("country"),
                "industry": row.get("industry"),
                "rank_score": row.get("rank_score", 0),
            }
            for row in marketplace_data.get("best_opportunities") or []
        ]

        from app.services.buyer_network_service import BuyerNetworkService

        network_data = await safe_section(
            "buyer_network",
            BuyerNetworkService.executive_summary(db, tenant_id=tenant_id, limit=8),
            default={},
            errors=errors,
            db=db,
        )
        network_buyers = [
            {
                "buyer_id": row.get("buyer_id"),
                "company_name": row.get("company_name") or "Unknown",
                "network_strength": row.get("network_strength", 0),
                "opportunity_score": row.get("opportunity_score", 0),
                "buyer_status": row.get("buyer_status") or "watchlist",
                "country": row.get("country"),
                "industry": row.get("industry"),
            }
            for row in network_data.get("strongest_buyers") or []
        ]

        from app.services.buyer_acquisition_service import BuyerAcquisitionService

        acquisition_data = await safe_section(
            "buyer_acquisition",
            BuyerAcquisitionService.executive_overview(
                db, client_id=company_id, tenant_id=tenant_id, limit=8,
            ),
            default={},
            errors=errors,
            db=db,
        )
        acquisition_buyers = acquisition_data.get("top_buyers") or []

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "buyer_intelligence": buyer_intel,
            "top_buyers": top_buyers,
            "buyer_discovery": discovery_data.get("overview") or {},
            "discovery_opportunities": discovery_opportunities,
            "marketplace": marketplace_data,
            "marketplace_opportunities": marketplace_opportunities,
            "buyer_network": network_data.get("overview") or {},
            "network_buyers": network_buyers,
            "buyer_acquisition": acquisition_data.get("overview") or {},
            "acquisition_buyers": acquisition_buyers,
            "deal_risk": deal_risk,
            "high_risk_deals": high_risk_deals,
            "revenue_forecast": revenue_forecast,
            "forecast_confidence": forecast_data.get("confidence", "medium"),
            "revenue_attribution": revenue_attribution,
            "errors": errors,
        }

    @staticmethod
    async def insights(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.deal_risk_service import DealRiskService

        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        company_id = scope["company_id"]
        errors: list[str] = []

        opp_data = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.list_buyers(
                db, client_id=company_id, skip=0, limit=30,
            ),
            default={"items": []},
            errors=errors,
            db=db,
        )
        hot_classes = frozenset({"hot_buyer", "strategic_buyer", "high_potential_buyer"})
        buyer_opportunities = [
            {
                "buyer_id": row.get("buyer_id"),
                "name": row.get("name") or "Unknown",
                "classification": row.get("classification") or "active_buyer",
                "buyer_score": row.get("buyer_score", 0),
                "reason": f"Score {row.get('buyer_score', 0)} — {row.get('classification', 'buyer')}",
            }
            for row in opp_data.get("items") or []
            if row.get("classification") in hot_classes or (row.get("buyer_score") or 0) >= 70
        ][:10]

        deal_data = await safe_section(
            "deal_risk",
            DealRiskService.list_deals(
                db, client_id=company_id, skip=0, limit=30,
            ),
            default={"items": []},
            errors=errors,
            db=db,
        )
        deal_risks = [
            {
                "deal_id": row.get("deal_id"),
                "title": row.get("title") or "Deal",
                "risk_level": row.get("risk_level"),
                "reason": f"Health score {row.get('deal_health_score', 0)} — review recommended",
            }
            for row in deal_data.get("items") or []
            if row.get("risk_level") in _HIGH_RISK_LEVELS
        ][:10]

        recommended_actions: list[dict[str, Any]] = []
        for opp in buyer_opportunities[:3]:
            recommended_actions.append({
                "action": f"Follow up with {opp['name']} — {opp['classification'].replace('_', ' ')}",
                "priority": "high",
                "source": "buyer_intelligence",
            })
        for risk in deal_risks[:3]:
            recommended_actions.append({
                "action": f"Review deal {risk['title']} — {risk['risk_level'].replace('_', ' ')}",
                "priority": "high" if risk["risk_level"] in ("critical", "lost_probability_high") else "medium",
                "source": "deal_risk",
            })
        if not recommended_actions:
            recommended_actions.append({
                "action": "Review active leads and update product catalog for export markets",
                "priority": "low",
                "source": "factory_platform",
            })

        from app.services.buyer_discovery_service import BuyerDiscoveryService
        from app.services.marketplace_service import MarketplaceService

        discovery_data = await safe_section(
            "buyer_discovery",
            BuyerDiscoveryService.top_opportunities(
                db, client_id=company_id, tenant_id=tenant_id, limit=8,
            ),
            default={"top_buyers": []},
            errors=errors,
            db=db,
        )
        export_discovery = [
            {
                "buyer_id": row.get("buyer_id"),
                "company_name": row.get("company_name") or "Unknown",
                "opportunity_score": row.get("opportunity_score", 0),
                "category": row.get("category") or "new",
                "country": row.get("country"),
                "industry": row.get("industry"),
            }
            for row in discovery_data.get("top_buyers") or []
        ]
        for opp in export_discovery[:3]:
            recommended_actions.append({
                "action": f"Research export buyer {opp['company_name']} — score {opp['opportunity_score']}",
                "priority": "medium",
                "source": "buyer_discovery",
            })

        marketplace_data = await safe_section(
            "marketplace",
            MarketplaceService.opportunity_recommendations(db, tenant_id=tenant_id, limit=5),
            default={"items": []},
            errors=errors,
            db=db,
        )
        exchange_opportunities = marketplace_data.get("items") or []
        for opp in exchange_opportunities[:3]:
            recommended_actions.append({
                "action": opp.get("title") or "Review marketplace opportunity",
                "priority": opp.get("priority") or "medium",
                "source": "marketplace",
            })

        from app.services.buyer_acquisition_service import BuyerAcquisitionService

        acquisition_data = await safe_section(
            "buyer_acquisition",
            BuyerAcquisitionService.acquisition_recommendations(
                db, client_id=company_id, tenant_id=tenant_id, limit=5,
            ),
            default={"items": []},
            errors=errors,
            db=db,
        )
        acquisition_recommendations = acquisition_data.get("items") or []
        for rec in acquisition_recommendations[:3]:
            recommended_actions.append({
                "action": rec.get("title") or "Review buyer acquisition workspace",
                "priority": rec.get("priority") or "medium",
                "source": "buyer_acquisition",
            })

        return {
            "tenant": FactoryPlatformService._tenant_ref(scope),
            "buyer_opportunities": buyer_opportunities,
            "export_discovery": export_discovery,
            "marketplace_opportunities": exchange_opportunities,
            "buyer_acquisition_recommendations": acquisition_recommendations,
            "deal_risks": deal_risks,
            "recommended_actions": recommended_actions,
            "errors": errors,
        }

    @staticmethod
    async def list_workspaces(
        db: AsyncSession,
        *,
        limit: int = 50,
        tenant_id: UUID | None = None,
    ) -> dict[str, Any]:
        """List tenants eligible for factory platform (has clients + optional portal)."""
        from app.models.tenant import Tenant

        query = select(Tenant).where(Tenant.status == "active").order_by(Tenant.created_at.desc())
        if tenant_id is not None:
            query = query.where(Tenant.id == tenant_id)
        result = await db.execute(query.limit(clamp_limit(limit)))
        items: list[dict[str, Any]] = []
        for tenant in result.scalars().all():
            client_ids = await TenantService.get_client_ids_for_tenant(db, tenant.id)
            if not client_ids:
                continue
            client = await db.get(Client, client_ids[0])
            portal_r = await db.execute(
                select(CustomerPortalAccount)
                .where(
                    CustomerPortalAccount.tenant_id == tenant.id,
                    CustomerPortalAccount.portal_status == "active",
                )
                .limit(1),
            )
            portal = portal_r.scalar_one_or_none()
            items.append({
                "tenant_id": tenant.id,
                "company_id": client_ids[0],
                "company_name": client.company_name if client else tenant.company_name,
                "tenant_status": tenant.status,
                "has_portal": portal is not None,
            })
        return {"items": items, "total": len(items)}
