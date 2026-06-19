"""Customer Portal v1 — company-scoped read-only portal for approved factory partners."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
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
from app.models.customer_portal_account import PORTAL_STATUSES, CustomerPortalAccount
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.proposal_document import ProposalDocument
logger = logging.getLogger(__name__)

MARKER = "[Customer Portal]"

_ACTIVE_LEAD_STATUSES = frozenset({
    "new", "contacted", "qualified", "proposal", "negotiation", "hot",
})

_ACTIVE_DEAL_STATUSES = frozenset({
    "new", "proposal", "contract", "invoice", "waiting_payment",
})


def _serialize_account(account: CustomerPortalAccount) -> dict[str, Any]:
    return {
        "id": account.id,
        "company_id": account.company_id,
        "company_name": account.company_name,
        "portal_status": account.portal_status,
        "owner_user": account.owner_user,
        "factory_partner_application_id": account.factory_partner_application_id,
        "created_at": account.created_at,
    }


class CustomerPortalService:
    """Read-only portal scoped to a single factory company — no admin or system-wide access."""

    @staticmethod
    async def _load_account(db: AsyncSession, portal_account_id: UUID) -> CustomerPortalAccount:
        result = await db.execute(
            select(CustomerPortalAccount).where(CustomerPortalAccount.id == portal_account_id),
        )
        account = result.scalar_one_or_none()
        if not account:
            raise HTTPException(status_code=404, detail="Portal account not found")
        return account

    @staticmethod
    async def resolve_active_account(
        db: AsyncSession,
        portal_account_id: UUID,
    ) -> tuple[CustomerPortalAccount, UUID]:
        """Enforce portal scope — only active accounts may access portal data."""
        account = await CustomerPortalService._load_account(db, portal_account_id)
        if account.portal_status != "active":
            raise HTTPException(
                status_code=403,
                detail=f"Portal account is {account.portal_status}. Access denied.",
            )
        return account, account.company_id

    @staticmethod
    async def list_accounts(
        db: AsyncSession,
        *,
        portal_status: str | None = None,
        tenant_id: UUID | None = None,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        query = select(CustomerPortalAccount).order_by(CustomerPortalAccount.created_at.desc())
        count_q = select(func.count()).select_from(CustomerPortalAccount)

        if tenant_id is not None:
            query = query.where(CustomerPortalAccount.tenant_id == tenant_id)
            count_q = count_q.where(CustomerPortalAccount.tenant_id == tenant_id)

        if portal_status:
            if portal_status not in PORTAL_STATUSES:
                raise HTTPException(status_code=400, detail="Invalid portal status")
            query = query.where(CustomerPortalAccount.portal_status == portal_status)
            count_q = count_q.where(CustomerPortalAccount.portal_status == portal_status)

        total = int(await db.scalar(count_q) or 0)
        result = await db.execute(query.offset(skip).limit(clamp_limit(limit)))
        items = [_serialize_account(a) for a in result.scalars().all()]
        return {"items": items, "total": total}

    @staticmethod
    async def create_portal_account_from_application(
        db: AsyncSession,
        application_id: UUID,
    ) -> dict[str, Any]:
        """Admin-only — create portal account from approved factory application."""
        result = await db.execute(
            select(FactoryPartnerApplication).where(FactoryPartnerApplication.id == application_id),
        )
        app = result.scalar_one_or_none()
        if not app:
            raise HTTPException(status_code=404, detail="Application not found")
        if app.status != "approved":
            raise HTTPException(
                status_code=400,
                detail="Portal account can only be created from approved applications",
            )
        if not app.created_client_id:
            raise HTTPException(
                status_code=400,
                detail="Create client from application first — portal requires company_id",
            )

        existing = await db.execute(
            select(CustomerPortalAccount).where(
                CustomerPortalAccount.factory_partner_application_id == application_id,
            ),
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Portal account already exists for this application")

        owner = app.contact_name or app.contact_email or app.contact_phone
        tenant_id = app.tenant_id
        if not tenant_id:
            client = await db.get(Client, app.created_client_id)
            if client and client.tenant_id:
                tenant_id = client.tenant_id
        account = CustomerPortalAccount(
            company_id=app.created_client_id,
            company_name=app.company_name,
            portal_status="active",
            owner_user=owner,
            factory_partner_application_id=app.id,
            tenant_id=tenant_id,
        )
        db.add(account)
        await db.commit()
        await db.refresh(account)
        logger.info(
            "%s create-account: application=%s company=%s account=%s",
            MARKER, app.id, app.created_client_id, account.id,
        )
        return {
            "account": _serialize_account(account),
            "message": "Portal account created. Read-only company-scoped access only.",
        }

    @staticmethod
    async def summary_widget(db: AsyncSession, *, tenant_id: UUID | None = None) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for st in PORTAL_STATUSES:
            q = select(func.count()).select_from(CustomerPortalAccount).where(
                CustomerPortalAccount.portal_status == st,
            )
            if tenant_id is not None:
                q = q.where(CustomerPortalAccount.tenant_id == tenant_id)
            counts[st] = int(await db.scalar(q) or 0)

        latest_q = (
            select(CustomerPortalAccount.company_name)
            .where(CustomerPortalAccount.portal_status == "active")
            .order_by(CustomerPortalAccount.created_at.desc())
            .limit(1)
        )
        if tenant_id is not None:
            latest_q = latest_q.where(CustomerPortalAccount.tenant_id == tenant_id)
        latest_r = await db.execute(latest_q)
        latest = latest_r.scalar_one_or_none()

        return {
            "active_accounts": counts.get("active", 0),
            "pending_accounts": counts.get("pending", 0),
            "suspended_accounts": counts.get("suspended", 0),
            "total_accounts": sum(counts.values()),
            "latest_company_name": latest,
        }

    @staticmethod
    async def partner_overview(db: AsyncSession, *, limit: int = 10) -> dict[str, Any]:
        result = await db.execute(
            select(CustomerPortalAccount)
            .where(CustomerPortalAccount.portal_status == "active")
            .order_by(CustomerPortalAccount.created_at.desc())
            .limit(limit),
        )
        accounts = [
            {
                "id": a.id,
                "company_id": a.company_id,
                "company_name": a.company_name,
                "owner_user": a.owner_user,
                "created_at": a.created_at,
            }
            for a in result.scalars().all()
        ]
        widget = await CustomerPortalService.summary_widget(db)
        return {
            "active_accounts": widget["active_accounts"],
            "accounts": accounts,
        }

    @staticmethod
    async def _count_leads(db: AsyncSession, company_id: UUID) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(CrmLead)
                .where(
                    CrmLead.client_id == company_id,
                    CrmLead.status.in_(tuple(_ACTIVE_LEAD_STATUSES)),
                ),
            ) or 0,
        )

    @staticmethod
    async def _count_proposals(db: AsyncSession, company_id: UUID) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(ProposalDocument)
                .where(ProposalDocument.client_id == company_id),
            ) or 0,
        )

    @staticmethod
    async def _count_opportunities(db: AsyncSession, company_id: UUID) -> int:
        return int(
            await db.scalar(
                select(func.count())
                .select_from(CrmDeal)
                .where(
                    CrmDeal.client_id == company_id,
                    CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)),
                ),
            ) or 0,
        )

    @staticmethod
    async def _buyer_opportunity_counts(
        db: AsyncSession,
        company_id: UUID,
    ) -> dict[UUID, int]:
        result = await db.execute(
            select(CrmDeal.lead_id, func.count())
            .where(
                CrmDeal.client_id == company_id,
                CrmDeal.status.in_(tuple(_ACTIVE_DEAL_STATUSES)),
            )
            .group_by(CrmDeal.lead_id),
        )
        return {row[0]: int(row[1]) for row in result.all() if row[0]}

    @staticmethod
    async def dashboard(db: AsyncSession, portal_account_id: UUID) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.revenue_attribution_service import RevenueAttributionService

        account, company_id = await CustomerPortalService.resolve_active_account(db, portal_account_id)
        errors: list[str] = []

        active_leads = await CustomerPortalService._count_leads(db, company_id)
        proposals = await CustomerPortalService._count_proposals(db, company_id)
        opportunities = await CustomerPortalService._count_opportunities(db, company_id)

        buyer_overview = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.overview(db, client_id=company_id),
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

        from app.services.buyer_discovery_service import BuyerDiscoveryService
        from app.services.marketplace_service import MarketplaceService

        discovery_widget = await safe_section(
            "buyer_discovery",
            BuyerDiscoveryService.summary_widget(db, client_id=company_id),
            default={"total_buyers": 0, "high_potential": 0},
            errors=errors,
            db=db,
        )

        marketplace_widget = await safe_section(
            "marketplace",
            MarketplaceService.summary_widget(db),
            default={"total_opportunities": 0, "open_opportunities": 0},
            errors=errors,
            db=db,
        )

        return {
            "account": _serialize_account(account),
            "active_leads": active_leads,
            "active_buyers": active_buyers,
            "discovered_buyers": int(discovery_widget.get("total_buyers") or 0),
            "high_potential_discoveries": int(discovery_widget.get("high_potential") or 0),
            "marketplace_opportunities": int(marketplace_widget.get("open_opportunities") or 0),
            "marketplace_total": int(marketplace_widget.get("total_opportunities") or 0),
            "proposals": proposals,
            "opportunities": opportunities,
            "revenue_summary": revenue_summary,
            "errors": errors,
        }

    @staticmethod
    async def buyers(
        db: AsyncSession,
        portal_account_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService

        account, company_id = await CustomerPortalService.resolve_active_account(db, portal_account_id)
        errors: list[str] = []

        buyer_data = await safe_section(
            "buyer_intelligence",
            BuyerIntelligenceService.list_buyers(
                db, client_id=company_id, skip=0, limit=500,
            ),
            default={"items": [], "total": 0},
            errors=errors,
            db=db,
        )
        opp_counts = await CustomerPortalService._buyer_opportunity_counts(db, company_id)

        items: list[dict[str, Any]] = []
        for row in buyer_data.get("items") or []:
            buyer_id = row.get("buyer_id")
            items.append({
                "buyer_id": buyer_id,
                "name": row.get("name") or "Unknown",
                "company": row.get("company"),
                "buyer_score": row.get("buyer_score", 0),
                "classification": row.get("classification"),
                "risk_level": row.get("risk_level", "low"),
                "opportunities": opp_counts.get(buyer_id, 0),
                "annual_potential": row.get("annual_potential", 0),
                "status": row.get("status", "new"),
            })

        total = len(items)
        limit = clamp_limit(limit)
        page = items[skip: skip + limit]

        return {
            "account": _serialize_account(account),
            "items": page,
            "total": total,
            "errors": errors,
        }

    @staticmethod
    async def deals(
        db: AsyncSession,
        portal_account_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        from app.services.deal_risk_service import DealRiskService

        account, company_id = await CustomerPortalService.resolve_active_account(db, portal_account_id)
        errors: list[str] = []

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
                "title": row.get("title") or "Deal",
                "buyer_name": row.get("buyer_name"),
                "status": row.get("status"),
                "deal_health_score": row.get("deal_health_score", 0),
                "risk_level": row.get("risk_level"),
                "close_probability": row.get("close_probability", 0.0),
                "expected_close_date": row.get("expected_close_date"),
                "revenue": row.get("revenue", 0),
                "currency": row.get("currency", "UZS"),
            }
            for row in deal_data.get("items") or []
        ]

        return {
            "account": _serialize_account(account),
            "items": items,
            "total": int(deal_data.get("total") or len(items)),
            "errors": errors,
        }

    @staticmethod
    async def proposals(
        db: AsyncSession,
        portal_account_id: UUID,
        *,
        skip: int = 0,
        limit: int = DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        account, company_id = await CustomerPortalService.resolve_active_account(db, portal_account_id)
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
                "title": row[0].title,
                "status": row[0].status,
                "buyer_name": row[1],
                "sent_at": row[0].sent_at,
                "created_at": row[0].created_at,
            }
            for row in result.all()
        ]

        return {
            "account": _serialize_account(account),
            "items": items,
            "total": total,
            "errors": [],
        }

    @staticmethod
    async def reports(db: AsyncSession, portal_account_id: UUID) -> dict[str, Any]:
        from app.services.buyer_intelligence_service import BuyerIntelligenceService
        from app.services.revenue_attribution_service import RevenueAttributionService
        from app.services.revenue_forecast_service import RevenueForecastService

        account, company_id = await CustomerPortalService.resolve_active_account(db, portal_account_id)
        errors: list[str] = []

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
            BuyerIntelligenceService.top_buyers(db, client_id=company_id, limit=5),
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
                "annual_potential": row.get("annual_potential", 0),
            }
            for row in top_data.get("top_buyers") or []
        ]

        from app.services.buyer_discovery_service import BuyerDiscoveryService
        from app.services.marketplace_service import MarketplaceService

        discovery_data = await safe_section(
            "buyer_discovery",
            BuyerDiscoveryService.top_opportunities(db, client_id=company_id, limit=5),
            default={"top_buyers": []},
            errors=errors,
            db=db,
        )
        buyer_opportunities = [
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

        marketplace_data = await safe_section(
            "marketplace",
            MarketplaceService.top_opportunities(db, limit=5),
            default={"best_opportunities": []},
            errors=errors,
            db=db,
        )
        exchange_opportunities = [
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

        client = await db.get(Client, company_id)
        portal_tenant_id = client.tenant_id if client else None
        network_data = await safe_section(
            "buyer_network",
            BuyerNetworkService.insights(db, tenant_id=portal_tenant_id, limit=8),
            default={},
            errors=errors,
            db=db,
        )
        network_insights = {
            "strongest_buyers": network_data.get("strongest_buyers") or [],
            "strategic_buyers": network_data.get("strategic_buyers") or [],
            "underutilized_buyers": network_data.get("underutilized_buyers") or [],
        }

        from app.services.buyer_acquisition_service import BuyerAcquisitionService

        acquisition_data = await safe_section(
            "buyer_acquisition",
            BuyerAcquisitionService.executive_overview(
                db, client_id=company_id, tenant_id=portal_tenant_id, limit=8,
            ),
            default={},
            errors=errors,
            db=db,
        )

        return {
            "account": _serialize_account(account),
            "revenue_attribution": revenue_attribution,
            "revenue_forecast": revenue_forecast,
            "forecast_confidence": forecast_data.get("confidence", "medium"),
            "top_buyers": top_buyers,
            "buyer_opportunities": buyer_opportunities,
            "exchange_opportunities": exchange_opportunities,
            "network_insights": network_insights,
            "buyer_acquisition": acquisition_data.get("overview") or {},
            "acquisition_insights": {
                "top_buyers": acquisition_data.get("top_buyers") or [],
                "strongest_relationships": acquisition_data.get("strongest_relationships") or [],
                "highest_opportunity_buyers": acquisition_data.get("highest_opportunity_buyers") or [],
                "best_countries": acquisition_data.get("best_countries") or [],
                "best_industries": acquisition_data.get("best_industries") or [],
            },
            "errors": errors,
        }

    @staticmethod
    async def billing(db: AsyncSession, portal_account_id: UUID) -> dict[str, Any]:
        """Read-only billing summary scoped to portal tenant."""
        from app.services.subscription_service import SubscriptionService

        account, company_id = await CustomerPortalService.resolve_active_account(
            db, portal_account_id,
        )
        errors: list[str] = []
        billing_summary: dict[str, Any] = {}
        if account.tenant_id:
            billing_summary = await safe_section(
                "subscription_billing",
                SubscriptionService.summary(db, account.tenant_id),
                default={},
                errors=errors,
                db=db,
            )
        else:
            errors.append("No tenant linked — subscription billing unavailable")
        return {
            "account": _serialize_account(account),
            "billing_summary": billing_summary,
            "errors": errors,
        }
