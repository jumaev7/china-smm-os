"""Customer Portal v2 — tenant-scoped read-only partner workspace."""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from app.core.endpoint_guard import safe_section
from app.core.pagination import DEFAULT_LIMIT, clamp_limit
from app.services.factory_platform_service import FactoryPlatformService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Customer Portal v2]"

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})

_SOURCE_MAP = {
    "discovery": "buyer_acquisition",
    "marketplace": "marketplace",
    "network": "buyer_network",
}


def _safety_notice() -> str:
    return (
        "Read-only partner workspace — tenant-scoped only. "
        "No messaging, CRM writes, admin access, or autonomous actions."
    )


def _recommended_action(source: str, score: int) -> str:
    if score >= 75:
        return "Review opportunity details and prepare a manual outreach plan"
    if score >= 50:
        return "Qualify buyer fit and update CRM notes manually"
    if source == "marketplace":
        return "Browse marketplace listing and assess buyer requirements manually"
    if source == "buyer_network":
        return "Review network relationship strength and plan follow-up manually"
    return "Research buyer profile and add to your qualification pipeline manually"


def _proposal_value(row: Any) -> Decimal:
    payload = row.proposal_json if isinstance(getattr(row, "proposal_json", None), dict) else {}
    for key in ("total_value", "estimated_value", "deal_value"):
        val = payload.get(key)
        if val is not None:
            try:
                return Decimal(str(val))
            except Exception:
                pass
    return Decimal("0")


