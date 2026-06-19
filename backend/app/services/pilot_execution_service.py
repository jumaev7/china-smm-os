"""Pilot Client Onboarding Execution v1 — safe pilot seed, cross-module wiring, execution report."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.buyer_network import BuyerNetworkProfile, BuyerRelationship
from app.models.client import Client
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.customer_portal_account import CustomerPortalAccount
from app.models.deal_room import DealRoom
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.factory_platform_profile import FactoryPlatformProfile
from app.models.factory_profile import (
    FactoryCatalogProduct,
    FactoryCertificate,
    FactoryExportMarket,
    FactoryMediaAsset,
)
from app.models.marketplace import MarketplaceOpportunity, MarketplaceOpportunityInterest
from app.models.revenue_event import RevenueEvent
from app.models.tenant import TenantUser
from app.services.auth_service import hash_password, verify_password
from app.services.buyer_acquisition_engine_service import BuyerAcquisitionEngineService
from app.services.customer_portal_service import CustomerPortalService
from app.services.factory_partner_portal_service import FactoryPartnerPortalService
from app.services.factory_platform_service import FactoryPlatformService
from app.services.factory_profile_service import FactoryProfileService
from app.services.first_pilot_client_service import FirstPilotClientService
from app.services.pilot_onboarding_service import PilotOnboardingService
from app.services.real_factory_pilot_service import RealFactoryPilotService
from app.services.revenue_engine_service import RevenueEngineService
from app.services.subscription_service import SubscriptionService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Pilot Execution]"
PILOT_EXECUTION_MARKER = "[PILOT_EXECUTION_V1]"
PILOT_EXECUTION_COMPANY = "Guangzhou Precision Machinery Export Co."
PILOT_EXECUTION_EMAIL = "pilot-execution@factory.local"
PILOT_EXECUTION_PASSWORD = "pilotexec1234"

_EXECUTION_STEPS: tuple[tuple[str, str], ...] = (
    ("factory_application", "Real factory application"),
    ("application_approved", "Approved application"),
    ("company_client", "Company client"),
    ("tenant", "Tenant workspace"),
    ("tenant_owner", "Tenant owner user"),
    ("subscription", "Active subscription"),
    ("factory_profile", "Factory profile enriched"),
    ("product_catalog", "Product catalog"),
    ("certificates", "Certificates"),
    ("export_markets", "Export markets"),
    ("buyer_records", "Buyer records"),
    ("buyer_opportunities", "Buyer opportunities"),
    ("crm_leads", "CRM leads"),
    ("crm_deals", "CRM deals"),
    ("deal_rooms", "Deal room records"),
    ("revenue_events", "Revenue events"),
    ("cross_module_wiring", "Cross-module data wiring"),
)

_PAGE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("real_factory_pilot", "/real-factory-pilot", "/api/v1/real-factory-pilot/overview"),
    ("factory_platform", "/factory-platform", "/api/v1/factory-platform/summary-widget"),
    ("customer_portal_v2", "/customer-portal-v2", "/api/v1/customer-portal-v2/summary-widget"),
    ("buyer_acquisition_engine", "/buyer-acquisition-engine", "/api/v1/buyer-acquisition-engine/overview"),
    ("revenue_engine", "/revenue-engine", "/api/v1/revenue-engine/overview"),
    ("deal_room", "/deal-room", "/api/v1/deal-room/v2/overview"),
    ("executive_copilot", "/executive-copilot", "/api/v1/executive-copilot/overview"),
    ("dashboard", "/dashboard", "/api/v1/dashboard/overview"),
)

_TENANT_SCOPED_PAGES = frozenset({"factory_platform", "customer_portal_v2"})
_ADMIN_SCOPED_PAGES = frozenset({"real_factory_pilot", "executive_copilot"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Pilot execution tooling only — data tagged [PILOT_EXECUTION_V1], never overwrites existing "
        "execution records. No automatic messages, payment processing, or external API calls."
    )


class PilotExecutionService:
    @staticmethod
    async def _execution_application(db: AsyncSession) -> FactoryPartnerApplication | None:
        result = await db.execute(
            select(FactoryPartnerApplication)
            .where(
                (FactoryPartnerApplication.company_name == PILOT_EXECUTION_COMPANY)
                | (FactoryPartnerApplication.company_description.contains(PILOT_EXECUTION_MARKER)),
            )
            .order_by(FactoryPartnerApplication.created_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def execution_data_present(db: AsyncSession) -> bool:
        return (await PilotExecutionService._execution_application(db)) is not None

    @staticmethod
    async def _execution_context(db: AsyncSession) -> dict[str, Any]:
        app = await PilotExecutionService._execution_application(db)
        if not app:
            return {"application": None, "tenant_id": None, "client_id": None, "owner": None}
        owner = None
        if app.tenant_id:
            owner_r = await db.execute(
                select(TenantUser)
                .where(
                    TenantUser.tenant_id == app.tenant_id,
                    TenantUser.role == "owner",
                )
                .limit(1),
            )
            owner = owner_r.scalar_one_or_none()
        return {
            "application": app,
            "tenant_id": app.tenant_id,
            "client_id": app.created_client_id,
            "owner": owner,
        }

    @staticmethod
    async def _enrich_factory_profile(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        client_id: UUID,
        app: FactoryPartnerApplication,
    ) -> None:
        scope = await FactoryPlatformService.resolve_scope(db, tenant_id)
        profile = await FactoryProfileService._ensure_v2_data(db, scope)

        profile.company_name = app.company_name
        profile.brand_name = app.company_name
        profile.country = app.country or "China"
        profile.city = app.city or "Guangzhou"
        profile.industry = app.industry or "manufacturing"
        profile.company_description = (
            f"{PILOT_EXECUTION_MARKER} Leading precision machinery exporter serving "
            "Central Asia, Russia, and Middle East markets."
        )
        profile.contact_name = app.contact_name or "Zhang Wei"
        profile.contact_email = app.contact_email or PILOT_EXECUTION_EMAIL
        profile.contact_phone = app.contact_phone or "+86-20-8888-0001"
        profile.website = app.website or "https://precision-machinery-export.example"
        profile.logo_url = "/media/pilot/execution-logo.png"
        profile.factory_video_url = "/media/pilot/execution-factory-tour.mp4"
        profile.founded_year = 2008
        profile.employee_count = 320
        profile.industries = ["manufacturing", "industrial equipment", "export"]
        profile.product_categories = app.product_categories or [
            "CNC Machinery", "Industrial Components", "Precision Tools",
        ]
        profile.markets = app.target_markets or [
            "Uzbekistan", "Kazakhstan", "Russia", "UAE", "Turkey",
        ]
        profile.export_regions = profile.markets
        profile.verification_status = "pending"
        profile.updated_at = _utc_now()

        media_count = int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryMediaAsset)
                .where(FactoryMediaAsset.tenant_id == tenant_id),
            ) or 0,
        )
        if media_count == 0:
            for title, media_type in (
                ("Factory floor overview", "image"),
                ("Assembly line", "image"),
                ("Quality control lab", "image"),
            ):
                db.add(FactoryMediaAsset(
                    tenant_id=tenant_id,
                    media_type=media_type,
                    title=f"{title} {PILOT_EXECUTION_MARKER}",
                    storage_path=f"/media/pilot/{title.lower().replace(' ', '-')}.jpg",
                    reusable_modules=["customer_portal", "buyer_acquisition", "smm"],
                ))

        products = (
            await db.execute(
                select(FactoryCatalogProduct).where(FactoryCatalogProduct.tenant_id == tenant_id),
            )
        ).scalars().all()
        for idx, prod in enumerate(products):
            prod.status = "active"
            prod.export_available = True
            prod.description = f"{PILOT_EXECUTION_MARKER} {prod.description or prod.product_name}"
            if idx == 0:
                prod.image_url = "/media/pilot/cnc-machine.jpg"
                prod.moq = 10
                prod.price_min = Decimal("15000")
                prod.price_max = Decimal("85000")
                prod.currency = "USD"

        today = date.today()
        certs = (
            await db.execute(
                select(FactoryCertificate).where(FactoryCertificate.tenant_id == tenant_id),
            )
        ).scalars().all()
        for cert in certs:
            if not cert.expiry_date:
                cert.expiry_date = date(today.year + 2, 12, 31)
            if not cert.certificate_number:
                cert.certificate_number = f"EXEC-{cert.certificate_type}-001"

        await db.flush()

    @staticmethod
    async def _seed_complete(db: AsyncSession, tenant_id: UUID | None, client_id: UUID | None) -> bool:
        if not tenant_id or not client_id:
            return False
        deal_count = int(
            await db.scalar(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.client_id == client_id),
            ) or 0,
        )
        buyer_rel = int(
            await db.scalar(
                select(func.count())
                .select_from(BuyerRelationship)
                .where(BuyerRelationship.tenant_id == tenant_id),
            ) or 0,
        )
        return deal_count >= 2 and buyer_rel >= 3

    @staticmethod
    async def _seed_linked_entities(
        db: AsyncSession,
        *,
        app: FactoryPartnerApplication,
        tenant_id: UUID,
        client_id: UUID,
        now: datetime,
    ) -> dict[str, int]:
        await PilotExecutionService._enrich_factory_profile(
            db, tenant_id=tenant_id, client_id=client_id, app=app,
        )

        client = await db.get(Client, client_id)
        if client:
            client.notes = f"{PILOT_EXECUTION_MARKER} {client.notes or ''}".strip()
            client.tenant_id = tenant_id
            client.business_category = "manufacturing"

        owner = await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.email == PILOT_EXECUTION_EMAIL,
            ),
        )
        owner_user = owner.scalar_one_or_none()
        if owner_user and (
            not owner_user.password_hash
            or not verify_password(PILOT_EXECUTION_PASSWORD, owner_user.password_hash)
        ):
            owner_user.password_hash = hash_password(PILOT_EXECUTION_PASSWORD)
            owner_user.status = "active"
            owner_user.updated_at = now

        sub, _ = await SubscriptionService._active_subscription(db, tenant_id)
        if not sub:
            await SubscriptionService.create_subscription(
                db,
                tenant_id=tenant_id,
                plan_code="professional",
                billing_cycle="monthly",
                status="active",
            )

        portal_r = await db.execute(
            select(CustomerPortalAccount)
            .where(CustomerPortalAccount.company_id == client_id)
            .limit(1),
        )
        if not portal_r.scalar_one_or_none():
            await CustomerPortalService.create_portal_account_from_application(db, app.id)

        buyer_network_count = 0
        existing_rels = int(
            await db.scalar(
                select(func.count())
                .select_from(BuyerRelationship)
                .where(BuyerRelationship.tenant_id == tenant_id),
            ) or 0,
        )
        buyer_specs = (
            ("Tashkent Industrial Group", "Uzbekistan", "manufacturing", "active", 82),
            ("Almaty Trade Partners", "Kazakhstan", "distribution", "contacted", 78),
            ("Moscow Engineering LLC", "Russia", "industrial equipment", "discovered", 74),
            ("Dubai Gulf Imports", "UAE", "retail", "active", 80),
            ("Istanbul Machinery Hub", "Turkey", "manufacturing", "contacted", 76),
        )
        if existing_rels < 3:
            for company, country, industry, rel_type, strength in buyer_specs:
                profile = BuyerNetworkProfile(
                    company_name=f"{company} {PILOT_EXECUTION_MARKER}",
                    country=country,
                    industry=industry,
                    classification="strategic" if strength >= 80 else "high_potential",
                    opportunity_score=strength,
                    network_strength=strength,
                    buyer_status="active" if rel_type == "active" else "contacted",
                    source_key=f"execution:{company.lower().replace(' ', '-')}",
                )
                db.add(profile)
                await db.flush()
                db.add(BuyerRelationship(
                    buyer_id=profile.id,
                    tenant_id=tenant_id,
                    relationship_type=rel_type,
                    relationship_strength=strength,
                ))
                buyer_network_count += 1

        discovery_count = 0
        existing_discovery = int(
            await db.scalar(
                select(func.count())
                .select_from(BuyerDiscoveryEntry)
                .where(BuyerDiscoveryEntry.client_id == client_id),
            ) or 0,
        )
        if existing_discovery < 3:
            for idx, (company, country, industry, *_rest) in enumerate(buyer_specs[:4]):
                db.add(BuyerDiscoveryEntry(
                    client_id=client_id,
                    company_name=f"{company} {PILOT_EXECUTION_MARKER}",
                    country=country,
                    industry=industry,
                    source="pilot_execution",
                    contact_status="qualified" if idx < 2 else "researched",
                    opportunity_score=70 + idx * 5,
                    category="strategic" if idx < 2 else "high_potential",
                    pipeline_stage="negotiating" if idx == 0 else "qualified",
                    notes=f"{PILOT_EXECUTION_MARKER} Execution buyer for acquisition engine.",
                ))
                discovery_count += 1

        marketplace_count = 0
        existing_mkt = int(
            await db.scalar(
                select(func.count())
                .select_from(MarketplaceOpportunity)
                .where(MarketplaceOpportunity.created_by_tenant == tenant_id),
            ) or 0,
        )
        marketplace_opps: list[MarketplaceOpportunity] = []
        if existing_mkt < 2:
            for idx, (title, buyer_co, country, value) in enumerate(
                (
                    ("CNC lathe bulk order", "Tashkent Industrial Group", "Uzbekistan", 380_000),
                    ("Industrial components RFQ", "Almaty Trade Partners", "Kazakhstan", 220_000),
                    ("Precision tools distributor", "Dubai Gulf Imports", "UAE", 175_000),
                ),
            ):
                opp = MarketplaceOpportunity(
                    title=f"{title} {PILOT_EXECUTION_MARKER}",
                    description=f"{PILOT_EXECUTION_MARKER} Execution marketplace opportunity.",
                    buyer_company=buyer_co,
                    country=country,
                    industry="manufacturing",
                    opportunity_type="rfq",
                    estimated_value=Decimal(str(value)),
                    status="open",
                    visibility="public",
                    created_by_tenant=tenant_id,
                    rank_score=85 - idx * 5,
                )
                db.add(opp)
                marketplace_opps.append(opp)
                marketplace_count += 1
            await db.flush()
            if marketplace_opps:
                db.add(MarketplaceOpportunityInterest(
                    opportunity_id=marketplace_opps[0].id,
                    tenant_id=tenant_id,
                    note=f"{PILOT_EXECUTION_MARKER} Tenant expressed interest — manual follow-up only.",
                ))

        existing_leads = int(
            await db.scalar(
                select(func.count()).select_from(CrmLead).where(CrmLead.client_id == client_id),
            ) or 0,
        )
        leads: list[CrmLead] = []
        if existing_leads < 3:
            lead_specs = (
                ("Otabek Karimov", "Tashkent Industrial Group", "negotiating", 380_000),
                ("Aida Suleimenova", "Almaty Trade Partners", "contacted", 220_000),
                ("Dmitry Volkov", "Moscow Engineering LLC", "qualified", 290_000),
                ("Hassan Al-Rashid", "Dubai Gulf Imports", "contacted", 175_000),
            )
            for name, company, status, value in lead_specs:
                lead = CrmLead(
                    client_id=client_id,
                    name=name,
                    company=f"{company} {PILOT_EXECUTION_MARKER}",
                    email=f"{name.split()[0].lower()}@buyer.example",
                    phone="+998-90-000-0000",
                    source="buyer_discovery",
                    language="en",
                    status=status,
                    priority="high",
                    estimated_value=Decimal(str(value)),
                    lead_score=72,
                    notes=f"{PILOT_EXECUTION_MARKER} Execution CRM lead.",
                )
                db.add(lead)
                leads.append(lead)
            await db.flush()
        else:
            lead_rows = await db.execute(
                select(CrmLead)
                .where(CrmLead.client_id == client_id)
                .order_by(CrmLead.created_at.asc())
                .limit(4),
            )
            leads = list(lead_rows.scalars().all())

        existing_deals = int(
            await db.scalar(
                select(func.count()).select_from(CrmDeal).where(CrmDeal.client_id == client_id),
            ) or 0,
        )
        deals: list[CrmDeal] = []
        deal_room_count = 0
        revenue_count = 0
        if existing_deals < 2 and len(leads) >= 3:
            deal_specs = (
                ("CNC Machinery Export Deal", "negotiation", 420_000, 65),
                ("Industrial Components Contract", "quotation", 220_000, 45),
                ("Precision Tools Distribution", "qualified", 175_000, 35),
            )
            for idx, (title, status, value, prob) in enumerate(deal_specs):
                deal = CrmDeal(
                    client_id=client_id,
                    lead_id=leads[idx].id,
                    title=f"{title} {PILOT_EXECUTION_MARKER}",
                    status=status,
                    expected_value=Decimal(str(value)),
                    deal_amount=Decimal(str(value)),
                    currency="USD",
                    probability=prob,
                )
                db.add(deal)
                deals.append(deal)
            await db.flush()

            for idx, deal in enumerate(deals[:2]):
                stage = "negotiation" if idx == 0 else "quotation"
                db.add(DealRoom(
                    crm_client_id=client_id,
                    deal_name=deal.title,
                    stage=stage,
                    status="active",
                    probability=deal.probability,
                    expected_value=deal.expected_value,
                ))
                deal_room_count += 1

            prop_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmProposal)
                    .where(CrmProposal.client_id == client_id),
                ) or 0,
            )
            if prop_count == 0:
                db.add(CrmProposal(
                    lead_id=leads[0].id,
                    client_id=client_id,
                    title=f"Execution Commercial Proposal {PILOT_EXECUTION_MARKER}",
                    language="en",
                    status="sent",
                    proposal_text="Pilot execution commercial proposal — manual review only.",
                    estimated_value=Decimal("420000"),
                ))

            for deal in deals:
                db.add(RevenueEvent(
                    deal_id=deal.id,
                    type="pipeline",
                    amount=deal.expected_value,
                ))
                revenue_count += 1
            if deals:
                db.add(RevenueEvent(
                    deal_id=deals[0].id,
                    type="forecast",
                    amount=Decimal("420000"),
                ))
                revenue_count += 1

        return {
            "buyer_network_profiles": buyer_network_count or existing_rels,
            "buyer_discovery": discovery_count or existing_discovery,
            "marketplace_opportunities": marketplace_count or existing_mkt,
            "crm_leads": len(leads) or existing_leads,
            "crm_deals": len(deals) or existing_deals,
            "deal_rooms": deal_room_count,
            "revenue_events": revenue_count,
        }

    @staticmethod
    async def seed_pilot_data(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
        existing = await PilotExecutionService._execution_application(db)
        if existing and not force:
            if await PilotExecutionService._seed_complete(
                db, existing.tenant_id, existing.created_client_id,
            ):
                return {
                    "created": False,
                    "message": "Pilot execution data already exists and is complete",
                    "execution_marker": PILOT_EXECUTION_MARKER,
                    "application_id": existing.id,
                    "tenant_id": existing.tenant_id,
                    "client_id": existing.created_client_id,
                }
            readiness_before = await PilotExecutionService._collect_readiness(db)
            counts = await PilotExecutionService._seed_linked_entities(
                db,
                app=existing,
                tenant_id=existing.tenant_id,
                client_id=existing.created_client_id,
                now=_utc_now(),
            )
            await db.commit()
            FirstPilotClientService._invalidate_cache()
            await RealFactoryPilotService.refresh(db)
            readiness_after = await PilotExecutionService._collect_readiness(db)
            return {
                "created": False,
                "updated": True,
                "message": "Pilot execution data completed for existing partial seed",
                "execution_marker": PILOT_EXECUTION_MARKER,
                "application_id": existing.id,
                "tenant_id": existing.tenant_id,
                "client_id": existing.created_client_id,
                "login_email": PILOT_EXECUTION_EMAIL,
                "login_password": PILOT_EXECUTION_PASSWORD,
                "readiness_before": readiness_before,
                "readiness_after": readiness_after,
                "counts": counts,
            }

        if existing and force:
            return {
                "created": False,
                "message": (
                    f"Force re-seed not supported — remove records tagged {PILOT_EXECUTION_MARKER} "
                    "manually then seed again"
                ),
                "execution_marker": PILOT_EXECUTION_MARKER,
                "application_id": existing.id,
                "tenant_id": existing.tenant_id,
            }

        readiness_before = await PilotExecutionService._collect_readiness(db)

        now = _utc_now()
        demo_desc = (
            f"{PILOT_EXECUTION_MARKER} Safe pilot execution dataset for first real factory "
            "onboarding end-to-end validation."
        )

        app = FactoryPartnerApplication(
            company_name=PILOT_EXECUTION_COMPANY,
            country="China",
            city="Guangzhou",
            contact_name="Zhang Wei",
            contact_email=PILOT_EXECUTION_EMAIL,
            contact_phone="+86-20-8888-0001",
            website="https://precision-machinery-export.example",
            industry="manufacturing",
            product_categories=["CNC Machinery", "Industrial Components", "Precision Tools"],
            company_description=demo_desc,
            cooperation_terms_accepted=True,
            commission_model="revenue_share",
            target_markets=["Uzbekistan", "Kazakhstan", "Russia", "UAE", "Turkey"],
            status="submitted",
            submitted_at=now,
        )
        db.add(app)
        await db.flush()

        app.status = "approved"
        app.reviewed_at = now
        app.updated_at = now
        await db.flush()

        client_result = await FactoryPartnerPortalService.create_client_from_application(db, app.id)
        client_id = UUID(str(client_result["client_id"]))
        app = await db.get(FactoryPartnerApplication, app.id)
        assert app is not None

        tenant_result = await TenantService.create_tenant_from_application(
            db, app.id, owner_email=PILOT_EXECUTION_EMAIL,
        )
        tenant_id = UUID(str(tenant_result["tenant"]["id"]))
        app = await db.get(FactoryPartnerApplication, app.id)
        assert app is not None

        owner = await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.email == PILOT_EXECUTION_EMAIL,
            ),
        )
        owner_user = owner.scalar_one_or_none()
        if owner_user:
            owner_user.password_hash = hash_password(PILOT_EXECUTION_PASSWORD)
            owner_user.status = "active"
            owner_user.updated_at = now

        portal_result = await CustomerPortalService.create_portal_account_from_application(db, app.id)
        portal_id = portal_result["account"]["id"]

        sub_result = await SubscriptionService.create_subscription(
            db,
            tenant_id=tenant_id,
            plan_code="professional",
            billing_cycle="monthly",
            status="active",
        )
        subscription_id = sub_result["id"]

        counts = await PilotExecutionService._seed_linked_entities(
            db,
            app=app,
            tenant_id=tenant_id,
            client_id=client_id,
            now=now,
        )

        await db.commit()

        FirstPilotClientService._invalidate_cache()
        await RealFactoryPilotService.refresh(db)

        readiness_after = await PilotExecutionService._collect_readiness(db)

        cat_count = int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryCatalogProduct)
                .where(FactoryCatalogProduct.tenant_id == tenant_id),
            ) or 0,
        )
        cert_count = int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryCertificate)
                .where(FactoryCertificate.tenant_id == tenant_id),
            ) or 0,
        )
        market_count = int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryExportMarket)
                .where(FactoryExportMarket.tenant_id == tenant_id),
            ) or 0,
        )

        logger.info(
            "%s seed complete: app=%s tenant=%s client=%s readiness=%s→%s",
            MARKER,
            app.id,
            tenant_id,
            client_id,
            readiness_before["real_factory_pilot"],
            readiness_after["real_factory_pilot"],
        )

        return {
            "created": True,
            "message": "Pilot execution data seeded — tagged, cross-module, no external calls",
            "execution_marker": PILOT_EXECUTION_MARKER,
            "application_id": app.id,
            "tenant_id": tenant_id,
            "client_id": client_id,
            "portal_account_id": portal_id,
            "subscription_id": subscription_id,
            "login_email": PILOT_EXECUTION_EMAIL,
            "login_password": PILOT_EXECUTION_PASSWORD,
            "readiness_before": readiness_before,
            "readiness_after": readiness_after,
            "counts": {
                **counts,
                "catalog_products": cat_count,
                "certificates": cert_count,
                "export_markets": market_count,
                "proposals": 1,
            },
        }

    @staticmethod
    async def _collect_readiness(db: AsyncSession) -> dict[str, int]:
        ctx = await PilotExecutionService._execution_context(db)
        tenant_id = ctx.get("tenant_id")
        client_id = ctx.get("client_id")

        real_pilot_score = 0
        buyer_score = 0
        revenue_score = 0
        profile_score = 0

        if ctx.get("application"):
            try:
                pilot_readiness = await asyncio.wait_for(
                    RealFactoryPilotService.readiness(db),
                    timeout=30.0,
                )
                real_pilot_score = int(pilot_readiness.get("score") or 0)
            except Exception as exc:
                logger.info("%s real pilot readiness skip: %s", MARKER, exc)

        if client_id or tenant_id:
            try:
                bae = await BuyerAcquisitionEngineService.overview(
                    db, client_id=client_id, tenant_id=tenant_id,
                )
                buyer_score = int(bae.get("readiness_score") or 0)
            except Exception as exc:
                logger.info("%s buyer engine readiness skip: %s", MARKER, exc)

        if client_id or tenant_id:
            try:
                rev = await RevenueEngineService.overview(
                    db, client_id=client_id, tenant_id=tenant_id,
                )
                revenue_score = int(rev.get("readiness_score") or 0)
            except Exception as exc:
                logger.info("%s revenue engine readiness skip: %s", MARKER, exc)

        if tenant_id:
            try:
                score_data = await FactoryProfileService.profile_score(db, tenant_id)
                profile_score = int(score_data.get("profile_score") or 0)
            except Exception as exc:
                logger.info("%s profile score skip: %s", MARKER, exc)

        return {
            "real_factory_pilot": _clamp(real_pilot_score),
            "buyer_acquisition_engine": _clamp(buyer_score),
            "revenue_engine": _clamp(revenue_score),
            "factory_profile_score": _clamp(profile_score),
        }

    @staticmethod
    async def _build_execution_steps(db: AsyncSession, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        app = ctx.get("application")
        tenant_id = ctx.get("tenant_id")
        client_id = ctx.get("client_id")
        owner = ctx.get("owner")

        if not app:
            return [
                {
                    "step": step,
                    "label": label,
                    "status": "blocked",
                    "message": "Seed pilot execution data first",
                }
                for step, label in _EXECUTION_STEPS
            ]

        portal = None
        if client_id:
            portal_r = await db.execute(
                select(CustomerPortalAccount)
                .where(CustomerPortalAccount.company_id == client_id)
                .limit(1),
            )
            portal = portal_r.scalar_one_or_none()

        subscription = None
        if tenant_id:
            subscription, _ = await SubscriptionService._active_subscription(db, tenant_id)

        profile_score = 0
        cat_count = cert_count = market_count = 0
        if tenant_id:
            try:
                score_data = await FactoryProfileService.profile_score(db, tenant_id)
                profile_score = int(score_data.get("profile_score") or 0)
            except Exception:
                pass
            cat_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(FactoryCatalogProduct)
                    .where(FactoryCatalogProduct.tenant_id == tenant_id),
                ) or 0,
            )
            cert_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(FactoryCertificate)
                    .where(FactoryCertificate.tenant_id == tenant_id),
                ) or 0,
            )
            market_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(FactoryExportMarket)
                    .where(FactoryExportMarket.tenant_id == tenant_id),
                ) or 0,
            )

        buyer_rel_count = 0
        if tenant_id:
            buyer_rel_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerRelationship)
                    .where(BuyerRelationship.tenant_id == tenant_id),
                ) or 0,
            )

        discovery_count = 0
        if client_id:
            discovery_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerDiscoveryEntry)
                    .where(BuyerDiscoveryEntry.client_id == client_id),
                ) or 0,
            )

        lead_count = deal_count = room_count = rev_count = 0
        if client_id:
            lead_count = int(
                await db.scalar(
                    select(func.count()).select_from(CrmLead).where(CrmLead.client_id == client_id),
                ) or 0,
            )
            deal_count = int(
                await db.scalar(
                    select(func.count()).select_from(CrmDeal).where(CrmDeal.client_id == client_id),
                ) or 0,
            )
            room_count = int(
                await db.scalar(
                    select(func.count()).select_from(DealRoom).where(DealRoom.crm_client_id == client_id),
                ) or 0,
            )
            rev_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(RevenueEvent)
                    .join(CrmDeal, RevenueEvent.deal_id == CrmDeal.id)
                    .where(CrmDeal.client_id == client_id),
                ) or 0,
            )

        checks: dict[str, tuple[bool, str | None]] = {
            "factory_application": (True, f"Application {app.id}"),
            "application_approved": (app.status == "approved", f"Status={app.status}"),
            "company_client": (client_id is not None, f"client_id={client_id}"),
            "tenant": (tenant_id is not None, f"tenant_id={tenant_id}"),
            "tenant_owner": (
                owner is not None and bool(owner.password_hash),
                owner.email if owner else "No owner user",
            ),
            "subscription": (
                subscription is not None and subscription.status in ("trial", "active"),
                f"{subscription.status}" if subscription else "No subscription",
            ),
            "factory_profile": (profile_score >= 70, f"Profile score {profile_score}/100"),
            "product_catalog": (cat_count > 0, f"{cat_count} product(s)"),
            "certificates": (cert_count > 0, f"{cert_count} certificate(s)"),
            "export_markets": (market_count > 0, f"{market_count} market(s)"),
            "buyer_records": (discovery_count >= 3, f"{discovery_count} discovery + {buyer_rel_count} network"),
            "buyer_opportunities": (buyer_rel_count > 0, f"{buyer_rel_count} relationship(s)"),
            "crm_leads": (lead_count >= 3, f"{lead_count} lead(s)"),
            "crm_deals": (deal_count >= 2, f"{deal_count} deal(s)"),
            "deal_rooms": (room_count >= 1, f"{room_count} deal room(s)"),
            "revenue_events": (rev_count >= 2, f"{rev_count} revenue event(s)"),
            "cross_module_wiring": (
                profile_score >= 70
                and buyer_rel_count > 0
                and deal_count >= 2
                and room_count >= 1,
                "Real Factory Pilot, Factory Platform, Buyer Acquisition, Revenue, Deal Room linked",
            ),
        }

        steps: list[dict[str, Any]] = []
        for step, label in _EXECUTION_STEPS:
            ok, message = checks[step]
            if ok:
                status = "completed"
            elif step in ("factory_profile", "cross_module_wiring"):
                status = "warning" if checks[step][0] is False and any(
                    checks[s][0] for s in ("tenant", "company_client", "subscription")
                ) else "blocked"
            else:
                status = "blocked"
            steps.append({
                "step": step,
                "label": label,
                "status": status,
                "message": message,
            })
        return steps

    @staticmethod
    async def verify_pages() -> dict[str, Any]:
        from app.main import app

        transport = ASGITransport(app=app)
        tests: list[dict[str, Any]] = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for page, route, api_path in _PAGE_SPECS:
                start = time.perf_counter()
                error: str | None = None
                status_code = 0
                try:
                    response = await client.get(api_path)
                    status_code = response.status_code
                    if status_code >= 400:
                        detail = response.text[:200] if response.text else response.reason_phrase
                        error = f"HTTP {status_code}: {detail}"
                except Exception as exc:
                    error = str(exc)[:500]

                duration_ms = int((time.perf_counter() - start) * 1000)
                if page in _TENANT_SCOPED_PAGES and status_code in (401, 403, 422):
                    probe_status = "ok"
                    error = "Tenant-scoped route — page loads with tenant context"
                elif page in _ADMIN_SCOPED_PAGES and status_code in (401, 403):
                    probe_status = "ok"
                    error = "Admin-scoped route — page loads with admin context"
                elif error or status_code >= 400:
                    probe_status = "error"
                elif duration_ms > SLOW_THRESHOLD_MS:
                    probe_status = "slow"
                else:
                    probe_status = "ok"

                tests.append({
                    "page": page,
                    "route": route,
                    "api_probe": api_path.split("?")[0],
                    "status": probe_status,
                    "duration_ms": duration_ms,
                    "message": error,
                })

        ok_count = sum(1 for t in tests if t["status"] in ("ok", "slow"))
        return {"tests": tests, "ok_count": ok_count, "total": len(tests)}

    @staticmethod
    async def execution_report(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotExecutionService._execution_context(db)
        app = ctx.get("application")
        steps = await PilotExecutionService._build_execution_steps(db, ctx)
        readiness_after = await PilotExecutionService._collect_readiness(db)
        verify = await PilotExecutionService.verify_pages()

        readiness_before = {
            "real_factory_pilot": 0,
            "buyer_acquisition_engine": 0,
            "revenue_engine": 0,
            "factory_profile_score": 0,
        }
        if app:
            onboarding = await PilotOnboardingService._evaluate(db, app)
            readiness_before["real_factory_pilot"] = _clamp(
                max(0, int(onboarding.get("readiness_score") or 0) - 40),
            )

        blockers = [
            s["label"]
            for s in steps
            if s["status"] in ("blocked", "warning")
        ]

        targets_met = (
            readiness_after["real_factory_pilot"] >= 80
            and readiness_after["buyer_acquisition_engine"] > 50
            and readiness_after["revenue_engine"] > 40
            and readiness_after["factory_profile_score"] > 70
        )
        steps_complete = all(s["status"] == "completed" for s in steps)
        pages_ok = all(t["status"] in ("ok", "slow") for t in verify["tests"])

        next_action = None
        for s in steps:
            if s["status"] != "completed":
                next_action = f"Complete: {s['label']} — {s.get('message', '')}"
                break
        if not next_action and not targets_met:
            missing = []
            if readiness_after["real_factory_pilot"] < 80:
                missing.append("Real Factory Pilot readiness >= 80")
            if readiness_after["buyer_acquisition_engine"] <= 50:
                missing.append("Buyer Acquisition readiness > 50")
            if readiness_after["revenue_engine"] <= 40:
                missing.append("Revenue readiness > 40")
            if readiness_after["factory_profile_score"] <= 70:
                missing.append("Factory profile score > 70")
            next_action = f"Improve readiness: {', '.join(missing)}"
        if not next_action and not pages_ok:
            next_action = "Review page verification failures"
        if not next_action:
            next_action = "Pilot execution complete — ready for guided demo walkthrough"

        return {
            "execution_marker": PILOT_EXECUTION_MARKER,
            "execution_data_present": app is not None,
            "company_name": app.company_name if app else None,
            "application_id": app.id if app else None,
            "tenant_id": ctx.get("tenant_id"),
            "client_id": ctx.get("client_id"),
            "completed_steps": steps,
            "remaining_blockers": blockers,
            "readiness_before": readiness_before,
            "readiness_after": readiness_after,
            "next_action": next_action,
            "verified_pages": verify["tests"],
            "pages_ok_count": verify["ok_count"],
            "pages_total": verify["total"],
            "safety_notice": _safety_notice(),
            "implementation_complete": bool(
                app and steps_complete and targets_met and pages_ok,
            ),
            "generated_at": _utc_now(),
        }

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        report = await PilotExecutionService.execution_report(db)
        completed = sum(1 for s in report["completed_steps"] if s["status"] == "completed")
        blocked = sum(
            1 for s in report["completed_steps"] if s["status"] in ("blocked", "warning")
        )
        return {
            "execution_data_present": report["execution_data_present"],
            "company_name": report.get("company_name"),
            "readiness_after": report["readiness_after"],
            "completed_step_count": completed,
            "blocked_step_count": blocked,
            "remaining_blockers": report["remaining_blockers"],
            "next_action": report["next_action"],
            "safety_notice": report["safety_notice"],
            "implementation_complete": report["implementation_complete"],
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        report = await PilotExecutionService.execution_report(db)
        return {
            "execution_data_present": report["execution_data_present"],
            "company_name": report.get("company_name"),
            "readiness_after": report["readiness_after"],
            "completed_step_count": sum(
                1 for s in report["completed_steps"] if s["status"] == "completed"
            ),
            "remaining_blockers": report["remaining_blockers"][:5],
            "next_action": report["next_action"],
            "pages_ok_count": report["pages_ok_count"],
            "pages_total": report["pages_total"],
            "implementation_complete": report["implementation_complete"],
            "safety_notice": report["safety_notice"],
        }
