"""Final launch readiness score — security, stability, integrations, monitoring."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.admin_rbac_service import AdminRbacService
from app.services.pilot_readiness_service import PilotReadinessService
from app.services.pilot_success_service import PilotSuccessService
from app.services.system_health_dashboard_service import SystemHealthDashboardService


def _clamp(score: int) -> int:
    return max(0, min(100, int(score)))


def _status(score: int) -> str:
    if score >= 75:
        return "ready"
    if score >= 50:
        return "warning"
    return "blocked"


class LaunchReadinessService:
    @staticmethod
    async def score(db: AsyncSession) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        components: list[dict[str, Any]] = []
        blockers: list[str] = []
        recommendations: list[str] = []

        security_checks = await AdminRbacService.security_checks(db)
        sec_score = 85
        if isinstance(security_checks, dict):
            checks = security_checks.get("checks") or []
            failed = sum(1 for c in checks if isinstance(c, dict) and c.get("status") != "pass")
            sec_score = _clamp(100 - failed * 15)
            if failed:
                blockers.append(f"{failed} admin security check(s) failing")
        components.append({
            "key": "security",
            "label": "Security",
            "score": sec_score,
            "weight": 15,
            "status": _status(sec_score),
            "details": "Admin RBAC, JWT auth, tenant isolation",
        })

        health = await SystemHealthDashboardService.overview(db)
        comp_statuses = [c["status"] for c in health["components"]]
        stability_score = 90
        if "error" in comp_statuses:
            stability_score = 40
            blockers.append("System health reports component errors")
        elif "degraded" in comp_statuses or "warning" in comp_statuses:
            stability_score = 70
        components.append({
            "key": "stability",
            "label": "Stability",
            "score": stability_score,
            "weight": 15,
            "status": _status(stability_score),
            "details": f"Overall: {health['overall_status']}",
        })

        tenant_score = 80
        components.append({
            "key": "tenant_isolation",
            "label": "Tenant Isolation",
            "score": tenant_score,
            "weight": 10,
            "status": _status(tenant_score),
            "details": "Dual-scope model (tenant_id + client_id)",
        })

        ai_ok = bool(settings.OPENAI_API_KEY)
        ai_score = 85 if ai_ok else 45
        if not ai_ok:
            recommendations.append("Configure OPENAI_API_KEY for full AI readiness")
        components.append({
            "key": "ai_readiness",
            "label": "AI Readiness",
            "score": ai_score,
            "weight": 10,
            "status": _status(ai_score),
            "details": "OpenAI GPT-4o integration",
        })

        integ_health = next(
            (c for c in health["components"] if c["key"] in ("telegram", "wechat", "whatsapp")),
            None,
        )
        integ_score = 70
        if integ_health:
            warned = sum(
                1 for c in health["components"]
                if c["key"] in ("telegram", "wechat", "whatsapp") and c["status"] != "ok"
            )
            integ_score = _clamp(100 - warned * 10)
        components.append({
            "key": "integrations",
            "label": "Integrations",
            "score": integ_score,
            "weight": 10,
            "status": _status(integ_score),
            "details": "Telegram, WeChat, WhatsApp foundations",
        })

        billing_score = 75
        components.append({
            "key": "billing",
            "label": "Billing",
            "score": billing_score,
            "weight": 10,
            "status": _status(billing_score),
            "details": "Client billing + tenant subscriptions",
        })

        monitor_score = 70
        if settings.APP_ENV == "production":
            monitor_score = 60
            recommendations.append("Wire external error tracking (Sentry) for production")
        components.append({
            "key": "monitoring",
            "label": "Monitoring",
            "score": monitor_score,
            "weight": 10,
            "status": _status(monitor_score),
            "details": "In-process diagnostics + health dashboards",
        })

        doc_score = 80
        components.append({
            "key": "documentation",
            "label": "Documentation",
            "score": doc_score,
            "weight": 10,
            "status": _status(doc_score),
            "details": "Admin guide, quick-start, checklists",
        })

        total_weight = sum(c["weight"] for c in components)
        readiness_score = _clamp(
            sum(c["score"] * c["weight"] for c in components) / total_weight,
        )

        pilot_success = await PilotSuccessService.dashboard(db)
        pilot_readiness_score = pilot_success["overall_score"]

        try:
            pilot_probe = await PilotReadinessService.overview(db)
            probe_score = pilot_probe.get("readiness_score", pilot_readiness_score)
            pilot_readiness_score = _clamp((pilot_readiness_score + probe_score) // 2)
        except Exception:
            pass

        if readiness_score < 60:
            blockers.append("Overall readiness below 60 — address critical components before launch")

        return {
            "readiness_score": readiness_score,
            "pilot_readiness_score": pilot_readiness_score,
            "components": components,
            "launch_blockers": blockers,
            "recommendations": recommendations,
            "refreshed_at": now,
        }
