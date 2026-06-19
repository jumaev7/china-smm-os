"""Pilot Demo Scenario v1 — guided walkthrough, demo metrics, presentation flow (read-only)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.crm_proposal import CrmProposal
from app.models.marketplace import MarketplaceOpportunity
from app.models.revenue_event import RevenueEvent
from app.services.pilot_launch_service import PILOT_DEMO_MARKER, PilotLaunchService

logger = logging.getLogger(__name__)

MARKER = "[Pilot Demo]"

_SCENARIOS: tuple[dict[str, Any], ...] = (
    {
        "id": "factory_owner_demo",
        "title": "Factory Owner Demo",
        "audience": "factory_owner",
        "description": (
            "End-to-end story for a Chinese factory owner: apply, onboard, "
            "activate platform, acquire buyers, and review executive insights."
        ),
        "estimated_minutes": 25,
        "recommended_for": "Factory owners and export directors",
        "journey_route": "/pilot-demo#factory-owner",
    },
    {
        "id": "sales_director_demo",
        "title": "Sales Director Demo",
        "audience": "sales_director",
        "description": (
            "Sales leadership view: buyer acquisition, marketplace exchange, "
            "deal risk, and revenue forecast."
        ),
        "estimated_minutes": 18,
        "recommended_for": "International sales directors",
        "journey_route": "/pilot-demo#scenarios",
    },
    {
        "id": "executive_demo",
        "title": "Executive Demo",
        "audience": "executive",
        "description": (
            "C-suite narrative: business health, pilot readiness, revenue outlook, "
            "and strategic buyer pipeline."
        ),
        "estimated_minutes": 15,
        "recommended_for": "CEOs and executive sponsors",
        "journey_route": "/pilot-demo#executive",
    },
    {
        "id": "distributor_demo",
        "title": "Distributor Demo",
        "audience": "distributor",
        "description": (
            "Partner/distributor angle: marketplace opportunities, buyer network, "
            "and customer portal visibility."
        ),
        "estimated_minutes": 12,
        "recommended_for": "Distributors and trading partners",
        "journey_route": "/pilot-demo#scenarios",
    },
)

_FACTORY_OWNER_STEPS: tuple[dict[str, Any], ...] = (
    {
        "id": "factory_application",
        "title": "Factory Application",
        "narrative": "Show how a factory submits onboarding with product categories and target markets.",
        "admin_route": "/factory-apply",
        "tenant_route": None,
        "check": "application",
    },
    {
        "id": "application_approval",
        "title": "Application Approval",
        "narrative": "Admin reviews and approves the partner application — manual, no auto-approve in live ops.",
        "admin_route": "/factory-partners",
        "tenant_route": None,
        "check": "approved",
    },
    {
        "id": "tenant_creation",
        "title": "Tenant Creation",
        "narrative": "Multi-tenant workspace is created and linked to the approved factory client.",
        "admin_route": "/tenants",
        "tenant_route": None,
        "check": "tenant",
    },
    {
        "id": "subscription_activation",
        "title": "Subscription Activation",
        "narrative": "Professional plan subscription activates billing visibility (architecture only, no payments).",
        "admin_route": "/billing",
        "tenant_route": "/billing",
        "check": "subscription",
    },
    {
        "id": "factory_platform",
        "title": "Factory Platform",
        "narrative": "Company profile, catalog, certificates, and export markets demonstrate factory readiness.",
        "admin_route": "/factory-platform",
        "tenant_route": "/factory-platform",
        "check": "factory_platform",
    },
    {
        "id": "buyer_acquisition",
        "title": "Buyer Acquisition",
        "narrative": "Unified buyers, opportunities, and pipeline from discovery, network, and intelligence.",
        "admin_route": "/buyer-acquisition",
        "tenant_route": "/buyer-acquisition",
        "check": "buyers",
    },
    {
        "id": "marketplace",
        "title": "Marketplace",
        "narrative": "Lead exchange opportunities ranked for strategic export conversations.",
        "admin_route": "/marketplace",
        "tenant_route": "/marketplace",
        "check": "marketplace",
    },
    {
        "id": "executive_copilot",
        "title": "Executive Copilot",
        "narrative": "Executive overview ties revenue, risk, buyers, and pilot readiness into one briefing.",
        "admin_route": "/executive-copilot",
        "tenant_route": None,
        "check": "executive",
    },
    {
        "id": "reports_forecasts",
        "title": "Reports & Forecasts",
        "narrative": "Revenue forecast and attribution close the story with measurable growth narrative.",
        "admin_route": "/revenue-forecast",
        "tenant_route": "/customer-portal-v2",
        "check": "forecasts",
    },
)

_EXECUTIVE_STEPS: tuple[dict[str, Any], ...] = (
    {
        "id": "executive_overview",
        "title": "Executive Overview",
        "narrative": "Business health score, alerts, and strategic recommendations.",
        "admin_route": "/executive-copilot",
        "check": "executive",
    },
    {
        "id": "pilot_readiness",
        "title": "Pilot & Demo Readiness",
        "narrative": "Launch QA and guided demo readiness for investor or factory executive meetings.",
        "admin_route": "/pilot-demo",
        "check": "demo_ready",
    },
    {
        "id": "revenue_forecast",
        "title": "Revenue Forecast",
        "narrative": "7/30/90-day scenarios and pipeline-weighted revenue outlook.",
        "admin_route": "/revenue-forecast",
        "check": "forecasts",
    },
    {
        "id": "buyer_pipeline",
        "title": "Buyer Pipeline",
        "narrative": "Top buyers, strategic relationships, and marketplace opportunities.",
        "admin_route": "/buyer-acquisition",
        "check": "buyers",
    },
    {
        "id": "deal_risk",
        "title": "Deal Risk",
        "narrative": "At-risk revenue and deals requiring executive intervention.",
        "admin_route": "/deal-risk",
        "check": "deals",
    },
)

_PAGE_PROBES: tuple[tuple[str, str, str], ...] = (
    ("factory_apply", "/factory-apply", "/api/v1/system/health"),
    ("factory_partners", "/factory-partners", "/api/v1/factory-partner/summary-widget"),
    ("tenants", "/tenants", "/api/v1/tenants?limit=1"),
    ("billing", "/billing", "/api/v1/billing/plans"),
    ("factory_platform", "/factory-platform", "/api/v1/factory-platform/summary-widget"),
    ("buyer_acquisition", "/buyer-acquisition", "/api/v1/buyer-acquisition/overview"),
    ("marketplace", "/marketplace", "/api/v1/marketplace/overview"),
    ("executive_copilot", "/executive-copilot", "/api/v1/executive-copilot/overview"),
    ("revenue_forecast", "/revenue-forecast", "/api/v1/revenue-forecast/overview"),
    ("customer_portal_v2", "/customer-portal-v2", "/api/v1/customer-portal-v2/summary-widget"),
    ("pilot_demo", "/pilot-demo", "/api/v1/pilot-demo/overview"),
    ("pilot_launch", "/pilot-launch", "/api/v1/pilot-launch/overview"),
)

_PRESENTATION_FACTORY: tuple[tuple[str, str, int, str], ...] = (
    ("Opening", "/pilot-demo", 2, "Set context: AI sales OS for Chinese exporters"),
    ("Factory apply", "/factory-apply", 3, "Self-service onboarding story"),
    ("Admin approval", "/factory-partners", 3, "Manual governance — no auto-approve"),
    ("Tenant & billing", "/tenants", 4, "SaaS workspace + subscription architecture"),
    ("Factory platform", "/factory-platform", 5, "Profile, catalog, certificates, markets"),
    ("Buyer acquisition", "/buyer-acquisition", 5, "Unified buyer pipeline"),
    ("Marketplace", "/marketplace", 4, "Lead exchange and ranking"),
    ("Executive copilot", "/executive-copilot", 4, "Executive briefing and health"),
    ("Forecast close", "/revenue-forecast", 3, "Revenue scenarios and pipeline"),
)

_PRESENTATION_EXECUTIVE: tuple[tuple[str, str, int, str], ...] = (
    ("Executive copilot", "/executive-copilot", 5, "Business health and alerts"),
    ("Pilot demo center", "/pilot-demo", 3, "Guided demo readiness"),
    ("Revenue forecast", "/revenue-forecast", 4, "Growth scenarios"),
    ("Buyer acquisition", "/buyer-acquisition", 4, "Strategic buyers"),
    ("Deal risk", "/deal-risk", 3, "Intervention priorities"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Pilot demo tooling is read-only — no provisioning, billing changes, or external calls. "
        "Use Pilot Launch to seed tagged demo data before presentations."
    )


class PilotDemoService:
    @staticmethod
    def scenarios() -> dict[str, Any]:
        return {
            "scenarios": list(_SCENARIOS),
            "default_scenario_id": "factory_owner_demo",
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def _demo_context(db: AsyncSession) -> dict[str, Any]:
        return await PilotLaunchService._demo_context(db)

    @staticmethod
    async def demo_metrics(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotDemoService._demo_context(db)
        app = ctx.get("application")
        tenant_id: UUID | None = ctx.get("tenant_id")
        client_id: UUID | None = ctx.get("client_id")
        demo_present = app is not None

        buyers = opportunities = marketplace = deals = proposals = 0
        revenue_usd = 0.0
        forecast_periods = 3

        if client_id:
            buyers = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerDiscoveryEntry)
                    .where(
                        BuyerDiscoveryEntry.client_id == client_id,
                        or_(
                            BuyerDiscoveryEntry.notes.contains(PILOT_DEMO_MARKER),
                            BuyerDiscoveryEntry.company_name.contains(PILOT_DEMO_MARKER),
                        ),
                    ),
                ) or 0,
            )
            if buyers == 0:
                buyers = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(BuyerDiscoveryEntry)
                        .where(BuyerDiscoveryEntry.client_id == client_id),
                    ) or 0,
                )

            opportunities = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmLead)
                    .where(
                        CrmLead.client_id == client_id,
                        or_(
                            CrmLead.notes.contains(PILOT_DEMO_MARKER),
                            CrmLead.company.contains("Demo"),
                        ),
                    ),
                ) or 0,
            )

            deals = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmDeal)
                    .where(
                        CrmDeal.client_id == client_id,
                        or_(
                            CrmDeal.title.contains(PILOT_DEMO_MARKER),
                            CrmDeal.client_id == client_id,
                        ),
                    ),
                ) or 0,
            )

            proposals = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmProposal)
                    .where(CrmProposal.client_id == client_id),
                ) or 0,
            )

            rev_rows = await db.execute(
                select(RevenueEvent.amount)
                .join(CrmDeal, RevenueEvent.deal_id == CrmDeal.id)
                .where(CrmDeal.client_id == client_id),
            )
            for (amount,) in rev_rows.all():
                if amount is not None:
                    revenue_usd += float(amount)

        if tenant_id:
            marketplace = int(
                await db.scalar(
                    select(func.count())
                    .select_from(MarketplaceOpportunity)
                    .where(
                        MarketplaceOpportunity.created_by_tenant == tenant_id,
                        or_(
                            MarketplaceOpportunity.title.contains(PILOT_DEMO_MARKER),
                            MarketplaceOpportunity.description.contains(PILOT_DEMO_MARKER),
                        ),
                    ),
                ) or 0,
            )
            if marketplace == 0:
                marketplace = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(MarketplaceOpportunity)
                        .where(MarketplaceOpportunity.created_by_tenant == tenant_id),
                    ) or 0,
                )

        if not demo_present:
            forecast_periods = 0

        return {
            "demo_buyers": buyers,
            "demo_opportunities": opportunities,
            "demo_revenue_usd": round(revenue_usd, 2),
            "demo_forecast_periods": forecast_periods,
            "demo_marketplace_opportunities": marketplace,
            "demo_deals": deals,
            "demo_proposals": proposals,
            "demo_data_present": demo_present,
            "demo_company_name": app.company_name if app else None,
            "details": {
                "tenant_id": str(tenant_id) if tenant_id else None,
                "client_id": str(client_id) if client_id else None,
                "demo_marker": PILOT_DEMO_MARKER,
            },
        }

    @staticmethod
    async def _step_status(db: AsyncSession, check: str, ctx: dict[str, Any]) -> tuple[str, str | None]:
        app = ctx.get("application")
        tenant_id = ctx.get("tenant_id")
        client_id = ctx.get("client_id")
        metrics = await PilotDemoService.demo_metrics(db)

        if not app:
            return "blocked", "Seed pilot demo data via Pilot Launch first"

        if check == "application":
            return "ready", f"Application {app.status}"
        if check == "approved":
            if app.status == "approved":
                return "ready", "Application approved"
            return "warning", f"Status is {app.status}"
        if check == "tenant":
            if tenant_id:
                return "ready", f"Tenant {tenant_id}"
            return "blocked", "Create tenant from approved application"
        if check == "subscription":
            if tenant_id:
                from app.services.subscription_service import SubscriptionService

                sub, plan = await SubscriptionService._active_subscription(db, tenant_id)
                if sub and sub.status in ("trial", "active"):
                    return "ready", f"Plan {plan.code if plan else 'active'}"
                return "warning", "No active subscription"
            return "blocked", "Tenant required"
        if check == "factory_platform":
            if tenant_id:
                from app.services.factory_profile_service import FactoryProfileService

                score = await FactoryProfileService.profile_score(db, tenant_id)
                ps = score.get("profile_score", score.get("score", 0))
                if ps >= 50:
                    return "ready", f"Profile score {ps}%"
                return "warning", "Complete factory profile for stronger demo"
            return "blocked", "Tenant required"
        if check == "buyers":
            if metrics["demo_buyers"] > 0:
                return "ready", f"{metrics['demo_buyers']} demo buyers"
            return "warning", "No buyer discovery rows — seed demo data"
        if check == "marketplace":
            if metrics["demo_marketplace_opportunities"] > 0:
                return "ready", f"{metrics['demo_marketplace_opportunities']} opportunities"
            return "warning", "No marketplace opportunities"
        if check == "executive":
            return "ready", "Executive copilot available"
        if check == "forecasts":
            if metrics["demo_forecast_periods"] > 0 and metrics["demo_deals"] > 0:
                return "ready", "Forecast inputs from CRM pipeline"
            return "warning", "Limited forecast inputs"
        if check == "deals":
            if metrics["demo_deals"] > 0:
                return "ready", f"{metrics['demo_deals']} deals"
            return "warning", "No demo deals"
        if check == "demo_ready":
            readiness = await PilotDemoService.readiness(db)
            if readiness["readiness_score"] >= 70:
                return "ready", f"Readiness {readiness['readiness_score']}%"
            return "warning", "Improve demo readiness before executive meeting"
        return "info", None

    @staticmethod
    async def _build_journey(
        db: AsyncSession,
        *,
        scenario_id: str,
        title: str,
        step_defs: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        ctx = await PilotDemoService._demo_context(db)
        steps: list[dict[str, Any]] = []
        completed = 0
        current_id: str | None = None

        for idx, spec in enumerate(step_defs, start=1):
            status, message = await PilotDemoService._step_status(db, spec["check"], ctx)
            if status == "ready":
                completed += 1
            elif current_id is None and status in ("blocked", "warning"):
                current_id = spec["id"]
            steps.append({
                "step": idx,
                "id": spec["id"],
                "title": spec["title"],
                "narrative": spec["narrative"],
                "admin_route": spec.get("admin_route"),
                "tenant_route": spec.get("tenant_route"),
                "status": status,
                "message": message,
                "show_next": True,
            })

        if current_id is None and steps:
            for s in steps:
                if s["status"] != "ready":
                    current_id = s["id"]
                    break

        return {
            "scenario_id": scenario_id,
            "title": title,
            "steps": steps,
            "completed_steps": completed,
            "total_steps": len(steps),
            "current_step_id": current_id or (steps[0]["id"] if steps else None),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def factory_owner_journey(db: AsyncSession) -> dict[str, Any]:
        return await PilotDemoService._build_journey(
            db,
            scenario_id="factory_owner_demo",
            title="Factory Owner Journey",
            step_defs=_FACTORY_OWNER_STEPS,
        )

    @staticmethod
    async def executive_journey(db: AsyncSession) -> dict[str, Any]:
        return await PilotDemoService._build_journey(
            db,
            scenario_id="executive_demo",
            title="Executive Journey",
            step_defs=_EXECUTIVE_STEPS,
        )

    @staticmethod
    async def _probe_pages() -> tuple[list[dict[str, Any]], list[str], list[str]]:
        from app.main import app

        transport = ASGITransport(app=app)
        broken: list[str] = []
        unavailable: list[str] = []
        items: list[dict[str, Any]] = []

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            for page, route, api_path in _PAGE_PROBES:
                start = time.perf_counter()
                error: str | None = None
                status_code = 0
                try:
                    response = await client.get(api_path)
                    status_code = response.status_code
                    if status_code >= 400:
                        detail = response.text[:120] if response.text else response.reason_phrase
                        error = f"HTTP {status_code}: {detail}"
                except Exception as exc:
                    error = str(exc)[:200]

                duration_ms = int((time.perf_counter() - start) * 1000)
                tenant_scoped = page in ("factory_platform", "customer_portal_v2")
                if tenant_scoped and status_code in (401, 403, 422):
                    probe_status = "ok"
                    error = None
                elif error or status_code >= 400:
                    probe_status = "error"
                    broken.append(f"{route} ({api_path})")
                    unavailable.append(route)
                elif duration_ms > SLOW_THRESHOLD_MS:
                    probe_status = "warning"
                else:
                    probe_status = "ok"

                items.append({
                    "key": page,
                    "label": route,
                    "status": probe_status,
                    "message": error or (f"{duration_ms}ms" if probe_status == "ok" else "Slow response"),
                })

        return items, broken, unavailable

    @staticmethod
    async def readiness(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotDemoService._demo_context(db)
        metrics = await PilotDemoService.demo_metrics(db)
        launch = await PilotLaunchService.readiness(db)
        items, broken, unavailable = await PilotDemoService._probe_pages()

        missing: list[str] = []
        if not metrics["demo_data_present"]:
            missing.append("Pilot demo dataset — POST /api/v1/pilot-launch/seed-demo-data")
        if metrics["demo_buyers"] == 0:
            missing.append("Demo buyers in buyer discovery")
        if metrics["demo_marketplace_opportunities"] == 0:
            missing.append("Demo marketplace opportunities")
        if metrics["demo_deals"] == 0:
            missing.append("Demo CRM deals for revenue story")
        if not ctx.get("tenant_id"):
            missing.append("Demo tenant linked to application")

        journey = await PilotDemoService.factory_owner_journey(db)
        journey_penalty = max(0, journey["total_steps"] - journey["completed_steps"]) * 4

        base = int(launch["score"] * 0.45 + (100 if metrics["demo_data_present"] else 20) * 0.35)
        data_bonus = min(20, metrics["demo_buyers"] * 3 + metrics["demo_marketplace_opportunities"] * 4)
        probe_ok = sum(1 for i in items if i["status"] == "ok")
        probe_score = int((probe_ok / max(len(items), 1)) * 100 * 0.2)
        score = _clamp(base + data_bonus + probe_score - journey_penalty)

        return {
            "readiness_score": score,
            "missing_data": missing,
            "broken_links": broken[:10],
            "unavailable_pages": unavailable[:10],
            "items": items,
            "demo_data_present": metrics["demo_data_present"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def presentation_flow(
        db: AsyncSession,
        *,
        scenario_id: str = "factory_owner_demo",
    ) -> dict[str, Any]:
        specs = _PRESENTATION_EXECUTIVE if scenario_id == "executive_demo" else _PRESENTATION_FACTORY
        journey = (
            await PilotDemoService.executive_journey(db)
            if scenario_id == "executive_demo"
            else await PilotDemoService.factory_owner_journey(db)
        )
        current = journey.get("current_step_id")
        steps: list[dict[str, Any]] = []
        for order, (title, route, minutes, point) in enumerate(specs, start=1):
            steps.append({
                "order": order,
                "title": title,
                "route": route,
                "minutes": minutes,
                "talking_points": [point],
            })

        total = sum(s["minutes"] for s in steps)
        recommended = [s["title"] for s in steps]
        what_next = None
        for js in journey["steps"]:
            if js["id"] == current:
                what_next = f"{js['title']}: {js['narrative']}"
                break
        if not what_next and steps:
            what_next = f"Start with {steps[0]['title']} at {steps[0]['route']}"

        title = "Executive Presentation Flow" if scenario_id == "executive_demo" else "Factory Owner Presentation Flow"

        return {
            "scenario_id": scenario_id,
            "title": title,
            "steps": steps,
            "estimated_total_minutes": total,
            "recommended_flow": recommended,
            "what_to_show_next": what_next,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary(db: AsyncSession, *, scenario_id: str = "factory_owner_demo") -> dict[str, Any]:
        readiness = await PilotDemoService.readiness(db)
        flow = await PilotDemoService.presentation_flow(db, scenario_id=scenario_id)
        return {
            "what_to_show_next": flow["what_to_show_next"],
            "recommended_flow": flow["recommended_flow"],
            "estimated_presentation_minutes": flow["estimated_total_minutes"],
            "readiness_score": readiness["readiness_score"],
            "default_scenario_id": "factory_owner_demo",
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def integration_checks(db: AsyncSession) -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []
        try:
            from app.services.api_health_service import ApiHealthService

            await ApiHealthService.check(
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
            )
            checks.append({
                "module": "api_health",
                "status": "ok",
                "message": "System API health probes",
            })
        except Exception as exc:
            checks.append({
                "module": "api_health",
                "status": "degraded",
                "message": str(exc)[:200],
            })

        from app.core.dependency_registry import PAGE_DEPENDENCIES

        checks.append({
            "module": "dependency_registry",
            "status": "ok",
            "message": f"{len(PAGE_DEPENDENCIES)} page dependencies registered",
        })
        checks.append({
            "module": "pilot_launch",
            "status": "ok" if await PilotLaunchService.demo_data_present(db) else "degraded",
            "message": "Pilot launch demo data"
            if await PilotLaunchService.demo_data_present(db)
            else "Seed demo data in Pilot Launch",
        })
        return checks

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        metrics = await PilotDemoService.demo_metrics(db)
        summary = await PilotDemoService.summary(db)
        readiness = await PilotDemoService.readiness(db)
        journey = await PilotDemoService.factory_owner_journey(db)

        return {
            "readiness_score": readiness["readiness_score"],
            "demo_data_present": metrics["demo_data_present"],
            "demo_company_name": metrics.get("demo_company_name"),
            "active_scenario_id": "factory_owner_demo",
            "metrics": metrics,
            "summary": summary,
            "next_recommended_step": journey.get("current_step_id"),
            "integration_checks": await PilotDemoService.integration_checks(db),
            "safety_notice": _safety_notice(),
            "implementation_complete": True,
            "refreshed_at": _utc_now(),
        }

    @staticmethod
    async def refresh(db: AsyncSession) -> dict[str, Any]:
        """Recompute demo assessment — read-only, no provisioning."""
        readiness = await PilotDemoService.readiness(db)
        logger.info("%s refresh readiness=%s", MARKER, readiness["readiness_score"])
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": readiness["readiness_score"],
            "message": "Demo assessment refreshed (read-only — no data changes)",
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotDemoService.overview(db)
        journey = await PilotDemoService.factory_owner_journey(db)
        return {
            "readiness_score": overview["readiness_score"],
            "demo_data_present": overview["demo_data_present"],
            "demo_company_name": overview.get("demo_company_name"),
            "completed_steps": journey["completed_steps"],
            "total_steps": journey["total_steps"],
            "estimated_minutes": overview["summary"]["estimated_presentation_minutes"],
            "what_to_show_next": overview["summary"]["what_to_show_next"],
            "safety_notice": overview["safety_notice"],
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        readiness = await PilotDemoService.readiness(db)
        metrics = await PilotDemoService.demo_metrics(db)
        summary = await PilotDemoService.summary(db, scenario_id="executive_demo")
        return {
            "readiness_score": readiness["readiness_score"],
            "demo_data_present": metrics["demo_data_present"],
            "demo_buyers": metrics["demo_buyers"],
            "demo_revenue_usd": metrics["demo_revenue_usd"],
            "missing_data_count": len(readiness["missing_data"]),
            "broken_links_count": len(readiness["broken_links"]),
            "what_to_show_next": summary["what_to_show_next"],
            "estimated_presentation_minutes": summary["estimated_presentation_minutes"],
            "safety_notice": _safety_notice(),
        }
