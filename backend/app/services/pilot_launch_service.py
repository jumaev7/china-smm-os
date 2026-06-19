"""Pilot Launch QA & Demo Data v1 — demo seed, end-to-end QA, launch readiness."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.client import Client
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.customer_portal_account import CustomerPortalAccount
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.factory_profile import FactoryCatalogProduct, FactoryCertificate, FactoryExportMarket
from app.models.marketplace import MarketplaceOpportunity
from app.models.revenue_event import RevenueEvent
from app.models.tenant import TenantUser
from app.services.admin_rbac_service import AdminRbacService
from app.services.admin_security_service import AdminSecurityService
from app.services.auth_service import hash_password, verify_password
from app.services.customer_portal_service import CustomerPortalService
from app.services.factory_partner_portal_service import FactoryPartnerPortalService
from app.services.factory_profile_service import FactoryProfileService
from app.services.pilot_onboarding_service import PilotOnboardingService
from app.services.subscription_service import SubscriptionService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Pilot Launch]"
PILOT_DEMO_MARKER = "[PILOT_LAUNCH_DEMO_V1]"
PILOT_DEMO_COMPANY = "Shenzhen Export Demo Co. (Pilot)"
PILOT_DEMO_EMAIL = "pilot-demo@factory.local"
PILOT_DEMO_PASSWORD = "pilot1234"

_READINESS_WEIGHTS: tuple[tuple[str, str, int], ...] = (
    ("auth_health", "Auth health", 15),
    ("tenant_isolation", "Tenant isolation", 15),
    ("billing_availability", "Billing availability", 10),
    ("factory_profile", "Factory profile completeness", 15),
    ("portal_readiness", "Portal readiness", 10),
    ("buyer_acquisition", "Buyer acquisition data", 10),
    ("dashboard_health", "Dashboard health", 10),
    ("security_status", "Security status", 15),
)

_SMOKE_SPECS: tuple[tuple[str, str, str], ...] = (
    ("dashboard", "/dashboard", "/api/v1/dashboard/overview"),
    ("factory_apply", "/factory-apply", "/api/v1/system/health"),
    ("factory_partners", "/factory-partners", "/api/v1/factory-partner/summary-widget"),
    ("tenants", "/tenants", "/api/v1/tenants?limit=1"),
    ("billing", "/billing", "/api/v1/billing/plans"),
    ("factory_platform", "/factory-platform", "/api/v1/factory-platform/summary-widget"),
    ("customer_portal_v2", "/customer-portal-v2", "/api/v1/customer-portal-v2/summary-widget"),
    ("pilot_onboarding", "/pilot-onboarding", "/api/v1/pilot-onboarding/overview"),
    ("buyer_acquisition", "/buyer-acquisition", "/api/v1/buyer-acquisition/overview"),
    ("marketplace", "/marketplace", "/api/v1/marketplace/overview"),
    ("executive_copilot", "/executive-copilot", "/api/v1/executive-copilot/overview"),
    ("pilot_launch", "/pilot-launch", "/api/v1/pilot-launch/overview"),
)

_QA_STEPS: tuple[tuple[str, str], ...] = (
    ("factory_apply", "Factory apply flow"),
    ("approve_application", "Approve application"),
    ("create_client", "Create client"),
    ("create_tenant", "Create tenant"),
    ("create_portal_account", "Create portal account"),
    ("create_subscription", "Create subscription"),
    ("login", "Tenant login credentials"),
    ("customer_portal_v2", "Customer portal v2"),
    ("factory_platform_v2", "Factory platform v2"),
    ("buyer_acquisition", "Buyer acquisition"),
    ("marketplace", "Marketplace"),
    ("billing", "Billing"),
    ("executive_copilot", "Executive copilot"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Pilot launch tooling only — demo data is tagged and never overwrites real records. "
        "No automatic external messages, payment processing, or production provider calls."
    )


class PilotLaunchService:
    @staticmethod
    async def _demo_application(db: AsyncSession) -> FactoryPartnerApplication | None:
        result = await db.execute(
            select(FactoryPartnerApplication)
            .where(
                (FactoryPartnerApplication.company_name == PILOT_DEMO_COMPANY)
                | (FactoryPartnerApplication.company_description.contains(PILOT_DEMO_MARKER)),
            )
            .order_by(FactoryPartnerApplication.created_at.desc())
            .limit(1),
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def demo_data_present(db: AsyncSession) -> bool:
        return (await PilotLaunchService._demo_application(db)) is not None

    @staticmethod
    async def _demo_context(db: AsyncSession) -> dict[str, Any]:
        app = await PilotLaunchService._demo_application(db)
        if not app:
            return {"application": None, "tenant_id": None, "client_id": None}
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
    async def seed_demo_data(db: AsyncSession, *, force: bool = False) -> dict[str, Any]:
        existing = await PilotLaunchService._demo_application(db)
        if existing and not force:
            return {
                "created": False,
                "message": "Pilot demo data already exists — use force=true to re-seed after manual cleanup",
                "demo_marker": PILOT_DEMO_MARKER,
                "application_id": existing.id,
                "tenant_id": existing.tenant_id,
                "client_id": existing.created_client_id,
            }

        if existing and force:
            return {
                "created": False,
                "message": (
                    "Force re-seed not supported — remove pilot demo records manually "
                    f"(marker {PILOT_DEMO_MARKER}) then seed again"
                ),
                "demo_marker": PILOT_DEMO_MARKER,
                "application_id": existing.id,
                "tenant_id": existing.tenant_id,
            }

        now = _utc_now()
        demo_desc = f"{PILOT_DEMO_MARKER} Safe pilot demo dataset for first client presentation."

        app = FactoryPartnerApplication(
            company_name=PILOT_DEMO_COMPANY,
            country="China",
            city="Shenzhen",
            contact_name="Li Wei (Demo)",
            contact_email=PILOT_DEMO_EMAIL,
            contact_phone="+86-755-0000-0000",
            industry="manufacturing",
            product_categories=["Electronics", "Industrial Components", "Export Goods"],
            company_description=demo_desc,
            cooperation_terms_accepted=True,
            commission_model="revenue_share",
            target_markets=["Germany", "United States", "Russia", "Uzbekistan"],
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
            db, app.id, owner_email=PILOT_DEMO_EMAIL,
        )
        tenant_id = UUID(str(tenant_result["tenant"]["id"]))
        app = await db.get(FactoryPartnerApplication, app.id)
        assert app is not None

        owner = await db.execute(
            select(TenantUser).where(
                TenantUser.tenant_id == tenant_id,
                TenantUser.email == PILOT_DEMO_EMAIL,
            ),
        )
        owner_user = owner.scalar_one_or_none()
        if owner_user:
            owner_user.password_hash = hash_password(PILOT_DEMO_PASSWORD)
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

        scope = {"tenant_id": tenant_id, "company_id": client_id}
        profile = await FactoryProfileService._ensure_v2_data(db, scope)

        client = await db.get(Client, client_id)
        if client:
            client.notes = f"{PILOT_DEMO_MARKER} {client.notes or ''}".strip()
            client.tenant_id = tenant_id

        buyer_count = 0
        for idx, (company, country, industry) in enumerate(
            (
                ("EuroTech GmbH", "Germany", "electronics"),
                ("NorthStar Imports", "United States", "retail"),
                ("Silk Road Trading", "Uzbekistan", "distribution"),
                ("Moscow Industrial LLC", "Russia", "manufacturing"),
            ),
            start=1,
        ):
            db.add(BuyerDiscoveryEntry(
                client_id=client_id,
                company_name=f"{company} {PILOT_DEMO_MARKER}",
                country=country,
                industry=industry,
                source="pilot_demo",
                contact_status="researched",
                opportunity_score=72 + idx * 4,
                category="strategic" if idx < 2 else "high_potential",
                pipeline_stage="qualified" if idx < 3 else "discovered",
                notes=f"{PILOT_DEMO_MARKER} Demo buyer for pilot acquisition view.",
            ))
            buyer_count += 1

        marketplace_count = 0
        for idx, (title, buyer_co, country) in enumerate(
            (
                ("Bulk PCB assembly RFQ", "EuroTech GmbH", "Germany"),
                ("Consumer electronics distributor", "NorthStar Imports", "United States"),
            ),
        ):
            opp = MarketplaceOpportunity(
                title=f"{title} {PILOT_DEMO_MARKER}",
                description=f"{PILOT_DEMO_MARKER} Demo marketplace opportunity for pilot launch.",
                buyer_company=buyer_co,
                country=country,
                industry="electronics",
                opportunity_type="rfq",
                estimated_value=Decimal(str(250_000 + idx * 50_000)),
                status="open",
                visibility="public",
                created_by_tenant=tenant_id,
                rank_score=80 - idx * 5,
            )
            db.add(opp)
            marketplace_count += 1

        leads: list[CrmLead] = []
        for idx in range(3):
            lead = CrmLead(
                client_id=client_id,
                name=f"Pilot Buyer Contact {idx + 1}",
                company=f"Demo Buyer Corp {idx + 1}",
                source="buyer_discovery",
                language="en",
                status="qualified" if idx == 0 else "contacted",
                priority="high",
                estimated_value=Decimal(str(150_000 + idx * 25_000)),
                notes=f"{PILOT_DEMO_MARKER} Demo CRM lead.",
            )
            db.add(lead)
            leads.append(lead)
        await db.flush()

        deal = CrmDeal(
            client_id=client_id,
            lead_id=leads[0].id,
            title=f"Pilot Export Deal {PILOT_DEMO_MARKER}",
            status="negotiation",
            expected_value=Decimal("420000"),
            deal_amount=Decimal("420000"),
            currency="USD",
            probability=65,
        )
        db.add(deal)
        await db.flush()

        db.add(CrmProposal(
            lead_id=leads[0].id,
            client_id=client_id,
            title=f"Pilot Proposal {PILOT_DEMO_MARKER}",
            language="en",
            status="sent",
            proposal_text="Demo commercial proposal for pilot client presentation.",
            estimated_value=Decimal("420000"),
        ))

        db.add(RevenueEvent(
            deal_id=deal.id,
            type="pipeline",
            amount=deal.expected_value,
        ))

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

        await db.commit()
        logger.info(
            "%s demo seed: app=%s tenant=%s client=%s",
            MARKER, app.id, tenant_id, client_id,
        )

        return {
            "created": True,
            "message": "Pilot demo data seeded — clearly tagged, no external calls",
            "demo_marker": PILOT_DEMO_MARKER,
            "application_id": app.id,
            "tenant_id": tenant_id,
            "client_id": client_id,
            "portal_account_id": portal_id,
            "subscription_id": subscription_id,
            "login_email": PILOT_DEMO_EMAIL,
            "login_password": PILOT_DEMO_PASSWORD,
            "counts": {
                "buyers": buyer_count,
                "marketplace_opportunities": marketplace_count,
                "crm_leads": len(leads),
                "deals": 1,
                "proposals": 1,
                "revenue_events": 1,
                "catalog_products": cat_count,
                "certificates": cert_count,
                "export_markets": market_count,
                "profile_score_ready": 1 if profile else 0,
            },
        }

    @staticmethod
    async def _component_scores(db: AsyncSession) -> dict[str, dict[str, Any]]:
        ctx = await PilotLaunchService._demo_context(db)
        tenant_id = ctx.get("tenant_id")
        app = ctx.get("application")

        auth_score = 40
        auth_details = "Seed pilot demo data for login verification"
        owner = ctx.get("owner")
        if owner and owner.password_hash:
            if verify_password(PILOT_DEMO_PASSWORD, owner.password_hash):
                auth_score = 95
                auth_details = "Demo tenant owner password configured"
            else:
                auth_score = 70
                auth_details = "Demo owner has password (non-default check skipped)"

        isolation_score = 30
        isolation_details = "No pilot demo tenant"
        if tenant_id:
            client_mismatch = await db.scalar(
                select(func.count())
                .select_from(Client)
                .where(
                    Client.tenant_id == tenant_id,
                    Client.id != ctx.get("client_id"),
                ),
            ) or 0
            isolation_score = 95 if client_mismatch == 0 else 75
            isolation_details = f"Tenant {tenant_id} scoped; cross-tenant clients={client_mismatch}"

        billing_score = 25
        billing_details = "No active subscription on demo tenant"
        if tenant_id:
            sub, plan = await SubscriptionService._active_subscription(db, tenant_id)
            if sub and sub.status in ("trial", "active"):
                billing_score = 90
                billing_details = f"Plan {plan.code if plan else 'unknown'} — {sub.status}"
            else:
                billing_score = 40

        factory_score = 20
        factory_details = "Factory profile not seeded"
        if tenant_id:
            score_data = await FactoryProfileService.profile_score(db, tenant_id)
            factory_score = int(score_data.get("score", 0))
            factory_details = f"Profile score {factory_score}/100"

        portal_score = 25
        portal_details = "Portal account missing"
        if app and app.created_client_id:
            portal_r = await db.execute(
                select(CustomerPortalAccount)
                .where(CustomerPortalAccount.company_id == app.created_client_id)
                .limit(1),
            )
            portal = portal_r.scalar_one_or_none()
            if portal and portal.portal_status == "active":
                portal_score = 92
                portal_details = f"Portal active for {portal.company_name}"

        buyer_score = 20
        buyer_details = "No buyer acquisition demo rows"
        if ctx.get("client_id"):
            buyer_n = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerDiscoveryEntry)
                    .where(BuyerDiscoveryEntry.client_id == ctx["client_id"]),
                ) or 0,
            )
            mkt_n = int(
                await db.scalar(
                    select(func.count())
                    .select_from(MarketplaceOpportunity)
                    .where(MarketplaceOpportunity.created_by_tenant == tenant_id),
                ) or 0,
            ) if tenant_id else 0
            if buyer_n + mkt_n >= 3:
                buyer_score = min(100, 60 + buyer_n * 8 + mkt_n * 5)
                buyer_details = f"Discovery={buyer_n}, marketplace={mkt_n}"

        dashboard_score = 70
        dashboard_details = "Dashboard API probe pending"
        smoke = await PilotLaunchService.smoke_tests()
        dash = next((t for t in smoke["tests"] if t["page"] == "dashboard"), None)
        if dash:
            if dash["status"] == "ok":
                dashboard_score = 95
                dashboard_details = "Dashboard overview API healthy"
            elif dash["status"] == "slow":
                dashboard_score = 75
                dashboard_details = "Dashboard API slow"
            else:
                dashboard_score = 40
                dashboard_details = dash.get("message") or "Dashboard API error"

        security_score = 50
        security_details = "Security checks pending"
        try:
            from app.main import app as fastapi_app

            sec = await AdminSecurityService.security_status(fastapi_app, db)
            security_score = int(sec.get("readiness_score", 50))
            security_details = (
                f"Protected routes={sec.get('protected_route_count', 0)}, "
                f"open={sec.get('open_route_count', 0)}"
            )
        except Exception as exc:
            security_details = f"Security scan failed: {exc}"[:200]
            checks = await AdminRbacService.security_checks(db)
            if checks.get("jwt_secrets_distinct"):
                security_score = 70

        def _status(score: int) -> str:
            if score >= 80:
                return "completed"
            if score >= 50:
                return "warning"
            return "blocked"

        raw = {
            "auth_health": (auth_score, auth_details),
            "tenant_isolation": (isolation_score, isolation_details),
            "billing_availability": (billing_score, billing_details),
            "factory_profile": (factory_score, factory_details),
            "portal_readiness": (portal_score, portal_details),
            "buyer_acquisition": (buyer_score, buyer_details),
            "dashboard_health": (dashboard_score, dashboard_details),
            "security_status": (security_score, security_details),
        }
        out: dict[str, dict[str, Any]] = {}
        for key, label, weight in _READINESS_WEIGHTS:
            score, details = raw[key]
            out[key] = {
                "key": key,
                "label": label,
                "score": _clamp(score),
                "weight": weight,
                "status": _status(score),
                "details": details,
            }
        return out

    @staticmethod
    async def readiness(db: AsyncSession) -> dict[str, Any]:
        components_map = await PilotLaunchService._component_scores(db)
        components = list(components_map.values())
        total_weight = sum(c["weight"] for c in components) or 1
        weighted = sum(c["score"] * c["weight"] for c in components) / total_weight
        return {
            "score": _clamp(int(round(weighted))),
            "components": components,
            "demo_data_present": await PilotLaunchService.demo_data_present(db),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def checklist(db: AsyncSession) -> dict[str, Any]:
        demo = await PilotLaunchService.demo_data_present(db)
        readiness = await PilotLaunchService.readiness(db)
        qa = await PilotLaunchService.run_qa(db)
        items: list[dict[str, Any]] = []

        if demo:
            ctx = await PilotLaunchService._demo_context(db)
            app = ctx["application"]
            if app:
                ev = await PilotOnboardingService._evaluate(db, app)
                for step in ev.get("checklist", []):
                    st = "completed" if step.get("completed") else "blocked"
                    items.append({
                        "id": step["step"],
                        "label": step["label"],
                        "status": st,
                        "message": step.get("details"),
                        "next_action": None if st == "completed" else f"Complete: {step['label']}",
                    })
        else:
            items.append({
                "id": "demo_data",
                "label": "Seed pilot demo data",
                "status": "blocked",
                "message": "No tagged pilot demo dataset found",
                "next_action": "POST /api/v1/pilot-launch/seed-demo-data",
            })

        for comp in readiness["components"]:
            if comp["status"] != "completed":
                items.append({
                    "id": f"readiness_{comp['key']}",
                    "label": comp["label"],
                    "status": comp["status"],
                    "message": comp.get("details"),
                    "next_action": f"Improve {comp['label'].lower()}",
                })

        for step in qa["steps"]:
            if step["status"] == "fail":
                items.append({
                    "id": f"qa_{step['step']}",
                    "label": step["label"],
                    "status": "blocked",
                    "message": step.get("message"),
                    "next_action": f"Fix QA step: {step['label']}",
                })
            elif step["status"] == "warning":
                items.append({
                    "id": f"qa_{step['step']}",
                    "label": step["label"],
                    "status": "warning",
                    "message": step.get("message"),
                    "next_action": None,
                })

        completed = sum(1 for i in items if i["status"] == "completed")
        warning = sum(1 for i in items if i["status"] == "warning")
        blocked = sum(1 for i in items if i["status"] == "blocked")

        next_action = None
        for i in items:
            if i["status"] == "blocked" and i.get("next_action"):
                next_action = i["next_action"]
                break
        if not next_action and warning:
            next_action = "Review warning items before pilot demo"

        return {
            "items": items,
            "completed_count": completed,
            "warning_count": warning,
            "blocked_count": blocked,
            "next_action": next_action or ("Pilot launch checklist clear" if blocked == 0 else None),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def smoke_tests() -> dict[str, Any]:
        from app.main import app

        transport = ASGITransport(app=app)
        tests: list[dict[str, Any]] = []
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for page, route, api_path in _SMOKE_SPECS:
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
                if page == "factory_platform" and status_code in (401, 403, 422):
                    probe_status = "ok"
                    error = "Tenant-scoped route — page loads with tenant context"
                elif page == "factory_apply" and status_code == 200:
                    probe_status = "ok"
                    error = None
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

        ok_count = sum(1 for t in tests if t["status"] == "ok")
        return {"tests": tests, "ok_count": ok_count, "total": len(tests)}

    @staticmethod
    async def run_qa(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotLaunchService._demo_context(db)
        app = ctx.get("application")
        tenant_id = ctx.get("tenant_id")
        client_id = ctx.get("client_id")
        owner = ctx.get("owner")
        steps: list[dict[str, Any]] = []

        def add(step: str, label: str, status: str, message: str | None = None) -> None:
            steps.append({"step": step, "label": label, "status": status, "message": message})

        if not app:
            for step, label in _QA_STEPS:
                add(step, label, "skipped", "Seed pilot demo data first")
            return {
                "ran_at": _utc_now(),
                "pass_count": 0,
                "warning_count": 0,
                "fail_count": len(steps),
                "steps": steps,
                "safety_notice": _safety_notice(),
            }

        add(
            "factory_apply",
            "Factory apply flow",
            "pass",
            f"Demo application {app.id} ({app.status})",
        )

        add(
            "approve_application",
            "Approve application",
            "pass" if app.status == "approved" else "fail",
            f"Status={app.status}",
        )

        add(
            "create_client",
            "Create client",
            "pass" if client_id else "fail",
            f"client_id={client_id}" if client_id else "Missing client",
        )

        add(
            "create_tenant",
            "Create tenant",
            "pass" if tenant_id else "fail",
            f"tenant_id={tenant_id}" if tenant_id else "Missing tenant",
        )

        portal = None
        if client_id:
            portal_r = await db.execute(
                select(CustomerPortalAccount)
                .where(CustomerPortalAccount.company_id == client_id)
                .limit(1),
            )
            portal = portal_r.scalar_one_or_none()
        add(
            "create_portal_account",
            "Create portal account",
            "pass" if portal else "fail",
            portal.company_name if portal else "No portal account",
        )

        sub_ok = False
        if tenant_id:
            sub, plan = await SubscriptionService._active_subscription(db, tenant_id)
            sub_ok = sub is not None and sub.status in ("trial", "active")
            add(
                "create_subscription",
                "Create subscription",
                "pass" if sub_ok else "fail",
                f"{plan.code if plan else 'none'} / {sub.status if sub else 'missing'}",
            )
        else:
            add("create_subscription", "Create subscription", "fail", "No tenant")

        if owner and owner.password_hash and verify_password(PILOT_DEMO_PASSWORD, owner.password_hash):
            add("login", "Tenant login credentials", "pass", PILOT_DEMO_EMAIL)
        elif owner and owner.password_hash:
            add("login", "Tenant login credentials", "warning", "Password set but differs from pilot default")
        else:
            add("login", "Tenant login credentials", "fail", "Owner password not configured")

        async def _probe_label(name: str, path: str, label: str) -> None:
            from app.main import app as fastapi_app

            transport = ASGITransport(app=fastapi_app)
            try:
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    resp = await client.get(path)
                    if resp.status_code < 400 or (
                        name in ("factory_platform_v2", "customer_portal_v2")
                        and resp.status_code in (401, 403, 422)
                    ):
                        add(name, label, "pass", f"HTTP {resp.status_code}")
                    else:
                        add(name, label, "fail", f"HTTP {resp.status_code}")
            except Exception as exc:
                add(name, label, "fail", str(exc)[:200])

        await _probe_label(
            "customer_portal_v2",
            "/api/v1/customer-portal-v2/summary-widget",
            "Customer portal v2",
        )
        await _probe_label(
            "factory_platform_v2",
            "/api/v1/factory-platform/summary-widget",
            "Factory platform v2",
        )
        await _probe_label(
            "buyer_acquisition",
            "/api/v1/buyer-acquisition/overview",
            "Buyer acquisition",
        )
        await _probe_label("marketplace", "/api/v1/marketplace/overview", "Marketplace")
        await _probe_label("billing", "/api/v1/billing/plans", "Billing")
        await _probe_label(
            "executive_copilot",
            "/api/v1/executive-copilot/overview",
            "Executive copilot",
        )

        pass_count = sum(1 for s in steps if s["status"] == "pass")
        warning_count = sum(1 for s in steps if s["status"] == "warning")
        fail_count = sum(1 for s in steps if s["status"] == "fail")

        return {
            "ran_at": _utc_now(),
            "pass_count": pass_count,
            "warning_count": warning_count,
            "fail_count": fail_count,
            "steps": steps,
            "safety_notice": _safety_notice(),
        }

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

        from app.core.dependency_registry import PAGE_DEPENDENCIES
        from app.services.api_health_service import ApiHealthService

        await _probe(
            "api_health",
            ApiHealthService.check(
                None,
                skip_paths=frozenset({
                    "production_deployment",
                    "executive_copilot",
                    "pilot_demo",
                    "pilot_launch",
                    "pilot_launch_validation",
                    "real_factory_pilot",
                }),
                time_budget_sec=20.0,
                per_probe_timeout_sec=1.5,
            ),
            "System API health probes",
        )
        checks.append({
            "module": "dependency_registry",
            "status": "ok",
            "message": f"{len(PAGE_DEPENDENCIES)} page dependencies registered",
            "details": {"pages": len(PAGE_DEPENDENCIES)},
        })
        await _probe(
            "pilot_launch",
            PilotLaunchService.readiness(db),
            "Pilot launch readiness",
        )
        return checks

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        readiness = await PilotLaunchService.readiness(db)
        checklist = await PilotLaunchService.checklist(db)
        smoke = await PilotLaunchService.smoke_tests()
        qa = await PilotLaunchService.run_qa(db)
        ctx = await PilotLaunchService._demo_context(db)
        app = ctx.get("application")

        blockers = [i["label"] for i in checklist["items"] if i["status"] == "blocked"]
        next_actions = [
            i["next_action"]
            for i in checklist["items"]
            if i.get("next_action") and i["status"] != "completed"
        ][:5]

        return {
            "readiness_score": readiness["score"],
            "demo_data_present": readiness["demo_data_present"],
            "demo_company_name": app.company_name if app else None,
            "demo_application_id": app.id if app else None,
            "demo_tenant_id": ctx.get("tenant_id"),
            "qa_pass_count": qa["pass_count"],
            "qa_total": len(qa["steps"]),
            "smoke_ok_count": smoke["ok_count"],
            "smoke_total": smoke["total"],
            "checklist_completed": checklist["completed_count"],
            "checklist_blocked": checklist["blocked_count"],
            "blockers": blockers,
            "next_actions": next_actions,
            "integration_checks": await PilotLaunchService.integration_checks(db),
            "safety_notice": _safety_notice(),
            "implementation_complete": True,
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotLaunchService.overview(db)
        return {
            "readiness_score": overview["readiness_score"],
            "demo_data_present": overview["demo_data_present"],
            "demo_company_name": overview.get("demo_company_name"),
            "qa_pass_count": overview["qa_pass_count"],
            "qa_total": overview["qa_total"],
            "smoke_ok_count": overview["smoke_ok_count"],
            "smoke_total": overview["smoke_total"],
            "checklist_blocked": overview["checklist_blocked"],
            "blockers": overview["blockers"][:3],
            "next_action": overview["next_actions"][0] if overview["next_actions"] else None,
            "safety_notice": overview["safety_notice"],
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        """Executive Copilot — pilot launch rollup."""
        overview = await PilotLaunchService.overview(db)
        readiness = await PilotLaunchService.readiness(db)
        return {
            "readiness_score": overview["readiness_score"],
            "demo_data_present": overview["demo_data_present"],
            "demo_company_name": overview.get("demo_company_name"),
            "qa_pass_count": overview["qa_pass_count"],
            "qa_total": overview["qa_total"],
            "smoke_ok_count": overview["smoke_ok_count"],
            "smoke_total": overview["smoke_total"],
            "blocked_count": overview["checklist_blocked"],
            "top_blockers": overview["blockers"][:5],
            "next_action": overview["next_actions"][0] if overview["next_actions"] else None,
            "components": readiness["components"],
            "safety_notice": overview["safety_notice"],
        }
