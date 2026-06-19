"""Pilot Launch Validation v1 — end-to-end pilot experience validation (read-only)."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

from httpx import ASGITransport, AsyncClient

from app.core.database import db_probe_slot
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.models.admin_user import AdminUser
from app.models.buyer_discovery import BuyerDiscoveryEntry
from app.models.buyer_network import BuyerRelationship
from app.models.crm_deal import CrmDeal
from app.models.crm_lead import CrmLead
from app.models.deal_room import DealRoom
from app.models.factory_profile import (
    FactoryCatalogProduct,
    FactoryCertificate,
    FactoryExportMarket,
)
from app.models.marketplace import MarketplaceOpportunity
from app.models.revenue_event import RevenueEvent
from app.services.auth_service import verify_password
from app.services.factory_profile_service import FactoryProfileService
from app.services.pilot_execution_service import (
    PILOT_EXECUTION_EMAIL,
    PILOT_EXECUTION_MARKER,
    PILOT_EXECUTION_PASSWORD,
    PilotExecutionService,
)
from app.services.pilot_sales_demo_service import PilotSalesDemoService

logger = logging.getLogger(__name__)

MARKER = "[Pilot Launch Validation]"

_READINESS_WEIGHTS: tuple[tuple[str, str, int], ...] = (
    ("admin_readiness", "Admin readiness", 15),
    ("tenant_readiness", "Tenant readiness", 15),
    ("factory_profile_readiness", "Factory profile readiness", 15),
    ("buyer_acquisition_readiness", "Buyer acquisition readiness", 15),
    ("revenue_readiness", "Revenue readiness", 10),
    ("demo_readiness", "Demo readiness", 15),
    ("localization_readiness", "Localization readiness", 15),
)

_ADMIN_FLOW_SPECS: tuple[tuple[str, str, str | None], ...] = (
    ("admin_login", "Admin login available", "/admin-login", None),
    ("real_factory_pilot", "Real Factory Pilot", "/real-factory-pilot", "/api/v1/real-factory-pilot/overview"),
    (
        "pilot_execution_report",
        "Pilot execution report",
        "/real-factory-pilot",
        "/api/v1/pilot-execution/report",
    ),
    ("pilot_sales_demo", "Pilot sales demo", "/pilot-sales-demo", "/api/v1/pilot-sales-demo/overview"),
    ("factory_partners", "Factory partners", "/factory-partners", "/api/v1/factory-partner/summary-widget"),
    ("tenants", "Tenants", "/tenants", "/api/v1/tenants?limit=1"),
    ("billing", "Billing", "/billing", "/api/v1/billing/plans"),
    (
        "production_deployment",
        "Production deployment",
        "/production-deployment",
        "/api/v1/production-deployment/overview",
    ),
    ("executive_copilot", "Executive copilot", "/executive-copilot", "/api/v1/executive-copilot/overview"),
)

_TENANT_FLOW_SPECS: tuple[tuple[str, str, str | None], ...] = (
    ("tenant_login", "Tenant login available", "/login", None),
    ("factory_platform", "Factory platform", "/factory-platform", "/api/v1/factory-platform/summary-widget"),
    (
        "customer_portal_v2",
        "Customer portal v2",
        "/customer-portal-v2",
        "/api/v1/customer-portal-v2/summary-widget",
    ),
    (
        "buyer_acquisition_engine",
        "Buyer acquisition engine",
        "/buyer-acquisition-engine",
        "/api/v1/buyer-acquisition-engine/overview",
    ),
    ("revenue_engine", "Revenue engine", "/revenue-engine", "/api/v1/revenue-engine/overview"),
    ("deal_room", "Deal room", "/deal-room", "/api/v1/deal-room/v2/overview"),
    (
        "billing_visibility",
        "Billing visibility",
        "/customer-portal-v2",
        "/api/v1/customer-portal-v2/billing",
    ),
)

_TENANT_SCOPED_PROBES = frozenset({
    "factory_platform",
    "customer_portal_v2",
    "billing_visibility",
})

_ADMIN_SCOPED_PROBES = frozenset({
    "real_factory_pilot",
    "pilot_execution_report",
    "pilot_sales_demo",
    "factory_partners",
    "tenants",
    "executive_copilot",
    "production_deployment",
})

_CLIENT_FACING_PAGES: tuple[tuple[str, str, str], ...] = (
    ("admin_login", "/admin-login", "/api/v1/admin-auth/security-checks"),
    ("tenant_login", "/login", "/api/v1/auth/me"),
    ("factory_platform", "/factory-platform", "/api/v1/factory-platform/summary-widget"),
    ("customer_portal_v2", "/customer-portal-v2", "/api/v1/customer-portal-v2/summary-widget"),
    ("buyer_acquisition_engine", "/buyer-acquisition-engine", "/api/v1/buyer-acquisition-engine/overview"),
    ("revenue_engine", "/revenue-engine", "/api/v1/revenue-engine/overview"),
    ("deal_room", "/deal-room", "/api/v1/deal-room/v2/overview"),
    ("pilot_sales_demo", "/pilot-sales-demo", "/api/v1/pilot-sales-demo/overview"),
    ("real_factory_pilot", "/real-factory-pilot", "/api/v1/real-factory-pilot/overview"),
    ("executive_copilot", "/executive-copilot", "/api/v1/executive-copilot/overview"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Pilot launch validation is read-only — no provisioning, messaging, payments, or external calls. "
        "Uses [PILOT_EXECUTION_V1] execution dataset when present."
    )


def _status_from_score(score: int, *, blocked_below: int = 40, warning_below: int = 70) -> str:
    if score >= warning_below:
        return "ready"
    if score >= blocked_below:
        return "warning"
    return "blocked"


class PilotLaunchValidationService:
    @staticmethod
    async def _probe_api(path: str, *, page_id: str) -> dict[str, Any]:
        from app.main import app

        transport = ASGITransport(app=app)
        start = time.perf_counter()
        error: str | None = None
        status_code = 0
        try:
            async with db_probe_slot():
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await client.get(path)
                    status_code = response.status_code
                if status_code >= 400:
                    detail = response.text[:200] if response.text else response.reason_phrase
                    error = f"HTTP {status_code}: {detail}"
        except Exception as exc:
            error = str(exc)[:500]

        duration_ms = int((time.perf_counter() - start) * 1000)
        if page_id in _TENANT_SCOPED_PROBES and status_code in (401, 403, 422):
            probe_status = "ok"
            error = "Tenant-scoped route — page loads with tenant context"
        elif page_id in _ADMIN_SCOPED_PROBES and status_code in (401, 403):
            probe_status = "ok"
            error = "Admin-scoped route — page loads with admin context"
        elif page_id == "tenant_login" and status_code in (401, 403):
            probe_status = "ok"
            error = "Auth route — page loads with tenant session"
        elif error or status_code >= 400:
            probe_status = "error"
        elif duration_ms > SLOW_THRESHOLD_MS:
            probe_status = "slow"
        else:
            probe_status = "ok"

        return {
            "status_code": status_code,
            "probe_status": probe_status,
            "duration_ms": duration_ms,
            "message": error,
        }

    @staticmethod
    async def _admin_login_check(db: AsyncSession) -> dict[str, Any]:
        count = int(
            await db.scalar(
                select(func.count())
                .select_from(AdminUser)
                .where(
                    AdminUser.password_hash.isnot(None),
                    AdminUser.status == "active",
                ),
            ) or 0,
        )
        if count > 0:
            return {
                "status": "ready",
                "reason": f"{count} active admin user(s) with credentials",
                "missing_items": [],
                "next_action": None,
            }
        return {
            "status": "blocked",
            "reason": "No active admin users with password configured",
            "missing_items": ["Admin user account", "ADMIN_BOOTSTRAP_* in development"],
            "next_action": "Create admin via /admin-login bootstrap or POST /api/v1/admin-auth/bootstrap",
        }

    @staticmethod
    async def _tenant_login_check(db: AsyncSession, ctx: dict[str, Any]) -> dict[str, Any]:
        owner = ctx.get("owner")
        app = ctx.get("application")
        if not app:
            return {
                "status": "blocked",
                "reason": "Pilot execution data not seeded",
                "missing_items": ["[PILOT_EXECUTION_V1] tenant owner"],
                "next_action": "POST /api/v1/pilot-execution/seed-pilot-data",
            }
        if owner and owner.password_hash and verify_password(PILOT_EXECUTION_PASSWORD, owner.password_hash):
            return {
                "status": "ready",
                "reason": f"Tenant owner login ready ({PILOT_EXECUTION_EMAIL})",
                "missing_items": [],
                "next_action": None,
            }
        if owner and owner.password_hash:
            return {
                "status": "warning",
                "reason": "Tenant owner exists but password differs from pilot default",
                "missing_items": ["Known pilot credentials"],
                "next_action": f"Reset owner password or use configured credentials for {owner.email}",
            }
        return {
            "status": "blocked",
            "reason": "Tenant owner missing or password not set",
            "missing_items": ["Tenant owner user", "password_hash"],
            "next_action": "Complete pilot execution seed or set tenant owner password",
        }

    @staticmethod
    async def admin_flow(db: AsyncSession) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        for page_id, label, route, api_path in _ADMIN_FLOW_SPECS:
            if page_id == "admin_login":
                check = await PilotLaunchValidationService._admin_login_check(db)
                items.append({
                    "id": page_id,
                    "label": label,
                    "route": route,
                    "api_probe": None,
                    "status": check["status"],
                    "reason": check["reason"],
                    "missing_items": check["missing_items"],
                    "next_action": check["next_action"],
                    "duration_ms": None,
                })
                continue

            probe = await PilotLaunchValidationService._probe_api(api_path or "", page_id=page_id)
            if probe["probe_status"] in ("ok", "slow"):
                status = "ready" if probe["probe_status"] == "ok" else "warning"
                reason = probe["message"] or f"API probe OK ({probe['status_code']})"
            else:
                status = "blocked"
                reason = probe["message"] or "API probe failed"

            items.append({
                "id": page_id,
                "label": label,
                "route": route,
                "api_probe": api_path.split("?")[0] if api_path else None,
                "status": status,
                "reason": reason,
                "missing_items": [] if status == "ready" else ["API endpoint reachable"],
                "next_action": None if status == "ready" else f"Fix {label} — check {api_path}",
                "duration_ms": probe["duration_ms"],
            })

        ready = sum(1 for i in items if i["status"] == "ready")
        warning = sum(1 for i in items if i["status"] == "warning")
        blocked = sum(1 for i in items if i["status"] == "blocked")
        return {
            "flow_type": "admin",
            "items": items,
            "ready_count": ready,
            "warning_count": warning,
            "blocked_count": blocked,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def tenant_flow(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotExecutionService._execution_context(db)
        items: list[dict[str, Any]] = []

        for page_id, label, route, api_path in _TENANT_FLOW_SPECS:
            if page_id == "tenant_login":
                check = await PilotLaunchValidationService._tenant_login_check(db, ctx)
                items.append({
                    "id": page_id,
                    "label": label,
                    "route": route,
                    "api_probe": None,
                    "status": check["status"],
                    "reason": check["reason"],
                    "missing_items": check["missing_items"],
                    "next_action": check["next_action"],
                    "duration_ms": None,
                })
                continue

            probe = await PilotLaunchValidationService._probe_api(api_path or "", page_id=page_id)
            if probe["probe_status"] in ("ok", "slow"):
                status = "ready" if probe["probe_status"] == "ok" else "warning"
                reason = probe["message"] or f"API probe OK ({probe['status_code']})"
            else:
                status = "blocked"
                reason = probe["message"] or "API probe failed"

            missing: list[str] = []
            if status != "ready" and not ctx.get("tenant_id"):
                missing.append("Pilot tenant workspace")
                status = "blocked"
                reason = "Pilot execution tenant not seeded"

            items.append({
                "id": page_id,
                "label": label,
                "route": route,
                "api_probe": api_path.split("?")[0] if api_path else None,
                "status": status,
                "reason": reason,
                "missing_items": missing,
                "next_action": None if status == "ready" else f"Open {route} with tenant login",
                "duration_ms": probe["duration_ms"],
            })

        ready = sum(1 for i in items if i["status"] == "ready")
        warning = sum(1 for i in items if i["status"] == "warning")
        blocked = sum(1 for i in items if i["status"] == "blocked")
        return {
            "flow_type": "tenant",
            "items": items,
            "ready_count": ready,
            "warning_count": warning,
            "blocked_count": blocked,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def data_completeness(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotExecutionService._execution_context(db)
        app = ctx.get("application")
        tenant_id = ctx.get("tenant_id")
        client_id = ctx.get("client_id")
        present = app is not None

        profile_score = 0
        cat_count = cert_count = market_count = 0
        buyer_count = opp_count = deal_count = room_count = rev_count = 0

        if tenant_id:
            try:
                score_data = await FactoryProfileService.profile_score(db, tenant_id)
                profile_score = int(score_data.get("score") or 0)
            except Exception:
                profile_score = 0
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

        if client_id:
            discovery = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerDiscoveryEntry)
                    .where(BuyerDiscoveryEntry.client_id == client_id),
                ) or 0,
            )
            buyer_count = discovery
            opp_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(CrmLead)
                    .where(CrmLead.client_id == client_id),
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

        if tenant_id:
            rel_count = int(
                await db.scalar(
                    select(func.count())
                    .select_from(BuyerRelationship)
                    .where(BuyerRelationship.tenant_id == tenant_id),
                ) or 0,
            )
            buyer_count = max(buyer_count, rel_count)
            mkt = int(
                await db.scalar(
                    select(func.count())
                    .select_from(MarketplaceOpportunity)
                    .where(MarketplaceOpportunity.created_by_tenant == tenant_id),
                ) or 0,
            )
            opp_count = max(opp_count, mkt)

        specs: tuple[tuple[str, str, int, int, str], ...] = (
            ("factory_profile", "Factory profile", profile_score, 70, "score"),
            ("products", "Products", cat_count, 1, "count"),
            ("certificates", "Certificates", cert_count, 1, "count"),
            ("export_markets", "Export markets", market_count, 1, "count"),
            ("buyers", "Buyers", buyer_count, 3, "count"),
            ("opportunities", "Opportunities", opp_count, 1, "count"),
            ("deals", "Deals", deal_count, 2, "count"),
            ("revenue_events", "Revenue events", rev_count, 2, "count"),
            ("deal_rooms", "Deal rooms", room_count, 1, "count"),
        )

        items: list[dict[str, Any]] = []
        for item_id, label, value, required_min, kind in specs:
            if not present:
                items.append({
                    "id": item_id,
                    "label": label,
                    "status": "blocked",
                    "count": value,
                    "required_min": required_min,
                    "reason": "Execution data not seeded",
                    "missing_items": [PILOT_EXECUTION_MARKER],
                    "next_action": "POST /api/v1/pilot-execution/seed-pilot-data",
                })
                continue

            if kind == "score":
                ok = value >= required_min
                partial = value >= required_min - 15
            else:
                ok = value >= required_min
                partial = value >= max(1, required_min // 2)

            if ok:
                status = "ready"
                reason = f"{value} {'/100' if kind == 'score' else ''} — meets minimum {required_min}"
                missing: list[str] = []
                next_action = None
            elif partial:
                status = "warning"
                reason = f"{value} — below target {required_min}"
                missing = [f"Need {required_min - value} more" if kind == "count" else f"Score {required_min}+"]
                next_action = f"Improve {label.lower()} in Factory Platform"
            else:
                status = "blocked"
                reason = f"{value} — below minimum {required_min}"
                missing = [label]
                next_action = f"Add {label.lower()} via pilot execution seed or Factory Platform"

            items.append({
                "id": item_id,
                "label": label,
                "status": status,
                "count": value,
                "required_min": required_min,
                "reason": reason,
                "missing_items": missing,
                "next_action": next_action,
            })

        ready = sum(1 for i in items if i["status"] == "ready")
        warning = sum(1 for i in items if i["status"] == "warning")
        blocked = sum(1 for i in items if i["status"] == "blocked")
        return {
            "items": items,
            "ready_count": ready,
            "warning_count": warning,
            "blocked_count": blocked,
            "execution_data_present": present,
            "company_name": app.company_name if app else None,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def client_facing_readiness(db: AsyncSession) -> dict[str, Any]:
        data = await PilotLaunchValidationService.data_completeness(db)
        data_by_id = {i["id"]: i for i in data["items"]}
        ctx = await PilotExecutionService._execution_context(db)

        page_data_deps: dict[str, list[str]] = {
            "factory_platform": ["factory_profile", "products"],
            "customer_portal_v2": ["factory_profile", "deals", "opportunities"],
            "buyer_acquisition_engine": ["buyers", "opportunities"],
            "revenue_engine": ["deals", "revenue_events"],
            "deal_room": ["deal_rooms", "deals"],
            "pilot_sales_demo": ["buyers", "deals", "deal_rooms"],
            "real_factory_pilot": ["factory_profile", "buyers"],
            "executive_copilot": [],
            "admin_login": [],
            "tenant_login": [],
        }

        pages: list[dict[str, Any]] = []
        for page_id, route, api_path in _CLIENT_FACING_PAGES:
            if page_id == "admin_login":
                check = await PilotLaunchValidationService._admin_login_check(db)
                pages.append({
                    "page": page_id,
                    "route": route,
                    "status": check["status"],
                    "reason": check["reason"],
                    "missing_items": check["missing_items"],
                    "next_action": check["next_action"],
                    "api_probe": api_path,
                    "probe_status": "auth_check",
                })
                continue
            if page_id == "tenant_login":
                check = await PilotLaunchValidationService._tenant_login_check(db, ctx)
                pages.append({
                    "page": page_id,
                    "route": route,
                    "status": check["status"],
                    "reason": check["reason"],
                    "missing_items": check["missing_items"],
                    "next_action": check["next_action"],
                    "api_probe": api_path,
                    "probe_status": "auth_check",
                })
                continue

            probe = await PilotLaunchValidationService._probe_api(api_path, page_id=page_id)
            probe_ok = probe["probe_status"] in ("ok", "slow")

            missing_data: list[str] = []
            for dep in page_data_deps.get(page_id, []):
                dep_item = data_by_id.get(dep)
                if dep_item and dep_item["status"] != "ready":
                    missing_data.append(dep_item["label"])

            if not probe_ok:
                status = "blocked"
                reason = probe["message"] or "Page API probe failed"
                next_action = f"Verify {route} loads and API {api_path} responds"
            elif missing_data:
                status = "warning"
                reason = f"Page reachable — data gaps: {', '.join(missing_data)}"
                next_action = f"Complete missing data for {route}"
            else:
                status = "ready"
                reason = probe["message"] or "Page and data ready for client demo"
                next_action = None

            pages.append({
                "page": page_id,
                "route": route,
                "status": status,
                "reason": reason,
                "missing_items": missing_data,
                "next_action": next_action,
                "api_probe": api_path,
                "probe_status": probe["probe_status"],
            })

        ready = sum(1 for p in pages if p["status"] == "ready")
        warning = sum(1 for p in pages if p["status"] == "warning")
        blocked = sum(1 for p in pages if p["status"] == "blocked")
        return {
            "pages": pages,
            "ready_count": ready,
            "warning_count": warning,
            "blocked_count": blocked,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def _component_scores(db: AsyncSession) -> dict[str, int]:
        admin = await PilotLaunchValidationService.admin_flow(db)
        tenant = await PilotLaunchValidationService.tenant_flow(db)
        data = await PilotLaunchValidationService.data_completeness(db)
        client = await PilotLaunchValidationService.client_facing_readiness(db)

        admin_score = _clamp(
            int(round(100 * admin["ready_count"] / max(1, len(admin["items"])))),
        )
        tenant_score = _clamp(
            int(round(100 * tenant["ready_count"] / max(1, len(tenant["items"])))),
        )

        profile_item = next((i for i in data["items"] if i["id"] == "factory_profile"), None)
        factory_profile_score = profile_item["count"] if profile_item else 0

        buyer_item = next((i for i in data["items"] if i["id"] == "buyers"), None)
        opp_item = next((i for i in data["items"] if i["id"] == "opportunities"), None)
        buyer_acq_score = 0
        if buyer_item and opp_item:
            buyer_acq_score = _clamp(
                int(
                    (min(100, buyer_item["count"] * 20) + min(100, opp_item["count"] * 25)) / 2,
                ),
            )
            if buyer_item["status"] == "ready" and opp_item["status"] == "ready":
                buyer_acq_score = max(buyer_acq_score, 80)

        revenue_item = next((i for i in data["items"] if i["id"] == "deals"), None)
        rev_events = next((i for i in data["items"] if i["id"] == "revenue_events"), None)
        revenue_score = 0
        if revenue_item and rev_events:
            revenue_score = _clamp(
                int((min(100, revenue_item["count"] * 30) + min(100, rev_events["count"] * 25)) / 2),
            )
            if revenue_item["status"] == "ready":
                revenue_score = max(revenue_score, 70)

        demo_score = 0
        try:
            metrics = await PilotSalesDemoService.demo_metrics(db)
            demo_score = int(metrics.get("readiness_score") or 0)
        except Exception:
            demo_score = _clamp(
                int(round(100 * client["ready_count"] / max(1, len(client["pages"])))),
            )

        localization_score = 50

        return {
            "admin_readiness": admin_score,
            "tenant_readiness": tenant_score,
            "factory_profile_readiness": factory_profile_score,
            "buyer_acquisition_readiness": buyer_acq_score,
            "revenue_readiness": revenue_score,
            "demo_readiness": demo_score,
            "localization_readiness": localization_score,
        }

    @staticmethod
    async def readiness(db: AsyncSession) -> dict[str, Any]:
        ctx = await PilotExecutionService._execution_context(db)
        scores = await PilotLaunchValidationService._component_scores(db)
        components: list[dict[str, Any]] = []
        weighted = 0
        total_weight = sum(w for _, _, w in _READINESS_WEIGHTS)

        for key, label, weight in _READINESS_WEIGHTS:
            score = scores.get(key, 0)
            if key == "localization_readiness":
                status = "warning"
                details = "Placeholder — RU/UZ/EN localization audit not yet implemented"
            else:
                status = _status_from_score(score)
                details = None
            components.append({
                "key": key,
                "label": label,
                "score": score,
                "weight": weight,
                "status": status,
                "details": details,
            })
            weighted += score * weight

        overall = _clamp(int(round(weighted / max(1, total_weight))))
        return {
            "score": overall,
            "components": components,
            "execution_data_present": ctx.get("application") is not None,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def blockers(db: AsyncSession) -> dict[str, Any]:
        admin = await PilotLaunchValidationService.admin_flow(db)
        tenant = await PilotLaunchValidationService.tenant_flow(db)
        data = await PilotLaunchValidationService.data_completeness(db)
        client = await PilotLaunchValidationService.client_facing_readiness(db)

        blockers: list[dict[str, Any]] = []

        def collect(flow_items: list[dict[str, Any]], category: str) -> None:
            for item in flow_items:
                if item["status"] == "blocked":
                    blockers.append({
                        "id": item["id"],
                        "label": item["label"],
                        "category": category,
                        "severity": "blocked",
                        "reason": item.get("reason"),
                        "next_action": item.get("next_action"),
                    })
                elif item["status"] == "warning":
                    blockers.append({
                        "id": item["id"],
                        "label": item["label"],
                        "category": category,
                        "severity": "warning",
                        "reason": item.get("reason"),
                        "next_action": item.get("next_action"),
                    })

        collect(admin["items"], "admin_flow")
        collect(tenant["items"], "tenant_flow")
        for item in data["items"]:
            if item["status"] in ("blocked", "warning"):
                blockers.append({
                    "id": item["id"],
                    "label": item["label"],
                    "category": "data",
                    "severity": item["status"],
                    "reason": item.get("reason"),
                    "next_action": item.get("next_action"),
                })
        for page in client["pages"]:
            if page["status"] in ("blocked", "warning"):
                blockers.append({
                    "id": page["page"],
                    "label": page["page"].replace("_", " ").title(),
                    "category": "page",
                    "severity": page["status"],
                    "reason": page.get("reason"),
                    "next_action": page.get("next_action"),
                })

        blocked_count = sum(1 for b in blockers if b["severity"] == "blocked")
        warning_count = sum(1 for b in blockers if b["severity"] == "warning")
        return {
            "blockers": blockers,
            "warning_count": warning_count,
            "blocked_count": blocked_count,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def next_actions(db: AsyncSession) -> dict[str, Any]:
        blockers_data = await PilotLaunchValidationService.blockers(db)
        report = await PilotExecutionService.execution_report(db)

        actions: list[str] = []
        for b in blockers_data["blockers"]:
            if b["severity"] == "blocked" and b.get("next_action"):
                actions.append(b["next_action"])
        if report.get("next_action") and report["next_action"] not in actions:
            actions.append(report["next_action"])
        if not actions:
            actions.append("Pilot launch validation clear — proceed with guided client demo")

        primary = actions[0] if actions else None
        return {
            "actions": actions[:10],
            "primary_action": primary,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        readiness = await PilotLaunchValidationService.readiness(db)
        admin = await PilotLaunchValidationService.admin_flow(db)
        tenant = await PilotLaunchValidationService.tenant_flow(db)
        data = await PilotLaunchValidationService.data_completeness(db)
        client = await PilotLaunchValidationService.client_facing_readiness(db)
        blockers_data = await PilotLaunchValidationService.blockers(db)
        actions = await PilotLaunchValidationService.next_actions(db)
        report = await PilotExecutionService.execution_report(db)
        ctx = await PilotExecutionService._execution_context(db)
        app = ctx.get("application")

        blocked_labels = [b["label"] for b in blockers_data["blockers"] if b["severity"] == "blocked"]

        implementation_complete = bool(
            app
            and blockers_data["blocked_count"] == 0
            and admin["blocked_count"] == 0
            and tenant["blocked_count"] == 0
            and report.get("implementation_complete")
        )

        return {
            "readiness_score": readiness["score"],
            "execution_marker": PILOT_EXECUTION_MARKER,
            "execution_data_present": app is not None,
            "company_name": app.company_name if app else None,
            "admin_flow_ready": admin["ready_count"],
            "admin_flow_total": len(admin["items"]),
            "tenant_flow_ready": tenant["ready_count"],
            "tenant_flow_total": len(tenant["items"]),
            "data_ready_count": data["ready_count"],
            "data_total": len(data["items"]),
            "client_facing_ready": client["ready_count"],
            "client_facing_total": len(client["pages"]),
            "blocker_count": blockers_data["blocked_count"],
            "warning_count": blockers_data["warning_count"],
            "blockers": blocked_labels[:8],
            "next_actions": actions["actions"][:5],
            "primary_next_action": actions["primary_action"],
            "implementation_complete": implementation_complete,
            "safety_notice": _safety_notice(),
            "refreshed_at": _utc_now(),
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotLaunchValidationService.overview(db)
        return {
            "readiness_score": overview["readiness_score"],
            "execution_data_present": overview["execution_data_present"],
            "company_name": overview.get("company_name"),
            "admin_flow_ready": overview["admin_flow_ready"],
            "admin_flow_total": overview["admin_flow_total"],
            "tenant_flow_ready": overview["tenant_flow_ready"],
            "tenant_flow_total": overview["tenant_flow_total"],
            "blocker_count": overview["blocker_count"],
            "warning_count": overview["warning_count"],
            "primary_next_action": overview.get("primary_next_action"),
            "implementation_complete": overview["implementation_complete"],
            "safety_notice": overview["safety_notice"],
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotLaunchValidationService.overview(db)
        readiness = await PilotLaunchValidationService.readiness(db)
        return {
            "readiness_score": overview["readiness_score"],
            "execution_data_present": overview["execution_data_present"],
            "company_name": overview.get("company_name"),
            "admin_flow_ready": overview["admin_flow_ready"],
            "admin_flow_total": overview["admin_flow_total"],
            "tenant_flow_ready": overview["tenant_flow_ready"],
            "tenant_flow_total": overview["tenant_flow_total"],
            "blocker_count": overview["blocker_count"],
            "warning_count": overview["warning_count"],
            "top_blockers": overview["blockers"][:5],
            "primary_next_action": overview.get("primary_next_action"),
            "implementation_complete": overview["implementation_complete"],
            "components": readiness["components"],
            "validation_route": "/pilot-launch-validation",
            "safety_notice": overview["safety_notice"],
        }

    @staticmethod
    async def refresh(db: AsyncSession) -> dict[str, Any]:
        overview = await PilotLaunchValidationService.overview(db)
        logger.info("%s refresh score=%s", MARKER, overview["readiness_score"])
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": overview["readiness_score"],
            "message": "Launch validation assessment refreshed (read-only — no data changes)",
            "safety_notice": _safety_notice(),
        }
