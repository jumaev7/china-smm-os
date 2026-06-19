"""First Pilot Client Preparation v1 — client, onboarding, operational, tenant, launch readiness."""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.models.customer_portal_account import CustomerPortalAccount
from app.models.factory_partner_application import FactoryPartnerApplication
from app.models.factory_profile import FactoryCatalogProduct, FactoryCertificate, FactoryExportMarket
from app.models.tenant import TenantUser
from app.services.factory_profile_service import FactoryProfileService
from app.services.pilot_launch_service import PILOT_DEMO_MARKER

PILOT_EXECUTION_MARKER = "[PILOT_EXECUTION_V1]"
from app.services.pilot_onboarding_service import PilotOnboardingService
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

MARKER = "[First Pilot Client]"

_CLIENT_READINESS_WEIGHTS: tuple[tuple[str, str, int], ...] = (
    ("company_profile", "Company profile", 15),
    ("subscription", "Subscription", 15),
    ("tenant_setup", "Tenant setup", 15),
    ("users", "Users", 10),
    ("factory_profile", "Factory profile", 15),
    ("catalog", "Product catalog", 10),
    ("certificates", "Certificates", 10),
    ("export_markets", "Export markets", 10),
)

_OPERATIONAL_CHECKS: tuple[tuple[str, str, str], ...] = (
    ("onboarding_complete", "Onboarding complete", "onboarding"),
    ("billing_configured", "Billing configured", "billing"),
    ("dashboard_available", "Dashboard available", "/api/v1/dashboard/overview"),
    ("customer_portal_available", "Customer portal available", "/api/v1/customer-portal-v2/summary-widget"),
    ("executive_copilot_available", "Executive copilot available", "/api/v1/executive-copilot/overview"),
)

_PROFILE_MIN_SCORE = 50


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Read-only pilot client preparation — no automatic provisioning, billing actions, "
        "or messaging. All admin actions remain manual."
    )


def _is_demo_application(app: FactoryPartnerApplication) -> bool:
    desc = app.company_description or ""
    name = app.company_name or ""
    return PILOT_DEMO_MARKER in desc or "(Pilot)" in name or "Demo Co." in name


def _readiness_status(score: int) -> str:
    if score >= 80:
        return "ready"
    if score >= 50:
        return "warning"
    return "blocked"


