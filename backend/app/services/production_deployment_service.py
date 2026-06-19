"""Production Deployment Preparation v1 — deployment readiness assessment (read-only)."""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable
from datetime import datetime, timezone
from typing import Any, TypeVar
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.endpoint_guard import safe_section
from app.core.dependency_registry import dependency_graph
from app.models.admin_user import AdminUser
from app.models.tenant import Tenant
from app.services.admin_rbac_service import AdminRbacService, settings_secret_is_default
from app.services.admin_security_service import AdminSecurityService
from app.services.api_health_service import ApiHealthService
from app.services.first_pilot_client_service import FirstPilotClientService
from app.services.subscription_service import SubscriptionService
from app.services.system_health_service import SystemHealthService
from app.services.tenant_service import TenantService

logger = logging.getLogger(__name__)

MARKER = "[Production Deployment]"
_SECTION_TIMEOUT = 2.0
_HEAVY_SECTION_TIMEOUT = 1.5
_API_HEALTH_BUDGET_SEC = 2.0
_API_HEALTH_PROBE_TIMEOUT = 1.0
_API_HEALTH_SKIP = frozenset({"production_deployment"})

T = TypeVar("T")

_READINESS_WEIGHTS: tuple[tuple[str, str, int], ...] = (
    ("authentication", "Authentication", 15),
    ("rbac", "RBAC", 10),
    ("tenant_isolation", "Tenant isolation", 10),
    ("billing", "Billing", 10),
    ("backups", "Backups", 10),
    ("monitoring", "Monitoring", 10),
    ("ssl_readiness", "SSL readiness", 10),
    ("environment_configuration", "Environment configuration", 15),
    ("deployment_configuration", "Deployment configuration", 10),
)

