"""First Real Factory Pilot v1 — operational execution workspace (read-only + guided hints)."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from httpx import ASGITransport, AsyncClient

from app.core.database import db_probe_slot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.models.buyer_network import BuyerRelationship
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.factory_profile import FactoryCatalogProduct, FactoryCertificate, FactoryExportMarket
from app.models.marketplace import MarketplaceOpportunityClaim, MarketplaceOpportunityInterest
from app.services.admin_rbac_service import AdminRbacService
from app.services.admin_security_service import AdminSecurityService
from app.services.factory_profile_service import FactoryProfileService
from app.services.first_pilot_client_service import FirstPilotClientService, _is_demo_application
from app.services.pilot_launch_service import PILOT_DEMO_MARKER
from app.services.pilot_onboarding_service import PilotOnboardingService
from app.services.production_deployment_service import ProductionDeploymentService

logger = logging.getLogger(__name__)

MARKER = "[Real Factory Pilot]"

CHECKLIST_STEPS: tuple[tuple[str, str], ...] = (
    ("choose_real_factory", "Choose real factory"),
    ("verify_company_info", "Verify company info"),
    ("approve_application", "Approve application"),
    ("create_client", "Create client"),
    ("create_tenant", "Create tenant"),
    ("create_subscription", "Create subscription"),
    ("create_admin_user", "Create admin user"),
    ("complete_factory_profile", "Complete factory profile"),
    ("add_products", "Add products"),
    ("add_certificates", "Add certificates"),
    ("configure_export_markets", "Configure export markets"),
    ("seed_initial_buyer_opportunities", "Seed initial buyer opportunities"),
    ("verify_customer_portal", "Verify customer portal"),
    ("verify_factory_platform", "Verify factory platform"),
    ("verify_billing", "Verify billing"),
    ("verify_admin_access", "Verify admin access"),
    ("pilot_ready", "Pilot ready"),
)

TOTAL_STEPS = len(CHECKLIST_STEPS)

_READINESS_WEIGHTS: tuple[tuple[str, str, int], ...] = (
    ("company_readiness", "Company readiness", 15),
    ("tenant_readiness", "Tenant readiness", 15),
    ("security_readiness", "Security readiness", 10),
    ("billing_readiness", "Billing readiness", 10),
    ("portal_readiness", "Portal readiness", 10),
    ("factory_profile_readiness", "Factory profile readiness", 15),
    ("buyer_acquisition_readiness", "Buyer acquisition readiness", 10),
    ("deployment_readiness", "Deployment readiness", 15),
)

_ACTION_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("open_factory_partners", "Open Factory Partners", "Review and manage factory applications.", "/factory-partners"),
    ("open_tenants", "Open Tenants", "Manage tenant workspace and isolation.", "/tenants"),
    ("open_billing", "Open Billing", "Configure subscription and billing plan.", "/billing"),
    ("open_admin_users", "Open Admin Users", "Manage tenant owner and manager users.", "/tenant-users"),
    ("open_factory_platform", "Open Factory Platform", "Complete factory profile, catalog, and markets.", "/factory-platform"),
    ("open_customer_portal_v2", "Open Customer Portal v2", "Verify customer-facing portal experience.", "/customer-portal-v2"),
    ("open_buyer_acquisition", "Open Buyer Acquisition", "Review buyer pipeline and opportunities.", "/buyer-acquisition"),
    ("open_production_deployment", "Open Production Deployment", "Review production readiness before go-live.", "/production-deployment"),
)

_PROFILE_MIN_SCORE = 50
_HEAVY_SECTION_TIMEOUT = 10.0
_PROBE_TIMEOUT = 1.5


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Read-only real factory pilot — no automatic approval, tenant creation, subscription "
        "creation, user creation, or messaging. Guided admin action hints only."
    )


def _readiness_status(score: int) -> str:
    if score >= 80:
        return "ready"
    if score >= 50:
        return "warning"
    return "blocked"


class RealFactoryPilotService:
    @staticmethod
    async def _resolve_factory(db: AsyncSession) -> FactoryPartnerApplication | None:
        return await FirstPilotClientService._resolve_pilot_client(db)

    @staticmethod
    async def _catalog_count(db: AsyncSession, tenant_id: UUID | None) -> int:
        if not tenant_id:
            return 0
        return int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryCatalogProduct)
                .where(FactoryCatalogProduct.tenant_id == tenant_id),
            ) or 0,
        )

    @staticmethod
    async def _certificate_count(db: AsyncSession, tenant_id: UUID | None) -> int:
        if not tenant_id:
            return 0
        return int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryCertificate)
                .where(FactoryCertificate.tenant_id == tenant_id),
            ) or 0,
        )

    @staticmethod
    async def _export_market_count(db: AsyncSession, tenant_id: UUID | None) -> int:
        if not tenant_id:
            return 0
        return int(
            await db.scalar(
                select(func.count())
                .select_from(FactoryExportMarket)
                .where(FactoryExportMarket.tenant_id == tenant_id),
            ) or 0,
        )

    @staticmethod
    async def _buyer_opportunity_count(db: AsyncSession, tenant_id: UUID | None) -> int:
        if not tenant_id:
            return 0
        return int(
            await db.scalar(
                select(func.count())
                .select_from(BuyerRelationship)
                .where(BuyerRelationship.tenant_id == tenant_id),
            ) or 0,
        )

    @staticmethod
    async def _marketplace_activity_count(db: AsyncSession, tenant_id: UUID | None) -> int:
        if not tenant_id:
            return 0
        interests = int(
            await db.scalar(
                select(func.count())
                .select_from(MarketplaceOpportunityInterest)
                .where(MarketplaceOpportunityInterest.tenant_id == tenant_id),
            ) or 0,
        )
        claims = int(
            await db.scalar(
                select(func.count())
                .select_from(MarketplaceOpportunityClaim)
                .where(MarketplaceOpportunityClaim.tenant_id == tenant_id),
            ) or 0,
        )
        return interests + claims

    @staticmethod
    async def _api_probe(path: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            from app.main import app as fastapi_app

            transport = ASGITransport(app=fastapi_app)

            async def _run() -> Any:
                async with db_probe_slot():
                    async with AsyncClient(transport=transport, base_url="http://test") as client:
                        return await client.get(path)

            response = await asyncio.wait_for(_run(), timeout=_PROBE_TIMEOUT)
            duration_ms = int((time.perf_counter() - started) * 1000)
            ok = response.status_code < 400
            return {
                "ok": ok,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "slow": duration_ms >= SLOW_THRESHOLD_MS,
                "message": None if ok else f"HTTP {response.status_code}",
            }
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "status_code": None,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "slow": True,
                "message": f"Probe timed out after {_PROBE_TIMEOUT:.1f}s",
            }
        except Exception as exc:
            return {
                "ok": False,
                "status_code": None,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "slow": False,
                "message": str(exc)[:200],
            }

    @staticmethod
    async def _deployment_context(db: AsyncSession) -> dict[str, Any]:
        default = {
            "readiness_score": 0,
            "deployment_ready": False,
            "blockers": [],
            "warnings": [],
        }
        try:
            summary = await asyncio.wait_for(
                ProductionDeploymentService.executive_summary(db),
                timeout=_HEAVY_SECTION_TIMEOUT,
            )
            return {
                "readiness_score": int(summary.get("production_readiness_score") or 0),
                "deployment_ready": bool(summary.get("deployment_ready")),
                "blockers": [
                    {"label": b.get("label", "Blocker"), "message": b.get("message", str(b))}
                    for b in (summary.get("top_blockers") or [])
                ],
                "warnings": [],
            }
        except Exception as exc:
            logger.info("%s deployment context skip err=%s", MARKER, exc)
            return default

    @staticmethod
    async def _security_context(db: AsyncSession) -> dict[str, Any]:
        default = {
            "readiness_score": 0,
            "critical_findings": [],
            "warnings": [],
            "open_route_count": 0,
        }
        try:
            from app.main import app as fastapi_app

            status = await asyncio.wait_for(
                AdminSecurityService.security_status(fastapi_app, db),
                timeout=_HEAVY_SECTION_TIMEOUT,
            )
            return {
                "readiness_score": int(status.get("readiness_score") or 0),
                "critical_findings": status.get("critical_findings") or [],
                "warnings": status.get("warnings") or [],
                "open_route_count": int(status.get("open_route_count") or 0),
            }
        except Exception as exc:
            logger.info("%s security context skip err=%s", MARKER, exc)
            try:
                checks = await asyncio.wait_for(
                    AdminRbacService.security_checks(db),
                    timeout=1.0,
                )
                score = 50 if int(checks.get("ok_count") or 0) >= 4 else 30
                return {**default, "readiness_score": score}
            except Exception:
                return default

    @staticmethod
    async def _build_context(db: AsyncSession) -> dict[str, Any]:
        app = await RealFactoryPilotService._resolve_factory(db)
        deployment, security = await asyncio.gather(
            RealFactoryPilotService._deployment_context(db),
            RealFactoryPilotService._security_context(db),
        )

        if not app:
            return {
                "application": None,
                "onboarding": None,
                "tenant_id": None,
                "client_id": None,
                "company_name": None,
                "portal": None,
                "subscription": None,
                "owner": None,
                "profile_score_data": None,
                "catalog_count": 0,
                "certificate_count": 0,
                "export_market_count": 0,
                "buyer_opportunity_count": 0,
                "marketplace_activity_count": 0,
                "deployment": deployment,
                "security": security,
            }

        onboarding = await PilotOnboardingService._evaluate(db, app)
        tenant_id = app.tenant_id
        portal = await PilotOnboardingService._portal_account(db, app)
        subscription = await PilotOnboardingService._active_subscription(db, tenant_id)
        owner = await PilotOnboardingService._owner_user(db, tenant_id)

        profile_score_data = None
        if tenant_id:
            try:
                profile_score_data = await FactoryProfileService.profile_score(db, tenant_id)
            except Exception as exc:
                logger.info("%s profile score skip tenant=%s err=%s", MARKER, tenant_id, exc)

        return {
            "application": app,
            "onboarding": onboarding,
            "tenant_id": tenant_id,
            "client_id": app.created_client_id,
            "company_name": app.company_name,
            "portal": portal,
            "subscription": subscription,
            "owner": owner,
            "profile_score_data": profile_score_data or {},
            "catalog_count": await RealFactoryPilotService._catalog_count(db, tenant_id),
            "certificate_count": await RealFactoryPilotService._certificate_count(db, tenant_id),
            "export_market_count": await RealFactoryPilotService._export_market_count(db, tenant_id),
            "buyer_opportunity_count": await RealFactoryPilotService._buyer_opportunity_count(db, tenant_id),
            "marketplace_activity_count": await RealFactoryPilotService._marketplace_activity_count(db, tenant_id),
            "deployment": deployment,
            "security": security,
        }

    @staticmethod
    def _workspace(ctx: dict[str, Any]) -> dict[str, Any]:
        app = ctx["application"]
        owner = ctx.get("owner")
        subscription = ctx.get("subscription")
        profile_data = ctx.get("profile_score_data") or {}
        return {
            "application_id": app.id if app else None,
            "company_name": ctx.get("company_name"),
            "client_id": ctx.get("client_id"),
            "tenant_id": ctx.get("tenant_id"),
            "subscription_status": subscription.status if subscription else None,
            "admin_user_email": owner.email if owner else None,
            "factory_profile_score": int(profile_data.get("profile_score") or 0),
            "catalog_count": ctx.get("catalog_count", 0),
            "certificate_count": ctx.get("certificate_count", 0),
            "export_market_count": ctx.get("export_market_count", 0),
            "buyer_opportunity_count": ctx.get("buyer_opportunity_count", 0),
            "marketplace_activity_count": ctx.get("marketplace_activity_count", 0),
            "factory_identified": app is not None,
        }

    @staticmethod
    async def _checklist_items(db: AsyncSession, ctx: dict[str, Any]) -> list[dict[str, Any]]:
        app = ctx["application"]
        onboarding = ctx.get("onboarding") or {}
        tenant_id = ctx.get("tenant_id")
        tenant_q = f"?tenant_id={tenant_id}" if tenant_id else ""
        profile_score = int((ctx.get("profile_score_data") or {}).get("profile_score") or 0)

        if not app:
            return [
                {
                    "step": step,
                    "label": label,
                    "completed": False,
                    "status": "pending",
                    "completed_at": None,
                    "details": "Select a real factory application first",
                }
                for step, label in CHECKLIST_STEPS
            ]

        portal_path = (
            f"/api/v1/customer-portal-v2/summary-widget{tenant_q}"
            if tenant_id
            else "/api/v1/customer-portal-v2/summary-widget"
        )
        factory_path = (
            f"/api/v1/factory-platform/summary-widget{tenant_q}"
            if tenant_id
            else "/api/v1/factory-platform/summary-widget"
        )
        portal_probe = await RealFactoryPilotService._api_probe(portal_path)
        factory_probe = await RealFactoryPilotService._api_probe(factory_path)
        billing_probe = await RealFactoryPilotService._api_probe("/api/v1/billing/summary-widget")

        company_verified = bool(
            app.company_name
            and (app.contact_email or app.contact_name)
            and (app.country or app.industry),
        )
        portal = ctx.get("portal")
        subscription = ctx.get("subscription")
        owner = ctx.get("owner")

        step_values = {
            "choose_real_factory": True,
            "verify_company_info": company_verified,
            "approve_application": app.status == "approved",
            "create_client": app.created_client_id is not None,
            "create_tenant": tenant_id is not None,
            "create_subscription": subscription is not None,
            "create_admin_user": owner is not None,
            "complete_factory_profile": profile_score >= _PROFILE_MIN_SCORE,
            "add_products": ctx.get("catalog_count", 0) > 0,
            "add_certificates": ctx.get("certificate_count", 0) > 0,
            "configure_export_markets": ctx.get("export_market_count", 0) > 0,
            "seed_initial_buyer_opportunities": ctx.get("buyer_opportunity_count", 0) > 0,
            "verify_customer_portal": bool(portal and portal.portal_status == "active" and portal_probe["ok"]),
            "verify_factory_platform": factory_probe["ok"] and profile_score >= 30,
            "verify_billing": bool(
                subscription and subscription.status in ("trial", "active") and billing_probe["ok"],
            ),
            "verify_admin_access": owner is not None,
        }
        pre_pilot = all(step_values[k] for k in step_values if k != "pilot_ready")
        deployment = ctx.get("deployment") or {}
        step_values["pilot_ready"] = pre_pilot and int(deployment.get("readiness_score") or 0) >= 60

        items: list[dict[str, Any]] = []
        for step, label in CHECKLIST_STEPS:
            completed = step_values[step]
            status = "completed" if completed else ("blocked" if app.status == "rejected" else "pending")
            details = None
            completed_at = None
            if step == "verify_company_info" and company_verified:
                details = f"{app.country or '—'} · {app.industry or '—'}"
            elif step == "complete_factory_profile":
                details = f"Profile score {profile_score}/100"
            elif step == "add_products" and ctx.get("catalog_count"):
                details = f"{ctx['catalog_count']} product(s)"
            elif step == "add_certificates" and ctx.get("certificate_count"):
                details = f"{ctx['certificate_count']} certificate(s)"
            elif step == "configure_export_markets" and ctx.get("export_market_count"):
                details = f"{ctx['export_market_count']} market(s)"
            elif step == "seed_initial_buyer_opportunities":
                details = f"{ctx.get('buyer_opportunity_count', 0)} buyer relationship(s)"
            elif step == "verify_customer_portal" and portal:
                details = f"Portal {portal.portal_status}"
            elif step == "verify_billing" and subscription:
                details = f"Subscription {subscription.status}"
            elif step == "create_admin_user" and owner:
                details = owner.email
                completed_at = owner.created_at
            elif step == "approve_application" and app.reviewed_at:
                completed_at = app.reviewed_at
            items.append({
                "step": step,
                "label": label,
                "completed": completed,
                "status": status,
                "completed_at": completed_at,
                "details": details,
            })

        return items

    @staticmethod
    async def _readiness_components(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        app = ctx["application"]
        onboarding = ctx.get("onboarding") or {}
        tenant_id = ctx.get("tenant_id")
        subscription = ctx.get("subscription")
        portal = ctx.get("portal")
        profile_score = int((ctx.get("profile_score_data") or {}).get("profile_score") or 0)
        deployment = ctx.get("deployment") or {}
        security = ctx.get("security") or {}

        if not app:
            components_raw = {key: (0, "No real factory selected") for key, _, _ in _READINESS_WEIGHTS}
        else:
            company_score = 20
            if app.status == "approved":
                company_score = 90 if ctx.get("client_id") else 65
            elif app.status in {"submitted", "under_review"}:
                company_score = 55
            company_details = f"Application {app.status}"

            tenant_score = 85 if tenant_id else 10
            if tenant_id and ctx.get("owner"):
                tenant_score = min(100, tenant_score + 10)
            tenant_details = "Tenant provisioned" if tenant_id else "Tenant not created"

            security_score = int(security.get("readiness_score") or 0)
            security_details = (
                f"Admin security score {security_score}/100"
                if security_score
                else "Security assessment pending"
            )

            billing_score = 15
            billing_details = "No subscription"
            if subscription:
                if subscription.status in ("trial", "active"):
                    billing_score = 95
                    billing_details = f"Subscription {subscription.status}"
                else:
                    billing_score = 40
                    billing_details = f"Subscription {subscription.status}"

            portal_score = 80 if portal and portal.portal_status == "active" else 20
            portal_details = (
                f"Portal {portal.portal_status}"
                if portal
                else "Customer portal account not created"
            )

            profile_data = ctx.get("profile_score_data") or {}
            components = profile_data.get("components") or {}
            if tenant_id and components:
                profile_pts = int(components.get("profile") or 0)
                catalog_pts = int(components.get("products") or 0)
                cert_pts = int(components.get("certificates") or 0)
                market_pts = int(components.get("export_markets") or 0)
                component_blend = _clamp(
                    int(round(
                        profile_pts * 0.35
                        + catalog_pts * 0.25
                        + cert_pts * 0.20
                        + market_pts * 0.20,
                    )),
                )
                factory_score = max(component_blend, profile_score)
                factory_details = (
                    f"Profile {profile_pts}, catalog {catalog_pts}, "
                    f"certs {cert_pts}, markets {market_pts} (total {profile_score}/100)"
                )
            else:
                factory_score = profile_score if tenant_id else 0
                factory_details = (
                    f"Factory profile {profile_score}/100" if tenant_id else "No factory profile"
                )

            buyer_count = ctx.get("buyer_opportunity_count", 0)
            buyer_score = min(100, 25 + buyer_count * 15) if buyer_count else 10
            buyer_details = (
                f"{buyer_count} buyer relationship(s)"
                if buyer_count
                else "Seed buyer opportunities manually"
            )

            deploy_score = int(deployment.get("readiness_score") or 0)
            deploy_details = f"Production deployment {deploy_score}/100"

            if int(onboarding.get("readiness_score") or 0) >= 80 and company_score < 85:
                company_score = min(100, company_score + 5)

            components_raw = {
                "company_readiness": (company_score, company_details),
                "tenant_readiness": (tenant_score, tenant_details),
                "security_readiness": (security_score, security_details),
                "billing_readiness": (billing_score, billing_details),
                "portal_readiness": (portal_score, portal_details),
                "factory_profile_readiness": (factory_score, factory_details),
                "buyer_acquisition_readiness": (buyer_score, buyer_details),
                "deployment_readiness": (deploy_score, deploy_details),
            }

        out: list[dict[str, Any]] = []
        for key, label, weight in _READINESS_WEIGHTS:
            score, details = components_raw[key]
            out.append({
                "key": key,
                "label": label,
                "score": _clamp(score),
                "weight": weight,
                "status": _readiness_status(score),
                "details": details,
            })
        return out

    @staticmethod
    def _build_blockers_and_warnings(ctx: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        app = ctx["application"]
        tenant_id = ctx.get("tenant_id")
        tenant_q = f"?tenant_id={tenant_id}" if tenant_id else ""
        app_q = f"?application={app.id}" if app else ""
        blockers: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if not app:
            blockers.append({
                "blocker": "missing_real_factory_application",
                "label": "Missing real factory application",
                "severity": "critical",
                "message": "Approve a non-demo factory application in Factory Partners.",
                "route_hint": "/factory-partners",
            })
            return blockers, warnings

        if app.status == "rejected":
            blockers.append({
                "blocker": "application_rejected",
                "label": "Application rejected",
                "severity": "critical",
                "message": "Selected factory application was rejected.",
                "route_hint": f"/factory-partners{app_q}",
            })

        if not tenant_id:
            blockers.append({
                "blocker": "missing_tenant",
                "label": "Missing tenant",
                "severity": "critical",
                "message": "Create tenant manually from approved application.",
                "route_hint": f"/factory-partners{app_q}",
            })

        if tenant_id and not ctx.get("subscription"):
            blockers.append({
                "blocker": "missing_subscription",
                "label": "Missing subscription",
                "severity": "critical",
                "message": "Assign billing plan manually — no automatic subscription setup.",
                "route_hint": f"/billing{tenant_q}",
            })

        if tenant_id and not ctx.get("owner"):
            blockers.append({
                "blocker": "missing_admin_user",
                "label": "Missing admin user",
                "severity": "critical",
                "message": "Add tenant owner user before pilot launch.",
                "route_hint": f"/tenant-users{tenant_q}",
            })

        profile_data = ctx.get("profile_score_data") or {}
        profile_score = int(profile_data.get("profile_score") or 0)
        components = profile_data.get("components") or {}
        if tenant_id and profile_score < _PROFILE_MIN_SCORE:
            warnings.append({
                "blocker": "incomplete_profile",
                "label": "Incomplete profile",
                "severity": "warning",
                "message": f"Factory profile score {profile_score}/100 — complete company profile.",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        if tenant_id and int(components.get("products") or 0) < 10:
            warnings.append({
                "blocker": "missing_catalog",
                "label": "Missing catalog",
                "severity": "warning",
                "message": "Add active export-ready products to improve catalog readiness.",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        if tenant_id and int(components.get("certificates") or 0) < 10:
            warnings.append({
                "blocker": "missing_certificates",
                "label": "Missing certificates",
                "severity": "warning",
                "message": "Upload ISO, CE, SGS, FDA, or HALAL certificates.",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        if tenant_id and int(components.get("export_markets") or 0) < 10:
            warnings.append({
                "blocker": "missing_export_markets",
                "label": "Missing export markets",
                "severity": "warning",
                "message": "Define target export markets for buyer matching.",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        deployment = ctx.get("deployment") or {}
        for b in deployment.get("blockers") or []:
            warnings.append({
                "blocker": "production_readiness",
                "label": b.get("label", "Production readiness"),
                "severity": "warning",
                "message": b.get("message", "Production deployment blocker detected."),
                "route_hint": "/production-deployment",
            })
        for w in deployment.get("warnings") or []:
            warnings.append({
                "blocker": "production_readiness_warning",
                "label": w.get("label", "Production warning"),
                "severity": "warning",
                "message": w.get("message", str(w)),
                "route_hint": "/production-deployment",
            })

        security = ctx.get("security") or {}
        for finding in security.get("critical_findings") or []:
            warnings.append({
                "blocker": "security_warning",
                "label": "Security finding",
                "severity": "warning",
                "message": finding if isinstance(finding, str) else str(finding),
                "route_hint": "/admin-audit",
            })
        for finding in security.get("warnings") or []:
            warnings.append({
                "blocker": "security_warning",
                "label": "Security warning",
                "severity": "warning",
                "message": finding if isinstance(finding, str) else str(finding),
                "route_hint": "/admin-audit",
            })

        return blockers, warnings

    @staticmethod
    def _pilot_status(
        ctx: dict[str, Any],
        checklist: list[dict[str, Any]],
        blockers: list[dict[str, Any]],
        readiness_score: int,
    ) -> str:
        app = ctx["application"]
        if not app:
            return "not_started"
        if app.status == "rejected" or any(b["severity"] == "critical" for b in blockers):
            return "blocked"
        if app.status == "draft" and not app.submitted_at:
            return "not_started"

        completed = sum(1 for c in checklist if c["completed"])
        all_complete = completed == TOTAL_STEPS
        deployment_score = int((ctx.get("deployment") or {}).get("readiness_score") or 0)
        deployment_ready = bool((ctx.get("deployment") or {}).get("deployment_ready"))

        if all_complete and deployment_ready:
            return "completed"
        if all_complete or (completed >= TOTAL_STEPS - 1 and readiness_score >= 85):
            return "live_pilot_started"
        if readiness_score >= 80 and not blockers:
            return "ready_for_live_pilot"
        if readiness_score >= 60 and ctx.get("tenant_id"):
            return "ready_for_demo"
        if completed > 0:
            return "in_progress"
        return "not_started"

    @staticmethod
    def _route_hint(action: str, ctx: dict[str, Any]) -> str:
        app = ctx.get("application")
        tenant_id = ctx.get("tenant_id")
        tenant_q = f"?tenant_id={tenant_id}" if tenant_id else ""
        app_q = f"?application={app.id}" if app else ""
        routes = {
            "open_factory_partners": f"/factory-partners{app_q}",
            "open_tenants": f"/tenants{tenant_q}" if tenant_id else "/tenants",
            "open_billing": f"/billing{tenant_q}",
            "open_admin_users": f"/tenant-users{tenant_q}",
            "open_factory_platform": f"/factory-platform{tenant_q}",
            "open_customer_portal_v2": f"/customer-portal-v2{tenant_q}",
            "open_buyer_acquisition": f"/buyer-acquisition{tenant_q}",
            "open_production_deployment": "/production-deployment",
        }
        return routes.get(action, "/real-factory-pilot")

    @staticmethod
    def _guided_actions(ctx: dict[str, Any], blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
        app = ctx.get("application")
        tenant_id = ctx.get("tenant_id")
        actions: list[dict[str, Any]] = []

        availability = {
            "open_factory_partners": True,
            "open_tenants": bool(app),
            "open_billing": bool(tenant_id),
            "open_admin_users": bool(tenant_id),
            "open_factory_platform": bool(tenant_id),
            "open_customer_portal_v2": bool(tenant_id),
            "open_buyer_acquisition": bool(tenant_id),
            "open_production_deployment": True,
        }

        blocker_actions = {
            "missing_real_factory_application": "open_factory_partners",
            "missing_tenant": "open_factory_partners",
            "missing_subscription": "open_billing",
            "missing_admin_user": "open_admin_users",
            "incomplete_profile": "open_factory_platform",
            "missing_catalog": "open_factory_platform",
            "missing_export_markets": "open_factory_platform",
            "production_readiness": "open_production_deployment",
            "security_warning": "open_production_deployment",
        }

        for action, label, description, _default_route in _ACTION_SPECS:
            highlighted = any(
                blocker_actions.get(b["blocker"]) == action for b in blockers
            )
            actions.append({
                "action": action,
                "label": label,
                "description": description,
                "route_hint": RealFactoryPilotService._route_hint(action, ctx),
                "available": availability.get(action, False) or highlighted,
                "manual_only": True,
            })
        return actions

    @staticmethod
    def _next_best_action(
        blockers: list[dict[str, Any]],
        actions: list[dict[str, Any]],
        checklist: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        critical = [b for b in blockers if b["severity"] == "critical"]
        if critical:
            b = critical[0]
            return {
                "title": b["label"],
                "description": b["message"],
                "route_hint": b.get("route_hint"),
                "action": None,
                "priority": "high",
            }
        pending = next((c for c in checklist if not c["completed"]), None)
        if pending:
            action_map = {
                "choose_real_factory": "open_factory_partners",
                "verify_company_info": "open_factory_partners",
                "approve_application": "open_factory_partners",
                "create_client": "open_factory_partners",
                "create_tenant": "open_tenants",
                "create_subscription": "open_billing",
                "create_admin_user": "open_admin_users",
                "complete_factory_profile": "open_factory_platform",
                "add_products": "open_factory_platform",
                "add_certificates": "open_factory_platform",
                "configure_export_markets": "open_factory_platform",
                "seed_initial_buyer_opportunities": "open_buyer_acquisition",
                "verify_customer_portal": "open_customer_portal_v2",
                "verify_factory_platform": "open_factory_platform",
                "verify_billing": "open_billing",
                "verify_admin_access": "open_admin_users",
                "pilot_ready": "open_production_deployment",
            }
            action_key = action_map.get(pending["step"])
            hint = next((a for a in actions if a["action"] == action_key), None)
            return {
                "title": pending["label"],
                "description": pending.get("details") or f"Complete step: {pending['label']}",
                "route_hint": hint["route_hint"] if hint else None,
                "action": action_key,
                "priority": "medium",
            }
        available = next((a for a in actions if a["available"]), None)
        if available:
            return {
                "title": available["label"],
                "description": available["description"],
                "route_hint": available["route_hint"],
                "action": available["action"],
                "priority": "low",
            }
        return None

    @staticmethod
    def _pilot_launch_notes(
        ctx: dict[str, Any],
        status: str,
        readiness_score: int,
        checklist: list[dict[str, Any]],
    ) -> list[str]:
        app = ctx.get("application")
        notes: list[str] = []
        if not app:
            notes.append("Select the first real factory partner — exclude demo-tagged applications.")
            return notes

        completed = sum(1 for c in checklist if c["completed"])
        notes.append(
            f"Tracking {app.company_name} — {completed}/{TOTAL_STEPS} checklist steps complete.",
        )

        if status == "not_started":
            notes.append("Submit and approve the factory application before provisioning tenant resources.")
        elif status == "blocked":
            notes.append("Resolve critical blockers before scheduling a live pilot walkthrough.")
        elif status == "ready_for_demo":
            notes.append("Demo-ready: walk factory owner through Factory Platform and Customer Portal v2.")
        elif status == "ready_for_live_pilot":
            notes.append("Live pilot ready pending final production deployment review.")
        elif status == "live_pilot_started":
            notes.append("Live pilot started — monitor readiness daily and avoid automatic provisioning.")
        elif status == "completed":
            notes.append("Pilot workspace complete — transition to ongoing factory operations support.")

        if readiness_score < 80:
            notes.append(f"Readiness score {readiness_score}% — complete remaining checklist steps manually.")
        deployment = ctx.get("deployment") or {}
        if int(deployment.get("readiness_score") or 0) < 80:
            notes.append("Review Production Deployment dashboard before directing real users to production.")

        notes.append("All actions are manual — no automatic approval, tenant, subscription, or user creation.")
        return notes

    @staticmethod
    async def _assessment(db: AsyncSession) -> dict[str, Any]:
        ctx = await RealFactoryPilotService._build_context(db)
        checklist = await RealFactoryPilotService._checklist_items(db, ctx)
        components = await RealFactoryPilotService._readiness_components(ctx)
        total_weight = sum(c["weight"] for c in components) or 1
        readiness_score = _clamp(
            int(round(sum(c["score"] * c["weight"] for c in components) / total_weight)),
        )
        blockers, warnings = RealFactoryPilotService._build_blockers_and_warnings(ctx)
        status = RealFactoryPilotService._pilot_status(ctx, checklist, blockers, readiness_score)
        actions = RealFactoryPilotService._guided_actions(ctx, blockers + warnings)
        next_best = RealFactoryPilotService._next_best_action(blockers, actions, checklist)
        completed_count = sum(1 for c in checklist if c["completed"])
        pilot_launch_notes = RealFactoryPilotService._pilot_launch_notes(
            ctx, status, readiness_score, checklist,
        )

        return {
            "ctx": ctx,
            "status": status,
            "readiness_score": readiness_score,
            "workspace": RealFactoryPilotService._workspace(ctx),
            "readiness": {
                "score": readiness_score,
                "components": components,
                "factory_identified": ctx.get("application") is not None,
                "company_name": ctx.get("company_name"),
                "application_id": ctx["application"].id if ctx.get("application") else None,
                "tenant_id": ctx.get("tenant_id"),
                "safety_notice": _safety_notice(),
            },
            "checklist": {
                "items": checklist,
                "completed_count": completed_count,
                "total_steps": TOTAL_STEPS,
                "progress_percent": _clamp(int(round(completed_count / TOTAL_STEPS * 100))),
                "company_name": ctx.get("company_name"),
                "application_id": ctx["application"].id if ctx.get("application") else None,
                "safety_notice": _safety_notice(),
            },
            "blockers": blockers,
            "warnings": warnings,
            "actions": actions,
            "next_best_action": next_best,
            "pilot_launch_notes": pilot_launch_notes,
            "critical_blocker_count": sum(1 for b in blockers if b["severity"] == "critical"),
        }

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        async def _probe(module: str, coro: Any, message: str) -> None:
            try:
                await asyncio.wait_for(coro, timeout=1.5)
                checks.append({"module": module, "status": "ok", "message": message, "details": {}})
            except Exception as exc:
                checks.append({
                    "module": module,
                    "status": "degraded",
                    "message": str(exc)[:200],
                    "details": {},
                })

        await _probe(
            "first_pilot_client",
            FirstPilotClientService.summary_widget(db),
            "First pilot client widget reachable",
        )
        await _probe(
            "pilot_onboarding",
            PilotOnboardingService.summary_widget(db),
            "Pilot onboarding widget reachable",
        )
        await _probe(
            "production_deployment",
            ProductionDeploymentService.summary_widget(db),
            "Production deployment widget reachable",
        )
        checks.append({
            "module": "real_factory_pilot",
            "status": "ok",
            "message": "Real factory pilot service active",
            "details": {},
        })
        return checks

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        ctx = data["ctx"]
        app = ctx.get("application")
        return {
            "status": data["status"],
            "readiness_score": data["readiness_score"],
            "factory_identified": app is not None,
            "company_name": ctx.get("company_name"),
            "application_id": app.id if app else None,
            "tenant_id": ctx.get("tenant_id"),
            "client_id": ctx.get("client_id"),
            "blocker_count": len(data["blockers"]),
            "warning_count": len(data["warnings"]),
            "critical_blocker_count": data["critical_blocker_count"],
            "checklist_completed": data["checklist"]["completed_count"],
            "checklist_total": data["checklist"]["total_steps"],
            "workspace": data["workspace"],
            "readiness": data["readiness"],
            "checklist": data["checklist"],
            "blockers": data["blockers"],
            "warnings": data["warnings"],
            "actions": data["actions"],
            "next_best_action": data["next_best_action"],
            "pilot_launch_notes": data["pilot_launch_notes"],
            "integration_checks": await RealFactoryPilotService.integration_checks(db),
            "safety_notice": _safety_notice(),
            "implementation_complete": True,
        }

    @staticmethod
    async def checklist(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        return data["checklist"]

    @staticmethod
    async def blockers(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        ctx = data["ctx"]
        return {
            "blockers": data["blockers"],
            "warnings": data["warnings"],
            "blocker_count": len(data["blockers"]),
            "warning_count": len(data["warnings"]),
            "critical_count": data["critical_blocker_count"],
            "company_name": ctx.get("company_name"),
            "application_id": ctx["application"].id if ctx.get("application") else None,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def actions(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        next_action = next((a for a in data["actions"] if a["available"]), None)
        return {
            "actions": data["actions"],
            "next_action": next_action,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def readiness(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        return data["readiness"]

    @staticmethod
    async def summary(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        return {
            "selected_factory": data["workspace"],
            "status": data["status"],
            "readiness_score": data["readiness_score"],
            "blockers": data["blockers"],
            "warnings": data["warnings"],
            "next_best_action": data["next_best_action"],
            "pilot_launch_notes": data["pilot_launch_notes"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def refresh(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": data["readiness_score"],
            "status": data["status"],
            "blocker_count": len(data["blockers"]),
            "next_best_action": data["next_best_action"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        ctx = data["ctx"]
        next_action = data.get("next_best_action") or {}
        return {
            "readiness_score": data["readiness_score"],
            "status": data["status"],
            "factory_identified": ctx.get("application") is not None,
            "company_name": ctx.get("company_name"),
            "blocker_count": len(data["blockers"]),
            "critical_blocker_count": data["critical_blocker_count"],
            "checklist_progress": data["checklist"]["progress_percent"],
            "next_action_title": next_action.get("title"),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        data = await RealFactoryPilotService._assessment(db)
        ctx = data["ctx"]
        return {
            "readiness_score": data["readiness_score"],
            "status": data["status"],
            "factory_identified": ctx.get("application") is not None,
            "company_name": ctx.get("company_name"),
            "blocker_count": len(data["blockers"]),
            "warning_count": len(data["warnings"]),
            "critical_blocker_count": data["critical_blocker_count"],
            "checklist_progress": data["checklist"]["progress_percent"],
            "next_best_action": data["next_best_action"],
            "top_blockers": data["blockers"][:5],
            "pilot_launch_notes": data["pilot_launch_notes"][:3],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def candidate_indicator(
        db: AsyncSession,
        application_id: UUID,
    ) -> dict[str, Any]:
        app = await db.get(FactoryPartnerApplication, application_id)
        if not app or _is_demo_application(app):
            return {
                "application_id": application_id,
                "is_pilot_candidate": False,
                "is_selected_factory": False,
                "company_name": app.company_name if app else None,
                "readiness_score": 0,
                "status": "not_started",
                "safety_notice": _safety_notice(),
            }

        selected = await RealFactoryPilotService._resolve_factory(db)
        is_selected = selected is not None and selected.id == app.id
        is_candidate = (
            app.status in ("approved", "submitted", "under_review")
            and PILOT_DEMO_MARKER not in (app.company_description or "")
        )
        ev = await PilotOnboardingService._evaluate(db, app)
        data = await RealFactoryPilotService._assessment(db) if is_selected else None

        return {
            "application_id": application_id,
            "is_pilot_candidate": is_candidate,
            "is_selected_factory": is_selected,
            "company_name": app.company_name,
            "readiness_score": data["readiness_score"] if data else int(ev.get("readiness_score") or 0),
            "status": data["status"] if data else "in_progress",
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def is_real_pilot_candidate(db: AsyncSession, application_id: UUID) -> bool:
        result = await RealFactoryPilotService.candidate_indicator(db, application_id)
        return bool(result.get("is_pilot_candidate"))