class FirstPilotClientService:
    _cache: dict[str, Any] | None = None
    _cache_at: datetime | None = None

    @staticmethod
    def _invalidate_cache() -> None:
        FirstPilotClientService._cache = None
        FirstPilotClientService._cache_at = None

    @staticmethod
    async def _list_real_applications(db: AsyncSession) -> list[FactoryPartnerApplication]:
        result = await db.execute(
            select(FactoryPartnerApplication)
            .where(
                FactoryPartnerApplication.status.in_(("approved", "submitted", "under_review")),
            )
            .order_by(
                FactoryPartnerApplication.status.desc(),
                FactoryPartnerApplication.updated_at.desc(),
            ),
        )
        apps = [a for a in result.scalars().all() if not _is_demo_application(a)]
        return apps

    @staticmethod
    async def _resolve_pilot_client(db: AsyncSession) -> FactoryPartnerApplication | None:
        apps = await FirstPilotClientService._list_real_applications(db)
        if not apps:
            return None

        scored: list[tuple[int, FactoryPartnerApplication]] = []
        for app in apps:
            ev = await PilotOnboardingService._evaluate(db, app)
            bonus = 0
            if app.status == "approved":
                bonus += 20
            if app.tenant_id:
                bonus += 10
            desc = app.company_description or ""
            if PILOT_EXECUTION_MARKER in desc:
                bonus += 50
            scored.append((ev["readiness_score"] + bonus, app))

        scored.sort(key=lambda x: (-x[0], x[1].updated_at or _utc_now()), reverse=False)
        return scored[0][1]

    @staticmethod
    async def _tenant_user_count(db: AsyncSession, tenant_id: UUID | None) -> int:
        if not tenant_id:
            return 0
        return int(
            await db.scalar(
                select(func.count())
                .select_from(TenantUser)
                .where(
                    TenantUser.tenant_id == tenant_id,
                    TenantUser.status == "active",
                ),
            ) or 0,
        )

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
    async def _api_probe(path: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            from app.main import app as fastapi_app

            transport = ASGITransport(app=fastapi_app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(path)
            duration_ms = int((time.perf_counter() - started) * 1000)
            ok = response.status_code < 400
            slow = duration_ms >= SLOW_THRESHOLD_MS
            return {
                "ok": ok,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "slow": slow,
                "message": None if ok else f"HTTP {response.status_code}",
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
    async def _build_context(db: AsyncSession) -> dict[str, Any]:
        app = await FirstPilotClientService._resolve_pilot_client(db)
        if not app:
            return {
                "application": None,
                "evaluation": None,
                "tenant_id": None,
                "client_id": None,
                "company_name": None,
                "profile_score_data": None,
                "user_count": 0,
                "catalog_count": 0,
                "certificate_count": 0,
                "export_market_count": 0,
                "portal": None,
                "subscription": None,
            }

        ev = await PilotOnboardingService._evaluate(db, app)
        tenant_id = app.tenant_id
        profile_score_data = None
        if tenant_id:
            try:
                profile_score_data = await FactoryProfileService.profile_score(db, tenant_id)
            except Exception as exc:
                logger.info("%s profile score skip tenant=%s err=%s", MARKER, tenant_id, exc)

        portal = await PilotOnboardingService._portal_account(db, app)
        subscription = await PilotOnboardingService._active_subscription(db, tenant_id)

        return {
            "application": app,
            "evaluation": ev,
            "tenant_id": tenant_id,
            "client_id": app.created_client_id,
            "company_name": app.company_name,
            "profile_score_data": profile_score_data,
            "user_count": await FirstPilotClientService._tenant_user_count(db, tenant_id),
            "catalog_count": await FirstPilotClientService._catalog_count(db, tenant_id),
            "certificate_count": await FirstPilotClientService._certificate_count(db, tenant_id),
            "export_market_count": await FirstPilotClientService._export_market_count(db, tenant_id),
            "portal": portal,
            "subscription": subscription,
        }

    @staticmethod
    async def _client_readiness_components(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        app = ctx["application"]
        ev = ctx["evaluation"]
        tenant_id = ctx["tenant_id"]
        profile_data = ctx["profile_score_data"] or {}
        components_raw: dict[str, tuple[int, str]] = {}

        if not app or not ev:
            for key, label, _weight in _CLIENT_READINESS_WEIGHTS:
                components_raw[key] = (0, "No real factory client identified yet")
        else:
            profile_score = int(profile_data.get("profile_score") or 0)
            profile_components = profile_data.get("components") or {}

            company_score = 40
            company_details = "Application pending approval"
            if app.status == "approved":
                company_score = 85 if ev.get("client_id") else 60
                company_details = f"Application approved — client {'linked' if ev.get('client_id') else 'pending'}"
            elif app.status in {"submitted", "under_review"}:
                company_score = 55
                company_details = f"Application status: {app.status}"

            sub_score = 20
            sub_details = "No subscription"
            subscription = ctx["subscription"]
            if subscription:
                if subscription.status in ("trial", "active"):
                    sub_score = 95
                    sub_details = f"Subscription {subscription.status}"
                else:
                    sub_score = 45
                    sub_details = f"Subscription status: {subscription.status}"

            tenant_score = 90 if tenant_id else 15
            tenant_details = f"Tenant {tenant_id}" if tenant_id else "Tenant not created"

            user_count = ctx["user_count"]
            users_score = min(100, 30 + user_count * 35) if tenant_id else 0
            users_details = f"{user_count} active user(s)" if tenant_id else "No tenant users"

            factory_score = profile_score if tenant_id else 0
            factory_details = (
                f"Factory profile score {profile_score}/100"
                if tenant_id
                else "Factory profile unavailable"
            )

            catalog_count = ctx["catalog_count"]
            catalog_score = min(100, 25 + catalog_count * 15) if catalog_count else 0
            catalog_details = (
                f"{catalog_count} catalog item(s)"
                if catalog_count
                else "No catalog products"
            )

            cert_count = ctx["certificate_count"]
            cert_score = min(100, 30 + cert_count * 20) if cert_count else 0
            cert_details = (
                f"{cert_count} certificate(s)"
                if cert_count
                else "No certificates on file"
            )

            market_count = ctx["export_market_count"]
            market_score = min(100, 25 + market_count * 15) if market_count else 0
            market_details = (
                f"{market_count} export market(s)"
                if market_count
                else "No export markets defined"
            )

            if profile_components.get("profile", 0) >= 18 and company_score < 80:
                company_score = min(100, company_score + 10)

            components_raw = {
                "company_profile": (company_score, company_details),
                "subscription": (sub_score, sub_details),
                "tenant_setup": (tenant_score, tenant_details),
                "users": (users_score, users_details),
                "factory_profile": (factory_score, factory_details),
                "catalog": (catalog_score, catalog_details),
                "certificates": (cert_score, cert_details),
                "export_markets": (market_score, market_details),
            }

        out: list[dict[str, Any]] = []
        for key, label, weight in _CLIENT_READINESS_WEIGHTS:
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
    async def _operational_readiness(db: AsyncSession, ctx: dict[str, Any]) -> dict[str, Any]:
        ev = ctx["evaluation"]
        subscription = ctx["subscription"]
        portal = ctx["portal"]
        items: list[dict[str, Any]] = []

        onboarding_ready = bool(ev and ev.get("status") in {"ready", "completed"})
        items.append({
            "key": "onboarding_complete",
            "label": "Onboarding complete",
            "status": "ready" if onboarding_ready else ("blocked" if ev and ev.get("blockers") else "warning"),
            "ready": onboarding_ready,
            "message": (
                f"Onboarding status: {ev.get('status')}"
                if ev
                else "No pilot client to evaluate"
            ),
        })

        billing_ready = bool(
            subscription and subscription.status in ("trial", "active"),
        )
        items.append({
            "key": "billing_configured",
            "label": "Billing configured",
            "status": "ready" if billing_ready else "blocked",
            "ready": billing_ready,
            "message": (
                f"Plan status: {subscription.status}"
                if subscription
                else "Create and activate subscription manually"
            ),
        })

        for key, label, probe_path in _OPERATIONAL_CHECKS[2:]:
            if key == "customer_portal_available":
                portal_ready = bool(portal and portal.portal_status == "active")
                items.append({
                    "key": key,
                    "label": label,
                    "status": "ready" if portal_ready else "warning",
                    "ready": portal_ready,
                    "message": (
                        f"Portal active for {portal.company_name}"
                        if portal_ready
                        else "Create customer portal account manually"
                    ),
                })
                continue

            probe = await FirstPilotClientService._api_probe(probe_path)
            if probe["ok"] and not probe.get("slow"):
                status = "ready"
            elif probe["ok"]:
                status = "warning"
            else:
                status = "blocked"
            items.append({
                "key": key,
                "label": label,
                "status": status,
                "ready": probe["ok"],
                "message": probe.get("message") or f"API healthy ({probe.get('duration_ms')}ms)",
            })

        ready_count = sum(1 for i in items if i["ready"])
        return {
            "items": items,
            "ready_count": ready_count,
            "total": len(items),
            "all_ready": ready_count == len(items),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _build_blockers(ctx: dict[str, Any]) -> list[dict[str, Any]]:
        app = ctx["application"]
        ev = ctx["evaluation"]
        tenant_id = ctx["tenant_id"]
        tenant_q = f"?tenant_id={tenant_id}" if tenant_id else ""
        blockers: list[dict[str, Any]] = []

        if not app or not ev:
            blockers.append({
                "blocker": "no_pilot_client",
                "label": "No pilot client identified",
                "severity": "critical",
                "message": "Approve a real factory application and exclude demo-tagged records.",
                "route_hint": "/factory-partners",
            })
            return blockers

        if not tenant_id:
            blockers.append({
                "blocker": "missing_tenant",
                "label": "Missing tenant",
                "severity": "critical",
                "message": "Create tenant manually from approved application.",
                "route_hint": f"/factory-partners?application={app.id}",
            })

        if tenant_id and not ctx["subscription"]:
            blockers.append({
                "blocker": "missing_subscription",
                "label": "Missing subscription",
                "severity": "critical",
                "message": "Assign billing plan manually — no automatic subscription setup.",
                "route_hint": f"/billing{tenant_q}",
            })

        if tenant_id and ctx["user_count"] == 0:
            blockers.append({
                "blocker": "missing_users",
                "label": "Missing users",
                "severity": "critical",
                "message": "Add tenant owner or manager user before pilot launch.",
                "route_hint": f"/tenant-users{tenant_q}",
            })

        profile_score = int((ctx["profile_score_data"] or {}).get("profile_score") or 0)
        if tenant_id and profile_score < _PROFILE_MIN_SCORE:
            blockers.append({
                "blocker": "incomplete_profile",
                "label": "Incomplete profile",
                "severity": "warning",
                "message": f"Factory profile score {profile_score}/100 — complete company profile.",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        if tenant_id and ctx["catalog_count"] == 0:
            blockers.append({
                "blocker": "incomplete_catalog",
                "label": "Incomplete catalog",
                "severity": "warning",
                "message": "Add at least one product to the factory catalog.",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        if tenant_id and ctx["certificate_count"] == 0:
            blockers.append({
                "blocker": "missing_certificates",
                "label": "Missing certificates",
                "severity": "warning",
                "message": "Upload export compliance certificates (CE, ISO, etc.).",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        if tenant_id and ctx["export_market_count"] == 0:
            blockers.append({
                "blocker": "missing_export_markets",
                "label": "Missing export markets",
                "severity": "warning",
                "message": "Define target export markets for buyer matching.",
                "route_hint": f"/factory-platform{tenant_q}",
            })

        for b in ev.get("blockers") or []:
            code = b.get("blocker", "")
            if code in {"tenant", "subscription", "admin_user", "company_profile", "products"}:
                continue
            blockers.append({
                "blocker": code,
                "label": b.get("label", code),
                "severity": b.get("severity", "warning"),
                "message": b.get("message", ""),
                "route_hint": f"/pilot-onboarding",
            })

        return blockers

    @staticmethod
    def _build_recommendations(
        ctx: dict[str, Any],
        blockers: list[dict[str, Any]],
        operational: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        high: list[dict[str, Any]] = []
        medium: list[dict[str, Any]] = []
        low: list[dict[str, Any]] = []

        def _add(
            rec_id: str,
            title: str,
            description: str,
            priority: str,
            route_hint: str | None = None,
        ) -> None:
            item = {
                "id": rec_id,
                "title": title,
                "description": description,
                "priority": priority,
                "route_hint": route_hint,
            }
            if priority == "high":
                high.append(item)
            elif priority == "medium":
                medium.append(item)
            else:
                low.append(item)

        for b in blockers:
            priority = "high" if b["severity"] == "critical" else "medium"
            _add(
                f"resolve_{b['blocker']}",
                b["label"],
                b["message"],
                priority,
                b.get("route_hint"),
            )

        for op in operational.get("items") or []:
            if not op.get("ready") and op["key"] not in {
                "onboarding_complete",
                "billing_configured",
            }:
                _add(
                    f"operational_{op['key']}",
                    f"Enable {op['label'].lower()}",
                    op.get("message") or f"Complete {op['label'].lower()}",
                    "medium",
                    "/first-pilot-client",
                )

        ev = ctx.get("evaluation")
        if ev and ev.get("next_best_action"):
            action = ev["next_best_action"]
            _add(
                f"onboarding_{action.get('action', 'next')}",
                action.get("label", "Complete onboarding step"),
                action.get("description", ""),
                "high",
                action.get("route_hint"),
            )

        if ctx.get("tenant_id") and ctx.get("catalog_count", 0) < 3:
            _add(
                "expand_catalog",
                "Expand product catalog",
                "Add more active catalog items to improve factory readiness score.",
                "low",
                f"/factory-platform?tenant_id={ctx['tenant_id']}",
            )

        if not high and not medium:
            _add(
                "final_review",
                "Conduct final launch review",
                "Walk through factory platform, customer portal, and executive copilot with the client.",
                "low",
                "/first-pilot-client",
            )

        return {"high_priority": high, "medium_priority": medium, "low_priority": low}

    @staticmethod
    def _next_action(
        blockers: list[dict[str, Any]],
        recommendations: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any] | None:
        critical = [b for b in blockers if b["severity"] == "critical"]
        if critical:
            b = critical[0]
            return {
                "title": b["label"],
                "description": b["message"],
                "route_hint": b.get("route_hint"),
                "priority": "high",
            }
        if recommendations.get("high_priority"):
            r = recommendations["high_priority"][0]
            return {
                "title": r["title"],
                "description": r["description"],
                "route_hint": r.get("route_hint"),
                "priority": "high",
            }
        if recommendations.get("medium_priority"):
            r = recommendations["medium_priority"][0]
            return {
                "title": r["title"],
                "description": r["description"],
                "route_hint": r.get("route_hint"),
                "priority": "medium",
            }
        return None

    @staticmethod
    async def _assessment(db: AsyncSession) -> dict[str, Any]:
        ctx = await FirstPilotClientService._build_context(db)
        components = await FirstPilotClientService._client_readiness_components(ctx)
        total_weight = sum(c["weight"] for c in components) or 1
        weighted = sum(c["score"] * c["weight"] for c in components) / total_weight
        readiness_score = _clamp(int(round(weighted)))

        operational = await FirstPilotClientService._operational_readiness(db, ctx)
        blockers = FirstPilotClientService._build_blockers(ctx)
        recommendations = FirstPilotClientService._build_recommendations(ctx, blockers, operational)
        all_recs = (
            recommendations["high_priority"]
            + recommendations["medium_priority"]
            + recommendations["low_priority"]
        )
        next_action = FirstPilotClientService._next_action(blockers, recommendations)

        critical_count = sum(1 for b in blockers if b["severity"] == "critical")
        launch_ready = (
            readiness_score >= 80
            and operational["all_ready"]
            and critical_count == 0
            and bool(ctx["application"])
        )

        app = ctx["application"]
        ev = ctx["evaluation"]

        return {
            "ctx": ctx,
            "readiness_score": readiness_score,
            "client_readiness": {
                "score": readiness_score,
                "components": components,
                "client_identified": app is not None,
                "company_name": ctx.get("company_name"),
                "application_id": app.id if app else None,
                "tenant_id": ctx.get("tenant_id"),
                "safety_notice": _safety_notice(),
            },
            "operational_readiness": operational,
            "blockers": blockers,
            "recommendations": recommendations,
            "all_recommendations": all_recs,
            "next_action": next_action,
            "operational_ready": operational["all_ready"],
            "launch_ready": launch_ready,
            "critical_blocker_count": critical_count,
            "onboarding_status": ev.get("status") if ev else None,
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

        await _probe(
            "pilot_onboarding",
            PilotOnboardingService.overview(db),
            "Pilot onboarding aggregation reachable",
        )
        await _probe(
            "first_pilot_client",
            FirstPilotClientService.readiness(db),
            "First pilot client readiness reachable",
        )
        return checks

    @staticmethod
    async def readiness(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        return data["client_readiness"]

    @staticmethod
    async def operational(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        return data["operational_readiness"]

    @staticmethod
    async def blockers(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        ctx = data["ctx"]
        blockers = data["blockers"]
        return {
            "blockers": blockers,
            "blocker_count": len(blockers),
            "critical_count": data["critical_blocker_count"],
            "company_name": ctx.get("company_name"),
            "application_id": ctx["application"].id if ctx.get("application") else None,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def recommendations(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        recs = data["recommendations"]
        total = (
            len(recs["high_priority"])
            + len(recs["medium_priority"])
            + len(recs["low_priority"])
        )
        return {**recs, "total": total, "safety_notice": _safety_notice()}

    @staticmethod
    async def summary(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        ctx = data["ctx"]
        return {
            "readiness_score": data["readiness_score"],
            "operational_ready": data["operational_ready"],
            "launch_ready": data["launch_ready"],
            "blockers": data["blockers"],
            "recommendations": data["all_recommendations"][:8],
            "next_action": data["next_action"],
            "company_name": ctx.get("company_name"),
            "application_id": ctx["application"].id if ctx.get("application") else None,
            "tenant_id": ctx.get("tenant_id"),
            "onboarding_status": data["onboarding_status"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        ctx = data["ctx"]
        app = ctx.get("application")
        recs = data["recommendations"]
        rec_count = (
            len(recs["high_priority"])
            + len(recs["medium_priority"])
            + len(recs["low_priority"])
        )
        return {
            "readiness_score": data["readiness_score"],
            "operational_ready": data["operational_ready"],
            "launch_ready": data["launch_ready"],
            "client_identified": app is not None,
            "company_name": ctx.get("company_name"),
            "application_id": app.id if app else None,
            "tenant_id": ctx.get("tenant_id"),
            "client_id": ctx.get("client_id"),
            "onboarding_status": data["onboarding_status"],
            "blocker_count": len(data["blockers"]),
            "critical_blocker_count": data["critical_blocker_count"],
            "recommendation_count": rec_count,
            "client_readiness": data["client_readiness"],
            "operational_readiness": data["operational_readiness"],
            "blockers": data["blockers"],
            "next_action": data["next_action"],
            "integration_checks": await FirstPilotClientService.integration_checks(db),
            "safety_notice": _safety_notice(),
            "implementation_complete": True,
        }

    @staticmethod
    async def refresh(db: AsyncSession) -> dict[str, Any]:
        FirstPilotClientService._invalidate_cache()
        data = await FirstPilotClientService._assessment(db)
        return {
            "refreshed_at": _utc_now(),
            "readiness_score": data["readiness_score"],
            "blocker_count": len(data["blockers"]),
            "launch_ready": data["launch_ready"],
            "next_action": data["next_action"],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        ctx = data["ctx"]
        next_action = data.get("next_action") or {}
        return {
            "readiness_score": data["readiness_score"],
            "launch_ready": data["launch_ready"],
            "client_identified": ctx.get("application") is not None,
            "company_name": ctx.get("company_name"),
            "blocker_count": len(data["blockers"]),
            "critical_blocker_count": data["critical_blocker_count"],
            "onboarding_status": data["onboarding_status"],
            "next_action_title": next_action.get("title"),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        data = await FirstPilotClientService._assessment(db)
        ctx = data["ctx"]
        return {
            "readiness_score": data["readiness_score"],
            "launch_ready": data["launch_ready"],
            "operational_ready": data["operational_ready"],
            "client_identified": ctx.get("application") is not None,
            "company_name": ctx.get("company_name"),
            "blocker_count": len(data["blockers"]),
            "critical_blocker_count": data["critical_blocker_count"],
            "onboarding_status": data["onboarding_status"],
            "next_action": data["next_action"],
            "top_blockers": data["blockers"][:5],
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def tenant_readiness_indicator(
        db: AsyncSession,
        tenant_id: UUID,
    ) -> dict[str, Any]:
        app = await PilotOnboardingService._application_for_tenant(db, tenant_id)
        if app and _is_demo_application(app):
            app = None
        if not app:
            apps = await FirstPilotClientService._list_real_applications(db)
            app = next((a for a in apps if a.tenant_id == tenant_id), None)
        if not app:
            return {
                "is_pilot_client": False,
                "readiness_score": 0,
                "launch_ready": False,
                "blocker_count": 0,
                "message": "Tenant is not the tracked first pilot client",
                "safety_notice": _safety_notice(),
            }
        pilot = await FirstPilotClientService._resolve_pilot_client(db)
        is_pilot = pilot is not None and pilot.id == app.id
        ev = await PilotOnboardingService._evaluate(db, app)
        profile_score = 0
        try:
            ps = await FactoryProfileService.profile_score(db, tenant_id)
            profile_score = int(ps.get("profile_score") or 0)
        except Exception:
            pass
        blockers = FirstPilotClientService._build_blockers({
            "application": app,
            "evaluation": ev,
            "tenant_id": tenant_id,
            "profile_score_data": {"profile_score": profile_score},
            "user_count": await FirstPilotClientService._tenant_user_count(db, tenant_id),
            "catalog_count": await FirstPilotClientService._catalog_count(db, tenant_id),
            "certificate_count": await FirstPilotClientService._certificate_count(db, tenant_id),
            "export_market_count": await FirstPilotClientService._export_market_count(db, tenant_id),
            "subscription": await PilotOnboardingService._active_subscription(db, tenant_id),
        })
        return {
            "is_pilot_client": is_pilot,
            "readiness_score": ev.get("readiness_score", 0),
            "profile_score": profile_score,
            "launch_ready": ev.get("status") in {"ready", "completed"} and not blockers,
            "blocker_count": len(blockers),
            "company_name": app.company_name,
            "message": (
                f"First pilot client readiness {ev.get('readiness_score', 0)}%"
                if is_pilot
                else "Related factory tenant"
            ),
            "safety_notice": _safety_notice(),
        }