class CustomerPortalV2Service:
    """Tenant-isolated partner portal — aggregates existing modules read-only."""

    @staticmethod
    async def _scope(db: Any, tenant_id: UUID) -> dict[str, Any]:
        return await FactoryPlatformService.resolve_scope(db, tenant_id)

    @staticmethod
    async def _scope_or_empty(db: Any, tenant_id: UUID) -> tuple[dict[str, Any] | None, list[str]]:
        try:
            return await CustomerPortalV2Service._scope(db, tenant_id), []
        except HTTPException as exc:
            if exc.status_code == 400:
                tenant = await TenantService.get_tenant(db, tenant_id)
                return None, [str(exc.detail)]
            raise
        except Exception as exc:
            return None, [str(exc)[:200]]

    @staticmethod
    def _tenant_ref(scope: dict[str, Any]) -> dict[str, Any]:
        return FactoryPlatformService._tenant_ref(scope)

    @staticmethod
    def _tenant_ref_fallback(tenant_id: UUID, company_name: str) -> dict[str, Any]:
        return {
            "tenant_id": tenant_id,
            "company_id": tenant_id,
            "company_name": company_name,
            "tenant_status": "active",
        }

    @staticmethod
    async def summary_widget(db: Any, tenant_id: UUID) -> dict[str, Any]:
        dash = await CustomerPortalV2Service.dashboard(db, tenant_id)
        return {
            "active_buyers": dash["active_buyers"],
            "open_deals": dash["open_deals"],
            "active_opportunities": dash["active_opportunities"],
            "profile_completeness": dash["profile_completeness"],
            "subscription_status": dash["subscription_status"],
            "company_name": dash["tenant"]["company_name"],
            "errors": dash.get("errors") or [],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def health_overview(db: Any, tenant_id: UUID | None = None) -> dict[str, Any]:
        if tenant_id is None:
            workspaces = await FactoryPlatformService.list_workspaces(db, limit=1)
            items = workspaces.get("items") or []
            if not items:
                return {
                    "active_buyers": 0,
                    "open_deals": 0,
                    "active_opportunities": 0,
                    "profile_completeness": 0,
                    "subscription_status": None,
                    "company_name": None,
                    "readiness": "needs_attention",
                    "errors": ["No tenant workspace available"],
                    "safety_notice": _safety_notice(),
                }
            tenant_id = items[0]["tenant_id"]

        widget = await CustomerPortalV2Service.summary_widget(db, tenant_id)
        score = widget["profile_completeness"]
        buyers = widget["active_buyers"]
        opps = widget["active_opportunities"]
        if score >= 70 and buyers >= 3 and opps >= 2:
            readiness = "healthy"
        elif score >= 40 or buyers >= 1:
            readiness = "moderate"
        else:
            readiness = "needs_attention"

        return {
            **widget,
            "readiness": readiness,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def dashboard(db: Any, tenant_id: UUID) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.revenue_attribution_service import RevenueAttributionService
        from app.services.subscription_service import SubscriptionService
        from app.services.factory_profile_service import FactoryProfileService

        scope, scope_errors = await CustomerPortalV2Service._scope_or_empty(db, tenant_id)
        errors: list[str] = list(scope_errors)
        if not scope:
            tenant = await TenantService.get_tenant(db, tenant_id)
            billing = await safe_section(
                "subscription_billing",
                SubscriptionService.summary(db, tenant_id),
                default={},
                errors=errors,
                db=db,
            )
            return {
                "tenant": CustomerPortalV2Service._tenant_ref_fallback(
                    tenant_id, tenant.company_name,
                ),
                "subscription_status": billing.get("status"),
                "current_plan": (billing.get("plan") or {}).get("name"),
                "active_buyers": 0,
                "active_opportunities": 0,
                "open_deals": 0,
                "proposals": 0,
                "revenue_summary": {
                    "total_revenue": 0,
                    "deals_won": 0,
                    "avg_deal_size": 0,
                    "conversion_rate": 0.0,
                    "currency": "UZS",
                },
                "profile_completeness": 0,
                "errors": errors,
                "safety_notice": _safety_notice(),
            }

        company_id = scope["company_id"]

        buyer_overview = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.overview(db, client_id=company_id),
            default={"active_buyers": 0},
            errors=errors,
            db=db,
        )
        active_buyers = int(buyer_overview.get("active_buyers") or 0)

        from app.services.customer_portal_service import CustomerPortalService

        open_deals = await CustomerPortalService._count_opportunities(db, company_id)
        proposals = await CustomerPortalService._count_proposals(db, company_id)

        opps_data = await CustomerPortalV2Service.opportunities(db, tenant_id, limit=1)
        active_opportunities = int(opps_data.get("total") or 0)

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

        billing = await safe_section(
            "subscription_billing",
            SubscriptionService.summary(db, tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        plan_name = (billing.get("plan") or {}).get("name")
        subscription_status = billing.get("status")

        profile_score = 0
        score_data = await safe_section(
            "factory_profile",
            FactoryProfileService.profile_score(db, tenant_id),
            default={"profile_score": 0},
            errors=errors,
            db=db,
        )
        profile_score = int(score_data.get("profile_score") or 0)

        return {
            "tenant": CustomerPortalV2Service._tenant_ref(scope),
            "subscription_status": subscription_status,
            "current_plan": plan_name,
            "active_buyers": active_buyers,
            "active_opportunities": active_opportunities,
            "open_deals": open_deals,
            "proposals": proposals,
            "revenue_summary": revenue_summary,
            "profile_completeness": profile_score,
            "errors": errors,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _map_opportunity(row: dict[str, Any]) -> dict[str, Any]:
        raw_source = row.get("source") or "discovery"
        source = _SOURCE_MAP.get(raw_source, "buyer_acquisition")
        score = int(row.get("score") or row.get("opportunity_score") or 0)
        return {
            "opportunity_id": str(row.get("opportunity_id") or ""),
            "title": row.get("title") or "Opportunity",
            "source": source,
            "buyer_company": row.get("buyer_company"),
            "opportunity_score": score,
            "country": row.get("country"),
            "industry": row.get("industry"),
            "recommended_action": _recommended_action(source, score),
        }

    @staticmethod
    async def opportunities(
        db: Any,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        from app.services.buyer_acquisition_service import BuyerAcquisitionService

        scope, scope_errors = await CustomerPortalV2Service._scope_or_empty(db, tenant_id)
        errors: list[str] = list(scope_errors)
        if not scope:
            tenant = await TenantService.get_tenant(db, tenant_id)
            return {
                "tenant": CustomerPortalV2Service._tenant_ref_fallback(
                    tenant_id, tenant.company_name,
                ),
                "buyer_acquisition": [],
                "marketplace": [],
                "buyer_network": [],
                "total": 0,
                "errors": errors,
                "safety_notice": _safety_notice(),
            }

        company_id = scope["company_id"]
        limit = clamp_limit(limit)

        acq_data = await safe_section(
            "buyer_acquisition",
            BuyerAcquisitionService.list_opportunities(
                db, client_id=company_id, tenant_id=tenant_id, skip=0, limit=200,
            ),
            default={"items": []},
            errors=errors,
            db=db,
        )

        acquisition: list[dict[str, Any]] = []
        marketplace: list[dict[str, Any]] = []
        network: list[dict[str, Any]] = []

        for row in acq_data.get("items") or []:
            mapped = CustomerPortalV2Service._map_opportunity(row)
            src = mapped["source"]
            if src == "marketplace":
                marketplace.append(mapped)
            elif src == "buyer_network":
                network.append(mapped)
            else:
                acquisition.append(mapped)

        all_items = acquisition + marketplace + network
        total = len(all_items)
        page = all_items[skip : skip + limit]

        acq_page = [i for i in page if i["source"] == "buyer_acquisition"]
        mkt_page = [i for i in page if i["source"] == "marketplace"]
        net_page = [i for i in page if i["source"] == "buyer_network"]

        return {
            "tenant": CustomerPortalV2Service._tenant_ref(scope),
            "buyer_acquisition": acq_page,
            "marketplace": mkt_page,
            "buyer_network": net_page,
            "total": total,
            "errors": errors,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def deals(
        db: Any,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        from app.services.deal_risk_service import DealRiskService

        scope, scope_errors = await CustomerPortalV2Service._scope_or_empty(db, tenant_id)
        errors: list[str] = list(scope_errors)
        if not scope:
            tenant = await TenantService.get_tenant(db, tenant_id)
            return {
                "tenant": CustomerPortalV2Service._tenant_ref_fallback(
                    tenant_id, tenant.company_name,
                ),
                "items": [],
                "total": 0,
                "errors": errors,
                "safety_notice": _safety_notice(),
            }

        company_id = scope["company_id"]

        deal_data = await safe_section(
            "deal_risk",
            DealRiskService.list_deals(
                db, client_id=company_id, skip=skip, limit=limit,
            ),
            default={"items": [], "total": 0},
            errors=errors,
            db=db,
        )

        items = [
            {
                "deal_id": row.get("deal_id"),
                "deal_name": row.get("title") or "Deal",
                "buyer": row.get("buyer_name"),
                "stage": row.get("status") or "new",
                "risk_level": row.get("risk_level") or "healthy",
                "close_probability": float(row.get("close_probability") or 0.0),
                "estimated_value": row.get("revenue") or row.get("expected_value") or 0,
                "currency": row.get("currency", "UZS"),
            }
            for row in deal_data.get("items") or []
        ]

        return {
            "tenant": CustomerPortalV2Service._tenant_ref(scope),
            "items": items,
            "total": int(deal_data.get("total") or len(items)),
            "errors": errors,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def proposals(
        db: Any,
        tenant_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        from sqlalchemy import func, select

        from app.models.crm_lead import CrmLead
        from app.models.proposal_document import ProposalDocument

        scope, scope_errors = await CustomerPortalV2Service._scope_or_empty(db, tenant_id)
        if not scope:
            tenant = await TenantService.get_tenant(db, tenant_id)
            return {
                "tenant": CustomerPortalV2Service._tenant_ref_fallback(
                    tenant_id, tenant.company_name,
                ),
                "items": [],
                "total": 0,
                "errors": scope_errors,
                "safety_notice": _safety_notice(),
            }

        company_id = scope["company_id"]
        limit = clamp_limit(limit)

        count_q = select(func.count()).select_from(ProposalDocument).where(
            ProposalDocument.client_id == company_id,
        )
        total = int(await db.scalar(count_q) or 0)

        result = await db.execute(
            select(ProposalDocument, CrmLead.name)
            .outerjoin(CrmLead, ProposalDocument.lead_id == CrmLead.id)
            .where(ProposalDocument.client_id == company_id)
            .order_by(ProposalDocument.updated_at.desc())
            .offset(skip)
            .limit(limit),
        )

        items = [
            {
                "proposal_id": row[0].id,
                "proposal_title": row[0].title,
                "buyer": row[1],
                "status": row[0].status,
                "estimated_value": _proposal_value(row[0]),
                "last_updated": row[0].updated_at,
            }
            for row in result.all()
        ]

        return {
            "tenant": CustomerPortalV2Service._tenant_ref(scope),
            "items": items,
            "total": total,
            "errors": [],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def reports(db: Any, tenant_id: UUID) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.marketplace_service import MarketplaceService
        from app.services.revenue_attribution_service import RevenueAttributionService
        from app.services.revenue_forecast_service import RevenueForecastService

        scope, scope_errors = await CustomerPortalV2Service._scope_or_empty(db, tenant_id)
        errors: list[str] = list(scope_errors)
        if not scope:
            tenant = await TenantService.get_tenant(db, tenant_id)
            return {
                "tenant": CustomerPortalV2Service._tenant_ref_fallback(
                    tenant_id, tenant.company_name,
                ),
                "revenue_forecast": [],
                "forecast_confidence": "medium",
                "revenue_attribution": {
                    "total_revenue": 0,
                    "deals_won": 0,
                    "avg_deal_size": 0,
                    "conversion_rate": 0.0,
                    "currency": "UZS",
                },
                "buyer_performance": [],
                "marketplace_performance": {
                    "open_opportunities": 0,
                    "total_opportunities": 0,
                    "visibility_score": 0,
                },
                "errors": errors,
                "safety_notice": _safety_notice(),
            }

        company_id = scope["company_id"]

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

        forecast_data = await safe_section(
            "revenue_forecast",
            RevenueForecastService.overview(db, client_id=company_id),
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

        top_data = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.top_buyers(db, client_id=company_id, limit=8),
            default={"top_buyers": []},
            errors=errors,
            db=db,
        )
        buyer_performance = [
            {
                "buyer_id": row.get("buyer_id"),
                "name": row.get("name") or "Unknown",
                "buyer_score": row.get("buyer_score", 0),
                "classification": row.get("classification"),
                "annual_potential": row.get("annual_potential", 0),
            }
            for row in top_data.get("top_buyers") or []
        ]

        marketplace_data = await safe_section(
            "marketplace",
            MarketplaceService.overview(db, tenant_id=tenant_id),
            default={},
            errors=errors,
            db=db,
        )
        open_opps = int(marketplace_data.get("open_opportunities") or 0)
        total_opps = int(marketplace_data.get("total_opportunities") or 0)
        visibility = min(100, open_opps * 8 + total_opps * 2)

        return {
            "tenant": CustomerPortalV2Service._tenant_ref(scope),
            "revenue_forecast": revenue_forecast,
            "forecast_confidence": forecast_data.get("confidence", "medium"),
            "revenue_attribution": revenue_attribution,
            "buyer_performance": buyer_performance,
            "marketplace_performance": {
                "open_opportunities": open_opps,
                "total_opportunities": total_opps,
                "visibility_score": visibility,
            },
            "errors": errors,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def billing(db: Any, tenant_id: UUID) -> dict[str, Any]:
        from app.services.subscription_service import SubscriptionService

        scope, scope_errors = await CustomerPortalV2Service._scope_or_empty(db, tenant_id)
        errors: list[str] = list(scope_errors)
        tenant = await TenantService.get_tenant(db, tenant_id)
        tenant_ref = (
            CustomerPortalV2Service._tenant_ref(scope)
            if scope
            else CustomerPortalV2Service._tenant_ref_fallback(tenant_id, tenant.company_name)
        )

        billing_summary = await safe_section(
            "subscription_billing",
            SubscriptionService.summary(db, tenant_id),
            default={},
            errors=errors,
            db=db,
        )

        invoices_data = await safe_section(
            "subscription_invoices",
            SubscriptionService.list_invoices(db, tenant_id=tenant_id, limit=10),
            default={"items": []},
            errors=errors,
            db=db,
        )
        invoice_summary = [
            {
                "invoice_id": inv["id"],
                "invoice_number": inv.get("invoice_number"),
                "status": inv.get("status", "draft"),
                "amount": inv.get("amount", 0),
                "currency": inv.get("currency", "UZS"),
                "invoice_date": inv.get("invoice_date"),
            }
            for inv in (invoices_data.get("items") or [])
        ]

        plan = billing_summary.get("plan") or {}
        return {
            "tenant": tenant_ref,
            "current_plan": plan.get("name"),
            "subscription_status": billing_summary.get("status"),
            "usage_summary": billing_summary.get("usage_summary") or {},
            "invoice_summary": invoice_summary,
            "monthly_price": billing_summary.get("monthly_price", 0.0),
            "next_renewal": billing_summary.get("next_renewal"),
            "errors": errors,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def factory_snapshot(db: Any, tenant_id: UUID) -> dict[str, Any]:
        from app.services.factory_profile_service import FactoryProfileService

        scope, scope_errors = await CustomerPortalV2Service._scope_or_empty(db, tenant_id)
        errors: list[str] = list(scope_errors)
        tenant = await TenantService.get_tenant(db, tenant_id)
        if not scope:
            return {
                "tenant": CustomerPortalV2Service._tenant_ref_fallback(
                    tenant_id, tenant.company_name,
                ),
                "company_profile": {"company_name": tenant.company_name},
                "products_count": 0,
                "certificates_count": 0,
                "export_markets": [],
                "verification_status": "unverified",
                "profile_score": 0,
                "errors": errors,
                "safety_notice": _safety_notice(),
            }

        profile_data = await safe_section(
            "factory_profile",
            FactoryProfileService.profile(db, tenant_id),
            default={"profile": {}},
            errors=errors,
            db=db,
        )
        catalog_data = await safe_section(
            "factory_catalog",
            FactoryProfileService.catalog(db, tenant_id),
            default={"total": 0},
            errors=errors,
            db=db,
        )
        cert_data = await safe_section(
            "factory_certificates",
            FactoryProfileService.certificates(db, tenant_id),
            default={"total": 0},
            errors=errors,
            db=db,
        )
        markets_data = await safe_section(
            "factory_export_markets",
            FactoryProfileService.export_markets(db, tenant_id),
            default={"items": []},
            errors=errors,
            db=db,
        )
        score_data = await safe_section(
            "factory_profile_score",
            FactoryProfileService.profile_score(db, tenant_id),
            default={"profile_score": 0},
            errors=errors,
            db=db,
        )
        ver_data = await safe_section(
            "factory_verification",
            FactoryProfileService.verification_status(db, tenant_id),
            default={"verification_status": "unverified"},
            errors=errors,
            db=db,
        )

        export_markets = [
            {
                "country": m.get("country") or "Unknown",
                "market_score": int(m.get("market_score") or 0),
                "active_buyers": int(m.get("active_buyers") or 0),
                "opportunities": int(m.get("opportunities") or 0),
            }
            for m in (markets_data.get("items") or [])
        ]

        return {
            "tenant": CustomerPortalV2Service._tenant_ref(scope),
            "company_profile": profile_data.get("profile") or {},
            "products_count": int(catalog_data.get("total") or 0),
            "certificates_count": int(cert_data.get("total") or 0),
            "export_markets": export_markets,
            "verification_status": ver_data.get("verification_status", "unverified"),
            "profile_score": int(score_data.get("profile_score") or 0),
            "errors": errors,
            "safety_notice": _safety_notice(),
        }
