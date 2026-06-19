"""Pilot Demo Polish & Sales Presentation v1 — [PILOT_EXECUTION_V1] sales walkthrough (read-only)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.buyer_network import BuyerNetworkProfile, BuyerRelationship
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.deal_room import DealRoom
from app.models.marketplace import MarketplaceOpportunity
from app.models.revenue_event import RevenueEvent
from app.services.pilot_execution_service import (
    PILOT_EXECUTION_MARKER,
    PilotExecutionService,
)

logger = logging.getLogger(__name__)

MARKER = "[Pilot Sales Demo]"

_DEMO_FLOW: tuple[tuple[str, str, int, str, str], ...] = (
    ("Dashboard", "/dashboard", 2, "Executive KPIs and cross-module widgets", "dashboard"),
    ("Factory Platform", "/factory-platform", 3, "Profile, catalog, certificates, export markets", "factory_platform"),
    (
        "Buyer Acquisition",
        "/buyer-acquisition-engine",
        3,
        "Matched buyers, opportunities, and lead pipeline",
        "buyer_acquisition",
    ),
    ("Deal Room", "/deal-room", 3, "Active deals, buyer context, documents, timeline", "deal_room"),
    ("Revenue Engine", "/revenue-engine", 2, "Pipeline value, forecast, and factory revenue view", "revenue_engine"),
    (
        "Executive Copilot",
        "/executive-copilot",
        2,
        "Business health, alerts, and strategic recommendations",
        "executive_copilot",
    ),
)

_CTAS: tuple[tuple[str, str, str, str], ...] = (
    (
        "start_pilot",
        "Start pilot",
        "Begin guided pilot onboarding with the Real Factory Pilot workspace.",
        "/real-factory-pilot",
    ),
    (
        "complete_profile",
        "Complete factory profile",
        "Fill company profile, media, and verification for stronger buyer matching.",
        "/factory-platform",
    ),
    (
        "add_products",
        "Add more products",
        "Expand catalog with MOQ, pricing, and export availability.",
        "/factory-platform",
    ),
    (
        "approve_outreach",
        "Approve buyer outreach manually",
        "Review matched buyers and approve outreach — no automatic messaging.",
        "/buyer-acquisition-engine",
    ),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Sales demo is read-only — uses [PILOT_EXECUTION_V1] pilot data only. "
        "No messaging, automation, external calls, or payments."
    )


def _float_amount(value: Decimal | float | int | None) -> float:
    if value is None:
        return 0.0
    return round(float(value), 2)


class PilotSalesDemoService:
    @staticmethod
    async def _execution_context(db: AsyncSession) -> dict[str, Any]:
        return await PilotExecutionService._execution_context(db)

    @staticmethod
    async def demo_metrics(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotSalesDemoService._execution_context(db)
        app = ctx.get("application")
        tenant_id = ctx.get("tenant_id")
        client_id = ctx.get("client_id")
        present = app is not None

        buyers_found = opportunities = active_deals = deal_rooms = 0
        pipeline_value = revenue_forecast = 0.0
        buyer_countries: set[str] = set()
        profile_score = 0

        if client_id:
            buyers_found = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerDiscoveryEntry)
                    .where(BuyerDiscoveryEntry.client_id == client_id),
                ) or 0,
            )
            if buyers_found == 0:
                buyers_found = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(CrmLead)
                        .where(CrmLead.client_id == client_id),
                    ) or 0,
                )

            country_rows = await db.execute(
                select(BuyerDiscoveryEntry.country)
                .where(
                    BuyerDiscoveryEntry.client_id == client_id,
                    BuyerDiscoveryEntry.country.isnot(None),
                )
                .distinct(),
            )
            for (country,) in country_rows.all():
                if country:
                    buyer_countries.add(country)

            lead_country_rows = await db.execute(
                select(CrmLead.company)
                .where(CrmLead.client_id == client_id),
            )
            for (company,) in lead_country_rows.all():
                if company and PILOT_EXECUTION_MARKER in company:
                    pass

        if tenant_id:
            rel_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerRelationship)
                    .where(BuyerRelationship.tenant_id == tenant_id),
                ) or 0,
            )
            buyers_found = max(buyers_found, rel_count)

            profile_rows = await db.execute(
                select(BuyerNetworkProfile.country)
                .join(BuyerRelationship, BuyerRelationship.buyer_id == BuyerNetworkProfile.id)
                .where(
                    BuyerRelationship.tenant_id == tenant_id,
                    BuyerNetworkProfile.country.isnot(None),
                )
                .distinct(),
            )
            for (country,) in profile_rows.all():
                if country:
                    buyer_countries.add(country)

            marketplace_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(MarketplaceOpportunity)
                    .where(
                        or_(
                            MarketplaceOpportunity.created_by_tenant == tenant_id,
                            MarketplaceOpportunity.title.contains(PILOT_EXECUTION_MARKER),
                        ),
                    ),
                ) or 0,
            )
            opportunities = marketplace_count

            mkt_country_rows = await db.execute(
                select(MarketplaceOpportunity.country)
                .where(
                    MarketplaceOpportunity.created_by_tenant == tenant_id,
                    MarketplaceOpportunity.country.isnot(None),
                )
                .distinct(),
            )
            for (country,) in mkt_country_rows.all():
                if country:
                    buyer_countries.add(country)

        if client_id:
            active_deals = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmDeal)
                    .where(
                        CrmDeal.client_id == client_id,
                        CrmDeal.status.notin_(("won", "lost", "closed_won", "closed_lost")),
                    ),
                ) or 0,
            )
            if active_deals == 0:
                active_deals = int(
                    await db.scalar(
                        select(func.count())
                        .select_from(CrmDeal)
                        .where(CrmDeal.client_id == client_id),
                    ) or 0,
                )

            deal_rows = await db.execute(
                select(CrmDeal.expected_value, CrmDeal.deal_amount, CrmDeal.probability)
                .where(
                    CrmDeal.client_id == client_id,
                    CrmDeal.status.notin_(("won", "lost", "closed_won", "closed_lost")),
                ),
            )
            for expected, amount, prob in deal_rows.all():
                val = expected or amount
                if val is not None:
                    pipeline_value += _float_amount(val)
                    probability = (prob or 50) / 100.0
                    revenue_forecast += _float_amount(val) * probability

            if revenue_forecast == 0 and pipeline_value > 0:
                revenue_forecast = round(pipeline_value * 0.55, 2)

            opportunities = max(
                opportunities,
                int(
                    await db.scalar(
                        select(func.count())
                        .select_from(CrmLead)
                        .where(
                            CrmLead.client_id == client_id,
                            CrmLead.status.notin_(("won", "lost")),
                        ),
                    ) or 0,
                ),
            )

            deal_rooms = int(
                await db.scalar(
                    select(func.count())
                    .select_from(DealRoom)
                    .where(DealRoom.crm_client_id == client_id),
                ) or 0,
            )

            forecast_rows = await db.execute(
                select(RevenueEvent.amount)
                .join(CrmDeal, RevenueEvent.deal_id == CrmDeal.id)
                .where(
                    CrmDeal.client_id == client_id,
                    RevenueEvent.type == "forecast",
                ),
            )
            forecast_sum = sum(_float_amount(a) for (a,) in forecast_rows.all())
            if forecast_sum > 0:
                revenue_forecast = forecast_sum

        readiness = await PilotExecutionService._collect_readiness(db)
        profile_score = readiness.get("factory_profile_score", 0)
        readiness_score = _clamp(
            int(
                readiness.get("real_factory_pilot", 0) * 0.35
                + readiness.get("buyer_acquisition_engine", 0) * 0.25
                + readiness.get("revenue_engine", 0) * 0.2
                + profile_score * 0.2,
            ),
        )
        if not present:
            readiness_score = 0

        return {
            "readiness_score": readiness_score,
            "buyers_found": buyers_found,
            "opportunities": opportunities,
            "active_deals": active_deals,
            "pipeline_value_usd": round(pipeline_value, 2),
            "revenue_forecast_usd": round(revenue_forecast, 2),
            "deal_rooms": deal_rooms,
            "buyer_countries": sorted(buyer_countries),
            "execution_data_present": present,
            "company_name": app.company_name if app else None,
            "factory_profile_score": _clamp(profile_score),
            "details": {
                "tenant_id": str(tenant_id) if tenant_id else None,
                "client_id": str(client_id) if client_id else None,
                "execution_marker": PILOT_EXECUTION_MARKER,
            },
        }

    @staticmethod
    async def factory_owner_story(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotSalesDemoService._execution_context(db)
        app = ctx.get("application")
        metrics = await PilotSalesDemoService.demo_metrics(db)
        report = await PilotExecutionService.execution_report(db)
        company = app.company_name if app else "Your factory"

        if not app:
            return {
                "company_name": None,
                "execution_data_present": False,
                "phases": [
                    {
                        "phase": "seed_required",
                        "title": "Seed pilot execution data",
                        "narrative": (
                            "Run POST /api/v1/pilot-execution/seed-pilot-data to load the "
                            "[PILOT_EXECUTION_V1] factory story."
                        ),
                        "highlights": ["No automatic provisioning"],
                        "status": "blocked",
                    },
                ],
                "safety_notice": _safety_notice(),
            }

        readiness = report.get("readiness_after") or {}
        countries = metrics["buyer_countries"]
        country_text = ", ".join(countries[:5]) if countries else "target export markets"

        phases = [
            {
                "phase": "before",
                "title": "Before China SMM OS",
                "narrative": (
                    f"{company} relied on fragmented spreadsheets, WeChat threads, and ad-hoc "
                    "buyer introductions with no unified export sales workspace."
                ),
                "highlights": [
                    "No centralized buyer pipeline",
                    "Manual profile sharing with distributors",
                    "No revenue forecast or deal room visibility",
                ],
                "status": "info",
            },
            {
                "phase": "after_onboarding",
                "title": "After onboarding",
                "narrative": (
                    f"Application approved, tenant workspace created, subscription active, and "
                    f"factory profile scored {metrics['factory_profile_score']}/100 with catalog, "
                    "certificates, and export markets configured."
                ),
                "highlights": [
                    f"Real Factory Pilot readiness: {readiness.get('real_factory_pilot', 0)}/100",
                    f"Profile score: {metrics['factory_profile_score']}/100",
                    "Customer portal and factory platform linked",
                ],
                "status": "ready" if metrics["factory_profile_score"] >= 70 else "warning",
            },
            {
                "phase": "buyers_discovered",
                "title": "Buyer opportunities discovered",
                "narrative": (
                    f"Buyer Acquisition Engine surfaced {metrics['buyers_found']} matched buyers "
                    f"across {country_text} with {metrics['opportunities']} active opportunities."
                ),
                "highlights": [
                    f"Buyer acquisition readiness: {readiness.get('buyer_acquisition_engine', 0)}/100",
                    f"Countries: {country_text}",
                    "Manual outreach approval only — no automatic messages",
                ],
                "status": "ready" if metrics["buyers_found"] > 0 else "warning",
            },
            {
                "phase": "deals_created",
                "title": "Deals created",
                "narrative": (
                    f"{metrics['active_deals']} active deal(s) in CRM with "
                    f"{metrics['deal_rooms']} deal room(s) for negotiation tracking."
                ),
                "highlights": [
                    f"Pipeline value: ${metrics['pipeline_value_usd']:,.0f} USD",
                    "Deal rooms with buyer context and document placeholders",
                    "No automatic deal stage changes",
                ],
                "status": "ready" if metrics["active_deals"] > 0 else "warning",
            },
            {
                "phase": "forecast_generated",
                "title": "Forecast generated",
                "narrative": (
                    f"Revenue Engine projects ${metrics['revenue_forecast_usd']:,.0f} USD weighted "
                    f"forecast from the execution pipeline."
                ),
                "highlights": [
                    f"Revenue engine readiness: {readiness.get('revenue_engine', 0)}/100",
                    "Forecast from CRM deals and revenue events",
                    "Executive Copilot aggregates health and alerts",
                ],
                "status": "ready" if metrics["revenue_forecast_usd"] > 0 else "warning",
            },
        ]

        return {
            "company_name": company,
            "execution_data_present": True,
            "phases": phases,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def demo_flow() -> dict[str, Any]:
        steps = [
            {
                "order": idx,
                "title": title,
                "route": route,
                "minutes": minutes,
                "talking_points": [point],
                "module": module,
            }
            for idx, (title, route, minutes, point, module) in enumerate(_DEMO_FLOW, start=1)
        ]
        return {
            "title": "15-Minute Sales Demo Flow",
            "steps": steps,
            "estimated_total_minutes": sum(s["minutes"] for s in steps),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def ctas() -> list[dict[str, Any]]:
        return [
            {
                "id": cta_id,
                "title": title,
                "description": desc,
                "route": route,
                "action_type": "link",
            }
            for cta_id, title, desc, route in _CTAS
        ]

    @staticmethod
    async def _build_sections(db: AsyncSession, metrics: dict[str, Any]) -> list[dict[str, Any]]:
        ctx = await PilotSalesDemoService._execution_context(db)
        app = ctx.get("application")
        report = await PilotExecutionService.execution_report(db)
        readiness = report.get("readiness_after") or {}
        completed = report.get("completed_step_count") or 0
        total = len(report.get("completed_steps") or [])

        def status(ok: bool, partial: bool = False) -> str:
            if not app:
                return "blocked"
            if ok:
                return "ready"
            return "warning" if partial else "blocked"

        return [
            {
                "id": "what_china_smm_os_does",
                "title": "What China SMM OS does",
                "summary": (
                    "AI-powered Sales + CRM + Communication OS for Chinese factories — "
                    "onboarding, buyer acquisition, deal rooms, revenue forecasting, and executive insights."
                ),
                "highlights": [
                    "Multi-tenant factory workspace",
                    "Unified buyer acquisition and marketplace",
                    "Read-only intelligence — manual actions only",
                ],
                "status": "ready",
                "route": "/dashboard",
            },
            {
                "id": "factory_onboarding",
                "title": "Factory onboarding summary",
                "summary": (
                    f"{completed}/{total} pilot execution steps complete for "
                    f"{metrics.get('company_name') or 'the pilot factory'}."
                ),
                "highlights": [
                    f"Application approved and tenant provisioned",
                    f"Login: pilot-execution@factory.local (seed credentials)",
                    report.get("next_action") or "Review Real Factory Pilot checklist",
                ],
                "status": status(completed >= 14, partial=completed >= 10),
                "route": "/real-factory-pilot",
            },
            {
                "id": "factory_profile",
                "title": "Factory profile readiness",
                "summary": (
                    f"Profile completeness {metrics['factory_profile_score']}/100 — "
                    "catalog, certificates, export markets, and media."
                ),
                "highlights": [
                    f"Real Factory Pilot component: {readiness.get('real_factory_pilot', 0)}/100",
                    "Verification pending — manual approval only",
                    "Export markets aligned to Central Asia, Russia, Middle East",
                ],
                "status": status(metrics["factory_profile_score"] >= 70, partial=metrics["factory_profile_score"] >= 50),
                "route": "/factory-platform",
            },
            {
                "id": "buyer_acquisition",
                "title": "Buyer acquisition results",
                "summary": (
                    f"{metrics['buyers_found']} buyers found, {metrics['opportunities']} opportunities, "
                    f"countries: {', '.join(metrics['buyer_countries'][:4]) or '—'}."
                ),
                "highlights": [
                    f"Buyer acquisition readiness: {readiness.get('buyer_acquisition_engine', 0)}/100",
                    "Discovery, network, and CRM leads unified",
                    "No automatic outreach",
                ],
                "status": status(metrics["buyers_found"] > 0),
                "route": "/buyer-acquisition-engine",
            },
            {
                "id": "revenue_forecast",
                "title": "Revenue forecast",
                "summary": (
                    f"Pipeline ${metrics['pipeline_value_usd']:,.0f} USD — "
                    f"weighted forecast ${metrics['revenue_forecast_usd']:,.0f} USD."
                ),
                "highlights": [
                    f"Revenue engine readiness: {readiness.get('revenue_engine', 0)}/100",
                    f"{metrics['active_deals']} active deal(s) in pipeline",
                    "Heuristic forecast — no payment processing",
                ],
                "status": status(metrics["revenue_forecast_usd"] > 0, partial=metrics["pipeline_value_usd"] > 0),
                "route": "/revenue-engine",
            },
            {
                "id": "deal_room_proof",
                "title": "Deal room proof",
                "summary": (
                    f"{metrics['deal_rooms']} deal room(s) with buyer context, stage tracking, "
                    "and revenue integration."
                ),
                "highlights": [
                    "Negotiation and quotation stages visible",
                    "Documents and timeline placeholders",
                    "Manual stage updates only",
                ],
                "status": status(metrics["deal_rooms"] > 0),
                "route": "/deal-room",
            },
            {
                "id": "executive_copilot",
                "title": "Executive copilot summary",
                "summary": (
                    "Business health, pilot execution status, revenue and buyer metrics "
                    "aggregated for executive briefings."
                ),
                "highlights": [
                    f"Overall demo readiness: {metrics['readiness_score']}/100",
                    "Alerts and recommendations — no auto actions",
                    "Cross-module lead metrics including pilot execution",
                ],
                "status": status(metrics["readiness_score"] >= 70, partial=metrics["readiness_score"] >= 50),
                "route": "/executive-copilot",
            },
            {
                "id": "next_steps",
                "title": "Next steps for factory",
                "summary": report.get("next_action") or "Expand catalog, approve outreach, and advance deal stages manually.",
                "highlights": [
                    "Complete factory profile to 100%",
                    "Add products for additional export categories",
                    "Review deal rooms and approve buyer contact manually",
                ],
                "status": "ready" if report.get("implementation_complete") else "warning",
                "route": "/real-factory-pilot",
            },
        ]

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        metrics = await PilotSalesDemoService.demo_metrics(db)
        story = await PilotSalesDemoService.factory_owner_story(db)
        flow = await PilotSalesDemoService.demo_flow()
        sections = await PilotSalesDemoService._build_sections(db, metrics)
        report = await PilotExecutionService.execution_report(db)

        company = metrics.get("company_name") or "the pilot factory"
        executive_summary = (
            f"{company} pilot execution demo: readiness {metrics['readiness_score']}/100, "
            f"{metrics['buyers_found']} buyers, ${metrics['pipeline_value_usd']:,.0f} pipeline, "
            f"{metrics['deal_rooms']} deal rooms. "
            f"{'Implementation complete — ready for sales presentation.' if report.get('implementation_complete') else report.get('next_action', 'Complete remaining pilot steps.')}"
        )

        return {
            "execution_marker": PILOT_EXECUTION_MARKER,
            "execution_data_present": metrics["execution_data_present"],
            "company_name": metrics.get("company_name"),
            "implementation_complete": bool(report.get("implementation_complete")),
            "readiness_score": metrics["readiness_score"],
            "metrics": metrics,
            "sections": sections,
            "factory_owner_story": story,
            "demo_flow": flow,
            "ctas": await PilotSalesDemoService.ctas(),
            "executive_summary": executive_summary,
            "pilot_execution_report_route": "/real-factory-pilot",
            "safety_notice": _safety_notice(),
            "refreshed_at": _utc_now(),
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotSalesDemoService.overview(db)
        metrics = overview["metrics"]
        first_step = overview["demo_flow"]["steps"][0]["title"] if overview["demo_flow"]["steps"] else None
        return {
            "readiness_score": metrics["readiness_score"],
            "execution_data_present": metrics["execution_data_present"],
            "company_name": metrics.get("company_name"),
            "buyers_found": metrics["buyers_found"],
            "active_deals": metrics["active_deals"],
            "pipeline_value_usd": metrics["pipeline_value_usd"],
            "deal_rooms": metrics["deal_rooms"],
            "implementation_complete": overview["implementation_complete"],
            "next_demo_step": first_step,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotSalesDemoService.overview(db)
        metrics = overview["metrics"]
        return {
            "readiness_score": metrics["readiness_score"],
            "execution_data_present": metrics["execution_data_present"],
            "company_name": metrics.get("company_name"),
            "buyers_found": metrics["buyers_found"],
            "pipeline_value_usd": metrics["pipeline_value_usd"],
            "revenue_forecast_usd": metrics["revenue_forecast_usd"],
            "deal_rooms": metrics["deal_rooms"],
            "implementation_complete": overview["implementation_complete"],
            "executive_summary": overview["executive_summary"],
            "demo_route": "/pilot-sales-demo",
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def refresh(db: AsyncSession) -> dict[str, Any]:
        metrics = await PilotSalesDemoService.demo_metrics(db)
        logger.info("%s refresh readiness=%s", MARKER, metrics["readiness_score"])
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": metrics["readiness_score"],
            "message": "Sales demo assessment refreshed (read-only — no data changes)",
            "safety_notice": _safety_notice(),
        }
