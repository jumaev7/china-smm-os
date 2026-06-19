"""Pilot Readiness Dashboard — demo tenant health, route stability, content metrics."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_error_buffer import SLOW_THRESHOLD_MS
from app.core.config import settings
from app.core.database import db_probe_slot
from app.models.admin_user import AdminUser
from app.models.client_brief import ClientBrief
from app.models.content import ContentItem
from app.models.operator_task import OperatorTask
from app.models.tenant import TenantUser
from app.services.auth_service import verify_password
from app.services.system_health_service import SystemHealthService
from app.services.tenant_auth_service import DEMO_USER_EMAIL, DEMO_USER_PASSWORD

logger = logging.getLogger(__name__)

MARKER = "[Pilot Readiness]"

_PROBE_TIMEOUT_SEC = 8.0

_ROUTE_SPECS: tuple[tuple[str, str, str, str], ...] = (
    ("dashboard", "/dashboard", "/api/v1/dashboard/overview", "both"),
    ("executive_copilot", "/executive-copilot", "/api/v1/executive-copilot/overview", "both"),
    ("deal_room", "/deal-room", "/api/v1/deal-room/v2/overview", "both"),
    ("deal_risk", "/deal-risk", "/api/v1/deal-risk/overview", "both"),
    ("revenue_forecast", "/revenue-forecast", "/api/v1/revenue-forecast/overview", "admin"),
    ("revenue_analytics", "/revenue-analytics", "/api/v1/analytics/overview", "both"),
    ("briefs", "/briefs", "/api/v1/client-briefs", "tenant"),
    ("content", "/content", "/api/v1/content", "both"),
    ("tasks", "/tasks", "/api/v1/tasks", "both"),
    ("calendar", "/calendar", "/api/v1/calendar/month/2026/6", "both"),
    ("marketplace", "/marketplace", "/api/v1/marketplace/overview", "both"),
    ("buyer_search", "/buyer-search", "/api/v1/buyer-discovery/overview", "both"),
    ("buyer_network", "/buyer-network", "/api/v1/buyer-network/overview", "both"),
)

_ROUTE_ALIASES: dict[str, str] = {
    "/revenue-analytics": "/analytics",
    "/buyer-search": "/buyer-finder",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _status_from_score(score: int) -> str:
    if score >= 75:
        return "ready"
    if score >= 50:
        return "warning"
    return "blocked"


def _safety_notice() -> str:
    return (
        "Pilot readiness dashboard is read-only — aggregates health probes and route audits. "
        "No provisioning, messaging, or external side effects."
    )


class PilotReadinessService:
    @staticmethod
    async def _probe_api(path: str) -> dict[str, Any]:
        from app.main import app

        transport = ASGITransport(app=app)
        start = time.perf_counter()
        error: str | None = None
        status_code = 0
        try:
            async with db_probe_slot():
                async with AsyncClient(transport=transport, base_url="http://test") as client:
                    response = await asyncio.wait_for(
                        client.get(path),
                        timeout=_PROBE_TIMEOUT_SEC,
                    )
                    status_code = response.status_code
                if status_code >= 400:
                    detail = response.text[:200] if response.text else response.reason_phrase
                    error = f"HTTP {status_code}: {detail}"
        except asyncio.TimeoutError:
            error = f"Probe timed out after {_PROBE_TIMEOUT_SEC:.0f}s"
        except Exception as exc:
            error = str(exc)[:500]

        duration_ms = int((time.perf_counter() - start) * 1000)
        if error or status_code >= 400:
            if "timed out" in (error or "").lower():
                probe_status = "slow"
            else:
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
    async def _demo_tenant_health(db: AsyncSession) -> dict[str, Any]:
        user = await db.scalar(
            select(TenantUser).where(func.lower(TenantUser.email) == DEMO_USER_EMAIL.lower()),
        )
        if not user:
            return {
                "key": "demo_tenant",
                "label": "Demo tenant health",
                "status": "blocked",
                "score": 0,
                "message": f"Demo user {DEMO_USER_EMAIL} not found — POST /api/v1/auth/create-demo-user",
            }
        if not user.password_hash or not verify_password(DEMO_USER_PASSWORD, user.password_hash):
            return {
                "key": "demo_tenant",
                "label": "Demo tenant health",
                "status": "warning",
                "score": 40,
                "message": f"Demo user exists but password differs from default ({DEMO_USER_EMAIL})",
            }
        if user.status != "active":
            return {
                "key": "demo_tenant",
                "label": "Demo tenant health",
                "status": "warning",
                "score": 50,
                "message": f"Demo user status is {user.status}",
            }
        return {
            "key": "demo_tenant",
            "label": "Demo tenant health",
            "status": "ready",
            "score": 100,
            "message": f"Demo tenant active ({DEMO_USER_EMAIL}, role={user.role})",
        }

    @staticmethod
    async def _auth_rbac_status(db: AsyncSession) -> dict[str, Any]:
        admin_count = int(
            await db.scalar(
                select(func.count())
                .select_from(AdminUser)
                .where(
                    AdminUser.password_hash.isnot(None),
                    AdminUser.status == "active",
                ),
            ) or 0,
        )
        tenant_users = int(
            await db.scalar(select(func.count()).select_from(TenantUser)) or 0,
        )
        issues: list[str] = []
        score = 100
        if admin_count == 0:
            issues.append("No active admin users")
            score -= 50
        if tenant_users == 0:
            issues.append("No tenant users")
            score -= 30

        status = _status_from_score(score)
        message = (
            f"{admin_count} admin(s), {tenant_users} tenant user(s)"
            + (f" — issues: {', '.join(issues)}" if issues else "")
        )
        return {
            "key": "auth_rbac",
            "label": "Auth / RBAC status",
            "status": status,
            "score": _clamp(score),
            "message": message,
        }

    @staticmethod
    async def _backend_status(db: AsyncSession) -> dict[str, Any]:
        try:
            health = await SystemHealthService.health(db)
            ok = health.get("status") in ("ok", "degraded")
            score = 100 if health.get("status") == "ok" else 70 if ok else 20
            return {
                "key": "backend",
                "label": "Backend status",
                "status": _status_from_score(score),
                "score": score,
                "message": f"API {health.get('status')} — uptime {health.get('uptime', 0)}s",
            }
        except Exception as exc:
            return {
                "key": "backend",
                "label": "Backend status",
                "status": "blocked",
                "score": 0,
                "message": str(exc)[:200],
            }

    @staticmethod
    async def _database_status(db: AsyncSession) -> dict[str, Any]:
        try:
            db_status = await SystemHealthService._check_database(db)
            score = 100 if db_status == "ok" else 0
            return {
                "key": "database",
                "label": "Database status",
                "status": "ready" if db_status == "ok" else "blocked",
                "score": score,
                "message": f"PostgreSQL {db_status}",
            }
        except Exception as exc:
            return {
                "key": "database",
                "label": "Database status",
                "status": "blocked",
                "score": 0,
                "message": str(exc)[:200],
            }

    @staticmethod
    async def _content_metrics(db: AsyncSession) -> dict[str, int]:
        briefs = int(await db.scalar(select(func.count()).select_from(ClientBrief)) or 0)
        tasks = int(
            await db.scalar(
                select(func.count())
                .select_from(OperatorTask)
                .where(OperatorTask.status.notin_(("done", "cancelled"))),
            ) or 0,
        )
        approved = int(
            await db.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(ContentItem.status == "approved"),
            ) or 0,
        )
        scheduled_published = int(
            await db.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    or_(
                        ContentItem.status.in_(("scheduled", "published")),
                        ContentItem.scheduled_for.isnot(None),
                        ContentItem.published_at.isnot(None),
                    ),
                ),
            ) or 0,
        )
        return {
            "briefs_count": briefs,
            "content_tasks_count": tasks,
            "approved_content_count": approved,
            "scheduled_published_content_count": scheduled_published,
        }

    @staticmethod
    async def _route_audits() -> list[dict[str, Any]]:
        if not settings.ROUTE_PROBING_ENABLED:
            return [
                {
                    "route": route,
                    "canonical_route": _ROUTE_ALIASES.get(route),
                    "audience": audience,
                    "status": "skipped",
                    "access": "not_probed",
                    "api_probe": api_path,
                    "api_status_code": None,
                    "duration_ms": None,
                    "issue": "Route probing disabled; set ROUTE_PROBING_ENABLED=true to audit live APIs.",
                }
                for _page_id, route, api_path, audience in _ROUTE_SPECS
            ]

        async def audit_one(
            _page_id: str, route: str, api_path: str, audience: str,
        ) -> dict[str, Any]:
            probe = await PilotReadinessService._probe_api(api_path)
            canonical = _ROUTE_ALIASES.get(route)

            if probe["probe_status"] == "ok":
                audit_status = "pass"
                access = "allowed"
                issue = None
            elif probe["probe_status"] == "slow":
                audit_status = "slow"
                access = "allowed"
                issue = probe["message"] or f"Slow response ({probe['duration_ms']}ms)"
            elif probe["status_code"] in (401, 403):
                audit_status = "pass"
                access = "login_required"
                issue = "Auth-gated — expected without session token in probe"
            else:
                audit_status = "fail"
                access = "unknown"
                issue = probe["message"] or "API probe failed"

            return {
                "route": route,
                "canonical_route": canonical,
                "audience": audience,
                "status": audit_status,
                "access": access,
                "api_probe": api_path,
                "api_status_code": probe["status_code"],
                "duration_ms": probe["duration_ms"],
                "issue": issue,
            }

        tasks = [
            audit_one(page_id, route, api_path, audience)
            for page_id, route, api_path, audience in _ROUTE_SPECS
        ]
        return list(await asyncio.gather(*tasks))

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        demo = await PilotReadinessService._demo_tenant_health(db)
        auth = await PilotReadinessService._auth_rbac_status(db)
        backend = await PilotReadinessService._backend_status(db)
        database = await PilotReadinessService._database_status(db)
        metrics = await PilotReadinessService._content_metrics(db)
        route_audits = await PilotReadinessService._route_audits()

        components = [demo, auth, backend, database]
        weighted = sum(c["score"] for c in components) / len(components)

        probed_routes = [r for r in route_audits if r["status"] != "skipped"]
        routes_pass = sum(1 for r in probed_routes if r["status"] in ("pass", "slow"))
        routes_fail = sum(1 for r in route_audits if r["status"] == "fail")
        route_score = (
            100
            if not probed_routes
            else _clamp(int(round(100 * routes_pass / max(1, len(probed_routes)))))
        )

        readiness_score = _clamp(int(round(weighted * 0.7 + route_score * 0.3)))

        open_issues: list[str] = []
        for c in components:
            if c["status"] != "ready":
                open_issues.append(f"{c['label']}: {c['message']}")
        for r in route_audits:
            if r["status"] == "fail":
                open_issues.append(f"Route {r['route']}: {r['issue']}")
            elif r["status"] == "slow":
                open_issues.append(f"Route {r['route']} slow ({r['duration_ms']}ms)")

        if metrics["briefs_count"] == 0:
            open_issues.append("No client briefs — seed demo data or submit a brief")
        if metrics["approved_content_count"] == 0:
            open_issues.append("No approved content items")

        return {
            "readiness_score": readiness_score,
            "status": _status_from_score(readiness_score),
            "generated_at": _utc_now(),
            "safety_notice": _safety_notice(),
            "demo_tenant_health": demo,
            "auth_rbac_status": auth,
            "backend_status": backend,
            "database_status": database,
            **metrics,
            "open_issues": open_issues[:20],
            "route_audits": route_audits,
            "routes_pass_count": routes_pass,
            "routes_fail_count": routes_fail,
        }