_CHECKLIST_SPECS: tuple[tuple[str, str], ...] = (
    ("domain_ready", "Domain ready"),
    ("ssl_ready", "SSL ready"),
    ("backups_configured", "Backups configured"),
    ("monitoring_configured", "Monitoring configured"),
    ("admin_security_enabled", "Admin security enabled"),
    ("tenant_isolation_verified", "Tenant isolation verified"),
    ("billing_verified", "Billing verified"),
    ("pilot_client_ready", "Pilot client ready"),
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _safety_notice() -> str:
    return (
        "Read-only deployment preparation — no DNS changes, SSL generation, cloud provisioning, "
        "or deployment execution. Assessment only."
    )


def _is_localhost_url(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host in ("localhost", "127.0.0.1", "0.0.0.0", "")
    except Exception:
        return True


def _is_https_url(url: str) -> bool:
    try:
        return urlparse(url).scheme == "https"
    except Exception:
        return False


def _readiness_status(score: int) -> str:
    if score >= 80:
        return "ready"
    if score >= 50:
        return "warning"
    return "blocked"


def _checklist_status(score: int) -> str:
    if score >= 80:
        return "completed"
    if score >= 50:
        return "warning"
    return "blocked"


def _default_env() -> dict[str, Any]:
    return {
        "valid": False,
        "critical_count": 0,
        "warning_count": 1,
        "checks": [],
        "safety_notice": _safety_notice(),
    }


def _default_security() -> dict[str, Any]:
    return {
        "readiness_score": 0,
        "critical_findings": [],
        "warnings": [],
        "protected_route_count": 0,
        "open_route_count": 0,
        "permission_coverage_percent": 0.0,
        "implementation_complete": False,
        "safety_notice": _safety_notice(),
    }


def _default_monitoring() -> dict[str, Any]:
    return {
        "items": [{
            "key": "api_health",
            "label": "API health",
            "status": "warning",
            "message": "API health probe skipped or timed out",
            "details": {},
        }],
        "ready_count": 0,
        "total": 1,
        "all_ready": False,
        "safety_notice": _safety_notice(),
    }


def _default_backups() -> dict[str, Any]:
    return {
        "items": [],
        "ready_count": 0,
        "total": 0,
        "all_ready": False,
        "safety_notice": _safety_notice(),
    }


def _default_pilot() -> dict[str, Any]:
    return {"launch_ready": False, "readiness_score": 0, "blockers": []}


def _default_billing() -> dict[str, Any]:
    return {"plans": [], "items": []}


async def _timed_section(
    name: str,
    coro: Awaitable[T],
    *,
    default: T,
    errors: list[str],
    timeout: float = _SECTION_TIMEOUT,
    db: AsyncSession | None = None,
) -> T:
    start = time.perf_counter()
    result = await safe_section(
        name, coro, default=default, errors=errors, timeout=timeout, db=db,
    )
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    degraded = any(name in err for err in errors)
    logger.info(
        "%s section=%s elapsed_ms=%d degraded=%s",
        MARKER, name, elapsed_ms, degraded,
    )
    return result


class ProductionDeploymentService:
    _cache: dict[str, Any] | None = None
    _cache_at: datetime | None = None

    @staticmethod
    def _invalidate_cache() -> None:
        ProductionDeploymentService._cache = None
        ProductionDeploymentService._cache_at = None

    @staticmethod
    async def _admin_security_data(db: AsyncSession) -> dict[str, Any]:
        try:
            from app.main import app as fastapi_app

            return await AdminSecurityService.security_status(fastapi_app, db)
        except Exception as exc:
            logger.warning("%s Admin security scan failed: %s", MARKER, exc)
            checks = await AdminRbacService.security_checks(db)
            return {
                "readiness_score": 50 if checks.get("ok_count", 0) >= 4 else 30,
                "protected_route_count": 0,
                "open_route_count": 0,
                "permission_coverage_percent": 0.0,
                "open_routes": [],
                "security_checks": checks,
                "implementation_complete": False,
            }

    @staticmethod
    async def _environment_checks() -> list[dict[str, Any]]:
        checks: list[dict[str, Any]] = []

        if settings.APP_ENV == "production":
            checks.append({
                "key": "APP_ENV",
                "label": "APP_ENV",
                "status": "valid",
                "message": "APP_ENV=production",
                "configured": True,
            })
        elif settings.APP_ENV == "development":
            checks.append({
                "key": "APP_ENV",
                "label": "APP_ENV",
                "status": "warning",
                "message": "APP_ENV=development — set to production before launch",
                "configured": False,
            })
        else:
            checks.append({
                "key": "APP_ENV",
                "label": "APP_ENV",
                "status": "warning",
                "message": f"APP_ENV={settings.APP_ENV} — verify staging vs production",
                "configured": True,
            })

        if settings.ADMIN_SECRET_KEY and not settings_secret_is_default():
            if settings.TENANT_SECRET_KEY and settings.ADMIN_SECRET_KEY != settings.TENANT_SECRET_KEY:
                admin_status = "valid"
                admin_msg = "ADMIN_SECRET_KEY configured and distinct from tenant key"
            elif not settings.TENANT_SECRET_KEY:
                admin_status = "warning"
                admin_msg = "ADMIN_SECRET_KEY set — also set TENANT_SECRET_KEY"
            else:
                admin_status = "critical"
                admin_msg = "ADMIN_SECRET_KEY must differ from TENANT_SECRET_KEY"
        elif settings_secret_is_default():
            admin_status = "critical"
            admin_msg = "ADMIN_SECRET_KEY not configured — using default SECRET_KEY"
        else:
            admin_status = "warning"
            admin_msg = "Set explicit ADMIN_SECRET_KEY for production"

        checks.append({
            "key": "ADMIN_SECRET_KEY",
            "label": "ADMIN_SECRET_KEY",
            "status": admin_status,
            "message": admin_msg,
            "configured": bool(settings.ADMIN_SECRET_KEY),
        })

        if settings.TENANT_SECRET_KEY and settings.ADMIN_SECRET_KEY != settings.TENANT_SECRET_KEY:
            tenant_status = "valid"
            tenant_msg = "TENANT_SECRET_KEY configured and distinct"
        elif not settings.TENANT_SECRET_KEY:
            tenant_status = "warning"
            tenant_msg = "TENANT_SECRET_KEY not set — falls back to SECRET_KEY"
        else:
            tenant_status = "critical"
            tenant_msg = "TENANT_SECRET_KEY must differ from ADMIN_SECRET_KEY"

        checks.append({
            "key": "TENANT_SECRET_KEY",
            "label": "TENANT_SECRET_KEY",
            "status": tenant_status,
            "message": tenant_msg,
            "configured": bool(settings.TENANT_SECRET_KEY),
        })

        db_url = settings.DATABASE_URL or ""
        if "localhost" in db_url or "127.0.0.1" in db_url:
            db_status = "warning" if settings.APP_ENV != "production" else "critical"
            db_msg = "DATABASE_URL points to localhost — use managed PostgreSQL in production"
        elif db_url.startswith("postgresql"):
            db_status = "valid"
            db_msg = "DATABASE_URL configured for PostgreSQL"
        else:
            db_status = "critical"
            db_msg = "DATABASE_URL missing or invalid"

        checks.append({
            "key": "DATABASE_URL",
            "label": "DATABASE_URL",
            "status": db_status,
            "message": db_msg,
            "configured": bool(db_url),
        })

        origins = settings.cors_origins_list
        if not origins:
            cors_status = "critical"
            cors_msg = "CORS_ORIGINS empty — frontend will be blocked"
        elif any(_is_localhost_url(o) for o in origins) and settings.APP_ENV == "production":
            cors_status = "warning"
            cors_msg = f"CORS includes localhost: {', '.join(origins)}"
        else:
            cors_status = "valid"
            cors_msg = f"CORS configured: {', '.join(origins[:3])}{'…' if len(origins) > 3 else ''}"

        checks.append({
            "key": "CORS",
            "label": "CORS",
            "status": cors_status,
            "message": cors_msg,
            "configured": bool(origins),
        })

        jwt_issues: list[str] = []
        if settings_secret_is_default():
            jwt_issues.append("default SECRET_KEY")
        if not settings.ADMIN_SECRET_KEY or not settings.TENANT_SECRET_KEY:
            jwt_issues.append("JWT keys not fully separated")
        elif settings.ADMIN_SECRET_KEY == settings.TENANT_SECRET_KEY:
            jwt_issues.append("admin/tenant keys identical")
        if settings.ACCESS_TOKEN_EXPIRE_MINUTES > 60 * 24 * 7:
            jwt_issues.append("access token TTL very long")

        if jwt_issues:
            jwt_status = "critical" if "default SECRET_KEY" in jwt_issues else "warning"
            jwt_msg = "; ".join(jwt_issues)
        else:
            jwt_status = "valid"
            jwt_msg = (
                f"JWT HS256 — access {settings.ACCESS_TOKEN_EXPIRE_MINUTES}m, "
                f"refresh {settings.REFRESH_TOKEN_EXPIRE_DAYS}d"
            )

        checks.append({
            "key": "JWT",
            "label": "JWT configuration",
            "status": jwt_status,
            "message": jwt_msg,
            "configured": not jwt_issues,
        })

        return checks

    @staticmethod
    async def environment_validation() -> dict[str, Any]:
        checks = await ProductionDeploymentService._environment_checks()
        critical_count = sum(1 for c in checks if c["status"] == "critical")
        warning_count = sum(1 for c in checks if c["status"] == "warning")
        return {
            "valid": critical_count == 0 and warning_count == 0,
            "critical_count": critical_count,
            "warning_count": warning_count,
            "checks": checks,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def _component_scores(db: AsyncSession) -> dict[str, dict[str, Any]]:
        sec = await ProductionDeploymentService._admin_security_data(db)
        env = await ProductionDeploymentService.environment_validation()
        rbac_checks = sec.get("security_checks") or await AdminRbacService.security_checks(db)
        if isinstance(rbac_checks, dict) and "checks" in rbac_checks:
            rbac_list = rbac_checks["checks"]
        else:
            rbac_list = rbac_checks.get("checks", []) if isinstance(rbac_checks, dict) else []

        admin_count = int(
            await db.scalar(select(func.count()).select_from(AdminUser)) or 0,
        )

        auth_score = 40
        auth_details = "No platform admin users"
        if admin_count > 0:
            auth_ok = sum(1 for c in rbac_list if c.get("name") == "admin_users_exist" and c.get("status") == "ok")
            auth_score = 85 if auth_ok else 65
            auth_details = f"{admin_count} admin user(s); login protection enabled"

        rbac_score = int(sec.get("readiness_score", 50))
        rbac_details = (
            f"Protected routes={sec.get('protected_route_count', 0)}, "
            f"open={sec.get('open_route_count', 0)}, "
            f"coverage={sec.get('permission_coverage_percent', 0)}%"
        )

        tenant_count = int(await db.scalar(select(func.count()).select_from(Tenant)) or 0)
        isolation_score = 70
        isolation_details = "No tenants to verify"
        if tenant_count > 0:
            sample = await db.execute(select(Tenant.id).limit(3))
            leaks = 0
            for row in sample.scalars():
                check = await TenantService.isolation_check(db, row)
                if not check.get("isolated"):
                    leaks += 1
            isolation_score = 95 if leaks == 0 else max(40, 95 - leaks * 20)
            isolation_details = f"{tenant_count} tenant(s) sampled; cross-tenant leaks={leaks}"

        billing_score = 50
        billing_details = "Billing plans check pending"
        try:
            plans = await SubscriptionService.list_plans(db)
            plan_count = len(plans.get("plans") or plans.get("items") or [])
            if plan_count >= 1:
                billing_score = 90
                billing_details = f"{plan_count} subscription plan(s) configured"
            else:
                billing_score = 40
                billing_details = "No subscription plans found"
        except Exception as exc:
            billing_details = f"Billing check failed: {exc}"[:120]

        backup_data = await ProductionDeploymentService.backup_readiness()
        backup_score = _clamp(
            int(round(sum(
                100 if i["status"] == "ready" else 50 if i["status"] == "warning" else 20
                for i in backup_data["items"]
            ) / max(len(backup_data["items"]), 1))),
        )
        backup_details = f"{backup_data['ready_count']}/{backup_data['total']} backup checks ready"

        monitoring_data = await ProductionDeploymentService.monitoring_readiness(db)
        monitoring_score = _clamp(
            int(round(sum(
                100 if i["status"] == "ready" else 50 if i["status"] == "warning" else 20
                for i in monitoring_data["items"]
            ) / max(len(monitoring_data["items"]), 1))),
        )
        monitoring_details = f"{monitoring_data['ready_count']}/{monitoring_data['total']} monitoring checks ready"

        public_https = _is_https_url(settings.PUBLIC_APP_URL)
        media_https = _is_https_url(settings.MEDIA_BASE_URL)
        if public_https and media_https:
            ssl_score = 95
            ssl_details = "PUBLIC_APP_URL and MEDIA_BASE_URL use HTTPS"
        elif public_https or media_https:
            ssl_score = 60
            ssl_details = "Partial HTTPS — configure both PUBLIC_APP_URL and MEDIA_BASE_URL"
        else:
            ssl_score = 25 if settings.APP_ENV != "production" else 15
            ssl_details = "HTTP URLs detected — TLS required for production"

        env_critical = env["critical_count"]
        env_warning = env["warning_count"]
        env_score = max(20, 100 - env_critical * 25 - env_warning * 10)
        env_details = f"Env checks: {env_critical} critical, {env_warning} warning"

        deploy_score = 50
        deploy_details = "Default deployment configuration"
        if settings.APP_ENV == "production":
            deploy_score += 20
        if "postgres" in (settings.DATABASE_URL or "") and "localhost" not in settings.DATABASE_URL:
            deploy_score += 15
        if not settings.DEMO_MODE:
            deploy_score += 10
        if settings.USE_S3:
            deploy_score += 5
        deploy_score = _clamp(deploy_score)
        deploy_details = (
            f"APP_ENV={settings.APP_ENV}, DEMO_MODE={settings.DEMO_MODE}, "
            f"storage={'S3' if settings.USE_S3 else 'local volume'}"
        )

        raw = {
            "authentication": (auth_score, auth_details),
            "rbac": (rbac_score, rbac_details),
            "tenant_isolation": (isolation_score, isolation_details),
            "billing": (billing_score, billing_details),
            "backups": (backup_score, backup_details),
            "monitoring": (monitoring_score, monitoring_details),
            "ssl_readiness": (ssl_score, ssl_details),
            "environment_configuration": (env_score, env_details),
            "deployment_configuration": (deploy_score, deploy_details),
        }
        out: dict[str, dict[str, Any]] = {}
        for key, label, weight in _READINESS_WEIGHTS:
            score, details = raw[key]
            out[key] = {
                "key": key,
                "label": label,
                "score": _clamp(score),
                "weight": weight,
                "status": _readiness_status(score),
                "details": details,
            }
        return out

    @staticmethod
    async def readiness(db: AsyncSession) -> dict[str, Any]:
        components_map = await ProductionDeploymentService._component_scores(db)
        components = list(components_map.values())
        total_weight = sum(c["weight"] for c in components) or 1
        weighted = sum(c["score"] * c["weight"] for c in components) / total_weight
        return {
            "production_readiness_score": _clamp(int(round(weighted))),
            "components": components,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def backup_readiness() -> dict[str, Any]:
        items: list[dict[str, Any]] = []

        db_configured = bool(settings.DATABASE_URL) and settings.DATABASE_URL.startswith("postgresql")
        is_local_db = "localhost" in settings.DATABASE_URL or "127.0.0.1" in settings.DATABASE_URL
        if db_configured and not is_local_db:
            db_status = "ready"
            db_msg = "DATABASE_URL points to external PostgreSQL — configure provider backups"
        elif db_configured:
            db_status = "warning"
            db_msg = "Local PostgreSQL — set up pg_dump or volume snapshots before production"
        else:
            db_status = "blocked"
            db_msg = "DATABASE_URL not configured"

        items.append({
            "key": "database_backups",
            "label": "Database backups",
            "status": db_status,
            "message": db_msg,
            "configured": db_configured and not is_local_db,
        })

        items.append({
            "key": "restore_procedure",
            "label": "Restore procedure",
            "status": "warning",
            "message": "Document and test restore — see PRODUCTION_DEPLOYMENT_GUIDE.md",
            "configured": False,
        })

        if settings.APP_ENV == "production" and not is_local_db:
            schedule_status = "warning"
            schedule_msg = "Verify automated backup schedule with your PostgreSQL provider"
        else:
            schedule_status = "warning"
            schedule_msg = "Define backup schedule (daily minimum) before production launch"

        items.append({
            "key": "backup_schedule",
            "label": "Backup schedule",
            "status": schedule_status,
            "message": schedule_msg,
            "configured": False,
        })

        ready_count = sum(1 for i in items if i["status"] == "ready")
        return {
            "items": items,
            "ready_count": ready_count,
            "total": len(items),
            "all_ready": ready_count == len(items),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def monitoring_readiness(
        db: AsyncSession,
        *,
        include_api_health: bool = True,
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []

        if include_api_health:
            try:
                api_health = await ApiHealthService.check(
                    None,
                    skip_paths=_API_HEALTH_SKIP,
                    time_budget_sec=_API_HEALTH_BUDGET_SEC,
                    per_probe_timeout_sec=_API_HEALTH_PROBE_TIMEOUT,
                )
                broken = sum(1 for p in api_health.get("endpoints", []) if p.get("status") == "error")
                slow = sum(1 for p in api_health.get("endpoints", []) if p.get("status") == "slow")
                ok = api_health.get("ok_count", 0)
                total = api_health.get("total", 0)
                if broken == 0 and ok >= total * 0.9:
                    api_status = "ready" if slow == 0 else "warning"
                elif broken <= 2:
                    api_status = "warning"
                else:
                    api_status = "blocked"
                items.append({
                    "key": "api_health",
                    "label": "API health",
                    "status": api_status,
                    "message": f"{ok}/{total} probes OK; {broken} errors, {slow} slow",
                    "details": {"ok_count": ok, "total": total, "broken": broken},
                })
            except Exception as exc:
                items.append({
                    "key": "api_health",
                    "label": "API health",
                    "status": "blocked",
                    "message": f"API health probe failed: {exc}"[:200],
                    "details": {},
                })
        else:
            items.append({
                "key": "api_health",
                "label": "API health",
                "status": "warning",
                "message": "Full API probe skipped on overview — use /system/stability",
                "details": {"skipped": True},
            })

        try:
            graph = dependency_graph()
            page_count = len(graph.get("pages") or [])
            prod_page = next(
                (p for p in (graph.get("pages") or []) if p.get("route") == "/production-deployment"),
                None,
            )
            if prod_page:
                dep_status = "ready"
                dep_msg = f"Dependency registry: {page_count} pages including production deployment"
            else:
                dep_status = "warning"
                dep_msg = f"Dependency registry: {page_count} pages — production deployment entry pending"
            items.append({
                "key": "dependency_registry",
                "label": "Dependency registry",
                "status": dep_status,
                "message": dep_msg,
                "details": {"page_count": page_count},
            })
        except Exception as exc:
            items.append({
                "key": "dependency_registry",
                "label": "Dependency registry",
                "status": "warning",
                "message": str(exc)[:200],
                "details": {},
            })

        try:
            sys_health = await SystemHealthService.health(db)
            sys_ok = sys_health.get("status") == "ok"
            items.append({
                "key": "system_health",
                "label": "System health",
                "status": "ready" if sys_ok else "warning",
                "message": (
                    f"Platform {sys_health.get('status')} — DB {sys_health.get('database')}, "
                    f"scheduler {sys_health.get('scheduler')}"
                ),
                "details": {
                    "database": sys_health.get("database"),
                    "scheduler": sys_health.get("scheduler"),
                },
            })
        except Exception as exc:
            items.append({
                "key": "system_health",
                "label": "System health",
                "status": "blocked",
                "message": str(exc)[:200],
                "details": {},
            })

        alert_ready = settings.APP_ENV == "production" and not settings.DEMO_MODE
        items.append({
            "key": "alert_readiness",
            "label": "Alert readiness",
            "status": "ready" if alert_ready else "warning",
            "message": (
                "Configure uptime alerts and error notifications for production"
                if not alert_ready
                else "Production env set — wire external alerting (PagerDuty, email, etc.)"
            ),
            "details": {"app_env": settings.APP_ENV},
        })

        ready_count = sum(1 for i in items if i["status"] == "ready")
        return {
            "items": items,
            "ready_count": ready_count,
            "total": len(items),
            "all_ready": ready_count == len(items),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def security_readiness(db: AsyncSession) -> dict[str, Any]:
        sec = await ProductionDeploymentService._admin_security_data(db)
        rbac_checks = sec.get("security_checks") or {}
        check_list = rbac_checks.get("checks", []) if isinstance(rbac_checks, dict) else []

        critical: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        open_routes = sec.get("open_routes") or []
        if open_routes:
            critical.append({
                "key": "open_admin_routes",
                "label": "Unprotected admin routes",
                "severity": "critical",
                "message": f"{len(open_routes)} admin-facing route(s) without RBAC protection",
            })

        for check in check_list:
            if check.get("status") == "error":
                critical.append({
                    "key": check.get("name", "security_check"),
                    "label": check.get("name", "Security check"),
                    "severity": "critical",
                    "message": check.get("message", ""),
                })
            elif check.get("status") == "warning":
                warnings.append({
                    "key": check.get("name", "security_check"),
                    "label": check.get("name", "Security check"),
                    "severity": "warning",
                    "message": check.get("message", ""),
                })

        if settings.APP_ENV == "development":
            warnings.append({
                "key": "app_env_development",
                "label": "Development environment",
                "severity": "warning",
                "message": "APP_ENV=development — bootstrap routes may be enabled",
            })

        return {
            "readiness_score": int(sec.get("readiness_score", 0)),
            "critical_findings": critical,
            "warnings": warnings,
            "protected_route_count": int(sec.get("protected_route_count", 0)),
            "open_route_count": int(sec.get("open_route_count", 0)),
            "permission_coverage_percent": float(sec.get("permission_coverage_percent", 0)),
            "implementation_complete": bool(sec.get("implementation_complete", False)),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def checklist(db: AsyncSession) -> dict[str, Any]:
        env = await ProductionDeploymentService.environment_validation()
        backups = await ProductionDeploymentService.backup_readiness()
        monitoring = await ProductionDeploymentService.monitoring_readiness(db)
        security = await ProductionDeploymentService.security_readiness(db)
        pilot = await FirstPilotClientService.summary(db)

        domain_ok = not _is_localhost_url(settings.PUBLIC_APP_URL)
        ssl_ok = _is_https_url(settings.PUBLIC_APP_URL) and _is_https_url(settings.MEDIA_BASE_URL)
        backups_ok = backups["all_ready"] or backups["ready_count"] >= 1
        monitoring_ok = monitoring["ready_count"] >= 3
        security_ok = security["readiness_score"] >= 80 and security["open_route_count"] == 0
        isolation_ok = True
        tenant_count = int(await db.scalar(select(func.count()).select_from(Tenant)) or 0)
        if tenant_count > 0:
            sample = await db.execute(select(Tenant.id).limit(1))
            tid = sample.scalar_one_or_none()
            if tid:
                isolation_ok = (await TenantService.isolation_check(db, tid)).get("isolated", False)

        billing_ok = False
        try:
            plans = await SubscriptionService.list_plans(db)
            billing_ok = len(plans.get("plans") or plans.get("items") or []) >= 1
        except Exception:
            pass

        pilot_ok = pilot.get("launch_ready", False)

        raw: dict[str, tuple[bool, str, str | None]] = {
            "domain_ready": (
                domain_ok,
                "PUBLIC_APP_URL uses production domain" if domain_ok else "PUBLIC_APP_URL still localhost",
                "Set PUBLIC_APP_URL to your production domain",
            ),
            "ssl_ready": (
                ssl_ok,
                "HTTPS configured for app and media URLs" if ssl_ok else "TLS not configured on all public URLs",
                "Configure SSL/TLS certificates for PUBLIC_APP_URL and MEDIA_BASE_URL",
            ),
            "backups_configured": (
                backups_ok,
                backups["items"][0]["message"] if backups["items"] else "Backup status unknown",
                "Configure database backups and test restore procedure",
            ),
            "monitoring_configured": (
                monitoring_ok,
                f"{monitoring['ready_count']}/{monitoring['total']} monitoring checks passing",
                "Review /system/stability API health and wire external alerts",
            ),
            "admin_security_enabled": (
                security_ok,
                f"Security score {security['readiness_score']}/100",
                "Resolve open admin routes and rotate JWT secrets",
            ),
            "tenant_isolation_verified": (
                isolation_ok,
                "Tenant isolation verified on sample tenant" if isolation_ok else "Cross-tenant leak detected",
                "Run isolation checks on /tenants",
            ),
            "billing_verified": (
                billing_ok,
                "Subscription plans available" if billing_ok else "Billing plans missing or unreachable",
                "Configure plans on /billing",
            ),
            "pilot_client_ready": (
                pilot_ok,
                f"First pilot client launch_ready={pilot_ok}",
                "Complete first pilot client preparation on /first-pilot-client",
            ),
        }

        items: list[dict[str, Any]] = []
        for key, label in _CHECKLIST_SPECS:
            ok, msg, next_action = raw[key]
            if ok:
                status = "completed"
            elif key in ("domain_ready", "ssl_ready", "backups_configured") and settings.APP_ENV != "production":
                status = "warning"
            else:
                status = "blocked"
            items.append({
                "key": key,
                "label": label,
                "status": status,
                "message": msg,
                "next_action": None if ok else next_action,
            })

        completed = sum(1 for i in items if i["status"] == "completed")
        warning = sum(1 for i in items if i["status"] == "warning")
        blocked = sum(1 for i in items if i["status"] == "blocked")
        next_action = next(
            (i["next_action"] for i in items if i["status"] == "blocked" and i.get("next_action")),
            None,
        ) or next(
            (i["next_action"] for i in items if i["status"] == "warning" and i.get("next_action")),
            None,
        )

        return {
            "items": items,
            "completed_count": completed,
            "warning_count": warning,
            "blocked_count": blocked,
            "all_ready": blocked == 0 and warning == 0,
            "next_action": next_action,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _build_recommendations(
        env: dict[str, Any],
        checklist: dict[str, Any],
        security: dict[str, Any],
    ) -> list[dict[str, Any]]:
        recs: list[dict[str, Any]] = []

        def _add(rid: str, title: str, desc: str, priority: str, route: str | None = None) -> None:
            recs.append({
                "id": rid,
                "title": title,
                "description": desc,
                "priority": priority,
                "route_hint": route,
            })

        for check in env.get("checks") or []:
            if check["status"] == "critical":
                _add(
                    f"env_{check['key']}",
                    f"Fix {check['label']}",
                    check["message"],
                    "high",
                    "/production-deployment",
                )

        for finding in security.get("critical_findings") or []:
            _add(finding["key"], finding["label"], finding["message"], "high", "/admin-audit")

        for item in checklist.get("items") or []:
            if item["status"] == "blocked":
                _add(
                    f"checklist_{item['key']}",
                    item["label"],
                    item["message"],
                    "high",
                    "/production-deployment",
                )
            elif item["status"] == "warning":
                _add(
                    f"checklist_{item['key']}",
                    item["label"],
                    item["message"],
                    "medium",
                    "/production-deployment",
                )

        if not recs:
            _add(
                "final_production_review",
                "Conduct production launch review",
                "Walk through deployment checklist, backups, and monitoring before go-live.",
                "low",
                "/production-deployment",
            )

        return recs[:12]

    @staticmethod
    def _next_action(
        blockers: list[str],
        recommendations: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if blockers:
            return {
                "title": blockers[0],
                "description": "Resolve this blocker before production deployment",
                "route_hint": "/production-deployment",
                "priority": "high",
            }
        high = [r for r in recommendations if r.get("priority") == "high"]
        if high:
            r = high[0]
            return {
                "title": r["title"],
                "description": r["description"],
                "route_hint": r.get("route_hint"),
                "priority": "high",
            }
        medium = [r for r in recommendations if r.get("priority") == "medium"]
        if medium:
            r = medium[0]
            return {
                "title": r["title"],
                "description": r["description"],
                "route_hint": r.get("route_hint"),
                "priority": "medium",
            }
        return None

    @staticmethod
    async def summary(db: AsyncSession) -> dict[str, Any]:
        readiness = await ProductionDeploymentService.readiness(db)
        env = await ProductionDeploymentService.environment_validation()
        checklist = await ProductionDeploymentService.checklist(db)
        security = await ProductionDeploymentService.security_readiness(db)

        blockers = [
            i["label"] for i in checklist["items"] if i["status"] == "blocked"
        ]
        for f in security.get("critical_findings") or []:
            blockers.append(f["label"])
        for c in env.get("checks") or []:
            if c["status"] == "critical":
                blockers.append(c["label"])

        warnings = [
            i["label"] for i in checklist["items"] if i["status"] == "warning"
        ]
        for f in security.get("warnings") or []:
            warnings.append(f["label"])
        for c in env.get("checks") or []:
            if c["status"] == "warning":
                warnings.append(c["label"])

        recommendations = ProductionDeploymentService._build_recommendations(env, checklist, security)
        next_action = ProductionDeploymentService._next_action(blockers, recommendations)

        score = readiness["production_readiness_score"]
        deployment_ready = (
            score >= 80
            and env["critical_count"] == 0
            and checklist["blocked_count"] == 0
            and len(security.get("critical_findings") or []) == 0
        )

        return {
            "readiness_score": score,
            "deployment_ready": deployment_ready,
            "blockers": blockers[:10],
            "warnings": warnings[:10],
            "recommendations": recommendations[:8],
            "next_action": next_action,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def _tenant_isolation_snapshot(db: AsyncSession) -> dict[str, Any]:
        tenant_count = int(await db.scalar(select(func.count()).select_from(Tenant)) or 0)
        isolation_score = 70
        isolation_details = "No tenants to verify"
        isolation_ok = True
        if tenant_count > 0:
            sample = await db.execute(select(Tenant.id).limit(3))
            leaks = 0
            for row in sample.scalars():
                check = await TenantService.isolation_check(db, row)
                if not check.get("isolated"):
                    leaks += 1
            isolation_score = 95 if leaks == 0 else max(40, 95 - leaks * 20)
            isolation_details = f"{tenant_count} tenant(s) sampled; cross-tenant leaks={leaks}"
            isolation_ok = leaks == 0
        return {
            "tenant_count": tenant_count,
            "score": isolation_score,
            "details": isolation_details,
            "isolated": isolation_ok,
        }

    @staticmethod
    async def _build_readiness_from_parts(
        db: AsyncSession,
        *,
        sec: dict[str, Any],
        env: dict[str, Any],
        backups: dict[str, Any],
        monitoring: dict[str, Any],
        billing_plans: dict[str, Any],
        tenant_isolation: dict[str, Any],
    ) -> dict[str, Any]:
        rbac_checks = sec.get("security_checks") or await AdminRbacService.security_checks(db)
        if isinstance(rbac_checks, dict) and "checks" in rbac_checks:
            rbac_list = rbac_checks["checks"]
        else:
            rbac_list = rbac_checks.get("checks", []) if isinstance(rbac_checks, dict) else []

        admin_count = int(await db.scalar(select(func.count()).select_from(AdminUser)) or 0)
        auth_score = 40
        auth_details = "No platform admin users"
        if admin_count > 0:
            auth_ok = sum(
                1 for c in rbac_list
                if c.get("name") == "admin_users_exist" and c.get("status") == "ok"
            )
            auth_score = 85 if auth_ok else 65
            auth_details = f"{admin_count} admin user(s); login protection enabled"

        rbac_score = int(sec.get("readiness_score", 50))
        rbac_details = (
            f"Protected routes={sec.get('protected_route_count', 0)}, "
            f"open={sec.get('open_route_count', 0)}, "
            f"coverage={sec.get('permission_coverage_percent', 0)}%"
        )

        isolation_score = int(tenant_isolation.get("score", 70))
        isolation_details = tenant_isolation.get("details", "Tenant isolation check pending")

        plan_count = len(billing_plans.get("plans") or billing_plans.get("items") or [])
        if plan_count >= 1:
            billing_score = 90
            billing_details = f"{plan_count} subscription plan(s) configured"
        else:
            billing_score = 40
            billing_details = "No subscription plans found"

        backup_score = _clamp(
            int(round(sum(
                100 if i["status"] == "ready" else 50 if i["status"] == "warning" else 20
                for i in backups.get("items") or []
            ) / max(len(backups.get("items") or []), 1))),
        ) if backups.get("items") else 50
        backup_details = (
            f"{backups.get('ready_count', 0)}/{backups.get('total', 0)} backup checks ready"
        )

        monitoring_score = _clamp(
            int(round(sum(
                100 if i["status"] == "ready" else 50 if i["status"] == "warning" else 20
                for i in monitoring.get("items") or []
            ) / max(len(monitoring.get("items") or []), 1))),
        ) if monitoring.get("items") else 50
        monitoring_details = (
            f"{monitoring.get('ready_count', 0)}/{monitoring.get('total', 0)} monitoring checks ready"
        )

        public_https = _is_https_url(settings.PUBLIC_APP_URL)
        media_https = _is_https_url(settings.MEDIA_BASE_URL)
        if public_https and media_https:
            ssl_score = 95
            ssl_details = "PUBLIC_APP_URL and MEDIA_BASE_URL use HTTPS"
        elif public_https or media_https:
            ssl_score = 60
            ssl_details = "Partial HTTPS — configure both PUBLIC_APP_URL and MEDIA_BASE_URL"
        else:
            ssl_score = 25 if settings.APP_ENV != "production" else 15
            ssl_details = "HTTP URLs detected — TLS required for production"

        env_critical = env.get("critical_count", 0)
        env_warning = env.get("warning_count", 0)
        env_score = max(20, 100 - env_critical * 25 - env_warning * 10)
        env_details = f"Env checks: {env_critical} critical, {env_warning} warning"

        deploy_score = 50
        if settings.APP_ENV == "production":
            deploy_score += 20
        if "postgres" in (settings.DATABASE_URL or "") and "localhost" not in settings.DATABASE_URL:
            deploy_score += 15
        if not settings.DEMO_MODE:
            deploy_score += 10
        if settings.USE_S3:
            deploy_score += 5
        deploy_score = _clamp(deploy_score)
        deploy_details = (
            f"APP_ENV={settings.APP_ENV}, DEMO_MODE={settings.DEMO_MODE}, "
            f"storage={'S3' if settings.USE_S3 else 'local volume'}"
        )

        raw = {
            "authentication": (auth_score, auth_details),
            "rbac": (rbac_score, rbac_details),
            "tenant_isolation": (isolation_score, isolation_details),
            "billing": (billing_score, billing_details),
            "backups": (backup_score, backup_details),
            "monitoring": (monitoring_score, monitoring_details),
            "ssl_readiness": (ssl_score, ssl_details),
            "environment_configuration": (env_score, env_details),
            "deployment_configuration": (deploy_score, deploy_details),
        }
        components: list[dict[str, Any]] = []
        for key, label, weight in _READINESS_WEIGHTS:
            score, details = raw[key]
            components.append({
                "key": key,
                "label": label,
                "score": _clamp(score),
                "weight": weight,
                "status": _readiness_status(score),
                "details": details,
            })
        total_weight = sum(c["weight"] for c in components) or 1
        weighted = sum(c["score"] * c["weight"] for c in components) / total_weight
        return {
            "production_readiness_score": _clamp(int(round(weighted))),
            "components": components,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _build_checklist_from_parts(
        *,
        env: dict[str, Any],
        backups: dict[str, Any],
        monitoring: dict[str, Any],
        security: dict[str, Any],
        pilot: dict[str, Any],
        billing_plans: dict[str, Any],
        tenant_isolation: dict[str, Any],
    ) -> dict[str, Any]:
        domain_ok = not _is_localhost_url(settings.PUBLIC_APP_URL)
        ssl_ok = _is_https_url(settings.PUBLIC_APP_URL) and _is_https_url(settings.MEDIA_BASE_URL)
        backups_ok = backups.get("all_ready") or backups.get("ready_count", 0) >= 1
        monitoring_ok = monitoring.get("ready_count", 0) >= 3
        security_ok = (
            security.get("readiness_score", 0) >= 80
            and security.get("open_route_count", 0) == 0
        )
        isolation_ok = tenant_isolation.get("isolated", True)
        billing_ok = len(billing_plans.get("plans") or billing_plans.get("items") or []) >= 1
        pilot_ok = pilot.get("launch_ready", False)

        raw: dict[str, tuple[bool, str, str | None]] = {
            "domain_ready": (
                domain_ok,
                "PUBLIC_APP_URL uses production domain" if domain_ok else "PUBLIC_APP_URL still localhost",
                "Set PUBLIC_APP_URL to your production domain",
            ),
            "ssl_ready": (
                ssl_ok,
                "HTTPS configured for app and media URLs" if ssl_ok else "TLS not configured on all public URLs",
                "Configure SSL/TLS certificates for PUBLIC_APP_URL and MEDIA_BASE_URL",
            ),
            "backups_configured": (
                backups_ok,
                backups["items"][0]["message"] if backups.get("items") else "Backup status unknown",
                "Configure database backups and test restore procedure",
            ),
            "monitoring_configured": (
                monitoring_ok,
                f"{monitoring.get('ready_count', 0)}/{monitoring.get('total', 0)} monitoring checks passing",
                "Review /system/stability API health and wire external alerts",
            ),
            "admin_security_enabled": (
                security_ok,
                f"Security score {security.get('readiness_score', 0)}/100",
                "Resolve open admin routes and rotate JWT secrets",
            ),
            "tenant_isolation_verified": (
                isolation_ok,
                "Tenant isolation verified on sample tenant" if isolation_ok else "Cross-tenant leak detected",
                "Run isolation checks on /tenants",
            ),
            "billing_verified": (
                billing_ok,
                "Subscription plans available" if billing_ok else "Billing plans missing or unreachable",
                "Configure plans on /billing",
            ),
            "pilot_client_ready": (
                pilot_ok,
                f"First pilot client launch_ready={pilot_ok}",
                "Complete first pilot client preparation on /first-pilot-client",
            ),
        }

        items: list[dict[str, Any]] = []
        for key, label in _CHECKLIST_SPECS:
            ok, msg, next_action = raw[key]
            if ok:
                status = "completed"
            elif key in ("domain_ready", "ssl_ready", "backups_configured") and settings.APP_ENV != "production":
                status = "warning"
            else:
                status = "blocked"
            items.append({
                "key": key,
                "label": label,
                "status": status,
                "message": msg,
                "next_action": None if ok else next_action,
            })

        completed = sum(1 for i in items if i["status"] == "completed")
        warning = sum(1 for i in items if i["status"] == "warning")
        blocked = sum(1 for i in items if i["status"] == "blocked")
        next_action = next(
            (i["next_action"] for i in items if i["status"] == "blocked" and i.get("next_action")),
            None,
        ) or next(
            (i["next_action"] for i in items if i["status"] == "warning" and i.get("next_action")),
            None,
        )

        return {
            "items": items,
            "completed_count": completed,
            "warning_count": warning,
            "blocked_count": blocked,
            "all_ready": blocked == 0 and warning == 0,
            "next_action": next_action,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _build_summary_from_parts(
        *,
        readiness: dict[str, Any],
        env: dict[str, Any],
        checklist: dict[str, Any],
        security: dict[str, Any],
    ) -> dict[str, Any]:
        blockers = [i["label"] for i in checklist["items"] if i["status"] == "blocked"]
        for f in security.get("critical_findings") or []:
            blockers.append(f["label"])
        for c in env.get("checks") or []:
            if c["status"] == "critical":
                blockers.append(c["label"])

        warnings = [i["label"] for i in checklist["items"] if i["status"] == "warning"]
        for f in security.get("warnings") or []:
            warnings.append(f["label"])
        for c in env.get("checks") or []:
            if c["status"] == "warning":
                warnings.append(c["label"])

        recommendations = ProductionDeploymentService._build_recommendations(env, checklist, security)
        next_action = ProductionDeploymentService._next_action(blockers, recommendations)
        score = readiness["production_readiness_score"]
        deployment_ready = (
            score >= 80
            and env.get("critical_count", 0) == 0
            and checklist["blocked_count"] == 0
            and len(security.get("critical_findings") or []) == 0
        )
        return {
            "readiness_score": score,
            "deployment_ready": deployment_ready,
            "blockers": blockers[:10],
            "warnings": warnings[:10],
            "recommendations": recommendations[:8],
            "next_action": next_action,
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    def _integration_checks_from_parts(
        security: dict[str, Any],
        pilot: dict[str, Any],
        monitoring: dict[str, Any],
        errors: list[str],
    ) -> list[dict[str, Any]]:
        def _section_failed(name: str) -> bool:
            return any(err.startswith(f"{name}:") for err in errors)

        api_item = next(
            (i for i in monitoring.get("items") or [] if i.get("key") == "api_health"),
            None,
        )
        api_ok = api_item is not None and api_item.get("status") != "blocked" and not _section_failed("monitoring")

        return [
            {
                "module": "admin_security",
                "status": "ok" if not _section_failed("security") else "degraded",
                "message": (
                    "Admin security hardening data loaded"
                    if not _section_failed("security")
                    else "Admin security partial or timed out"
                ),
                "details": {"readiness_score": security.get("readiness_score", 0)},
            },
            {
                "module": "first_pilot_client",
                "status": "ok" if not _section_failed("first_pilot_client") else "degraded",
                "message": (
                    "First pilot client readiness loaded"
                    if not _section_failed("first_pilot_client")
                    else "First pilot client check partial or timed out"
                ),
                "details": {"launch_ready": pilot.get("launch_ready", False)},
            },
            {
                "module": "api_health",
                "status": "ok" if api_ok else "degraded",
                "message": (
                    api_item.get("message", "API health probes loaded")
                    if api_item
                    else "API health probe skipped or timed out"
                ),
                "details": api_item.get("details", {}) if api_item else {},
            },
        ]

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
            "admin_security",
            ProductionDeploymentService.security_readiness(db),
            "Admin security hardening data reachable",
        )
        await _probe(
            "first_pilot_client",
            FirstPilotClientService.summary(db),
            "First pilot client readiness reachable",
        )
        await _probe(
            "api_health",
            ApiHealthService.check(
                None,
                skip_paths=_API_HEALTH_SKIP,
                time_budget_sec=_API_HEALTH_BUDGET_SEC,
                per_probe_timeout_sec=_API_HEALTH_PROBE_TIMEOUT,
            ),
            "API health probes reachable",
        )
        return checks

    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        errors: list[str] = []
        overview_start = time.perf_counter()

        env, backups = await asyncio.gather(
            _timed_section(
                "environment",
                ProductionDeploymentService.environment_validation(),
                default=_default_env(),
                errors=errors,
                timeout=_SECTION_TIMEOUT,
            ),
            _timed_section(
                "backups",
                ProductionDeploymentService.backup_readiness(),
                default=_default_backups(),
                errors=errors,
                timeout=_SECTION_TIMEOUT,
            ),
        )
        security = await _timed_section(
            "security",
            ProductionDeploymentService.security_readiness(db),
            default=_default_security(),
            errors=errors,
            db=db,
            timeout=_HEAVY_SECTION_TIMEOUT,
        )
        monitoring = await _timed_section(
            "monitoring",
            ProductionDeploymentService.monitoring_readiness(db, include_api_health=False),
            default=_default_monitoring(),
            errors=errors,
            db=db,
            timeout=_HEAVY_SECTION_TIMEOUT,
        )
        pilot = await _timed_section(
            "first_pilot_client",
            FirstPilotClientService.summary(db),
            default=_default_pilot(),
            errors=errors,
            db=db,
            timeout=_HEAVY_SECTION_TIMEOUT,
        )
        billing_plans = await _timed_section(
            "billing",
            SubscriptionService.list_plans(db),
            default=_default_billing(),
            errors=errors,
            db=db,
            timeout=_HEAVY_SECTION_TIMEOUT,
        )
        tenant_isolation = await _timed_section(
            "tenant_isolation",
            ProductionDeploymentService._tenant_isolation_snapshot(db),
            default={
                "tenant_count": 0,
                "score": 70,
                "details": "Tenant isolation check skipped",
                "isolated": True,
            },
            errors=errors,
            db=db,
            timeout=_HEAVY_SECTION_TIMEOUT,
        )

        readiness = await ProductionDeploymentService._build_readiness_from_parts(
            db,
            sec=security,
            env=env,
            backups=backups,
            monitoring=monitoring,
            billing_plans=billing_plans,
            tenant_isolation=tenant_isolation,
        )
        checklist = ProductionDeploymentService._build_checklist_from_parts(
            env=env,
            backups=backups,
            monitoring=monitoring,
            security=security,
            pilot=pilot,
            billing_plans=billing_plans,
            tenant_isolation=tenant_isolation,
        )
        summary = ProductionDeploymentService._build_summary_from_parts(
            readiness=readiness,
            env=env,
            checklist=checklist,
            security=security,
        )

        blockers = summary["blockers"]
        warnings = summary["warnings"]
        elapsed_ms = int((time.perf_counter() - overview_start) * 1000)
        logger.info("%s overview complete elapsed_ms=%d section_errors=%s", MARKER, elapsed_ms, errors)

        return {
            "production_readiness_score": readiness["production_readiness_score"],
            "deployment_ready": summary["deployment_ready"],
            "environment_valid": env["valid"],
            "checklist_completed": checklist["completed_count"],
            "checklist_blocked": checklist["blocked_count"],
            "backup_ready": backups["all_ready"],
            "monitoring_ready": monitoring["all_ready"],
            "security_score": security["readiness_score"],
            "critical_finding_count": len(security.get("critical_findings") or []),
            "blocker_count": len(blockers),
            "warning_count": len(warnings),
            "readiness": readiness,
            "environment": env,
            "checklist": checklist,
            "backups": backups,
            "monitoring": monitoring,
            "security": security,
            "summary": summary,
            "integration_checks": ProductionDeploymentService._integration_checks_from_parts(
                security, pilot, monitoring, errors,
            ),
            "safety_notice": _safety_notice(),
            "implementation_complete": True,
        }

    @staticmethod
    async def refresh(db: AsyncSession) -> dict[str, Any]:
        ProductionDeploymentService._invalidate_cache()
        summary = await ProductionDeploymentService.summary(db)
        return {
            "refreshed_at": _utc_now(),
            "production_readiness_score": summary["readiness_score"],
            "deployment_ready": summary["deployment_ready"],
            "blocker_count": len(summary["blockers"]),
            "next_action": summary.get("next_action"),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def summary_widget(db: AsyncSession) -> dict[str, Any]:
        summary = await ProductionDeploymentService.summary(db)
        env = await ProductionDeploymentService.environment_validation()
        security = await ProductionDeploymentService.security_readiness(db)
        next_action = summary.get("next_action") or {}
        return {
            "production_readiness_score": summary["readiness_score"],
            "deployment_ready": summary["deployment_ready"],
            "blocker_count": len(summary["blockers"]),
            "critical_finding_count": len(security.get("critical_findings") or []),
            "environment_valid": env["valid"],
            "next_action_title": next_action.get("title"),
            "safety_notice": _safety_notice(),
        }

    @staticmethod
    async def executive_summary(db: AsyncSession) -> dict[str, Any]:
        overview = await ProductionDeploymentService.overview(db)
        return {
            "production_readiness_score": overview["production_readiness_score"],
            "deployment_ready": overview["deployment_ready"],
            "environment_valid": overview["environment_valid"],
            "checklist_completed": overview["checklist_completed"],
            "checklist_blocked": overview["checklist_blocked"],
            "security_score": overview["security_score"],
            "critical_finding_count": overview["critical_finding_count"],
            "blocker_count": overview["blocker_count"],
            "warning_count": overview["warning_count"],
            "next_action": overview["summary"].get("next_action"),
            "top_blockers": overview["summary"].get("blockers", [])[:5],
            "safety_notice": _safety_notice(),
        }
