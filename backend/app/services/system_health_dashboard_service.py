"""Extended system health dashboard — API, DB, queue, jobs, webhooks, integrations."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.app_state import uptime_seconds
from app.core.config import settings
from app.services.system_health_service import SystemHealthService


class SystemHealthDashboardService:
    @staticmethod
    async def overview(db: AsyncSession) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        components: list[dict[str, Any]] = []

        base = await SystemHealthService.health(db)
        components.append({
            "key": "api",
            "label": "API Status",
            "status": "ok" if base.get("status") == "ok" else "degraded",
            "message": f"Platform {base.get('status')} — uptime {base.get('uptime')}s",
            "details": {"uptime": base.get("uptime")},
        })
        components.append({
            "key": "database",
            "label": "Database",
            "status": "ok" if base.get("database") == "ok" else "error",
            "message": f"PostgreSQL: {base.get('database')}",
            "details": {"pool": base.get("db_pool")},
        })
        scheduler = base.get("scheduler") or {}
        sched_ok = scheduler.get("status") == "running" if isinstance(scheduler, dict) else False
        components.append({
            "key": "scheduler",
            "label": "Scheduled Jobs",
            "status": "ok" if sched_ok else "warning",
            "message": (
                f"Scheduler {scheduler.get('status', 'unknown')}"
                if isinstance(scheduler, dict)
                else str(scheduler)
            ),
            "details": scheduler if isinstance(scheduler, dict) else {},
        })
        components.append({
            "key": "queue",
            "label": "Queue Status",
            "status": "ok",
            "message": "In-process task queue operational (no external broker configured)",
            "details": {"type": "in_process", "broker": None},
        })
        components.append({
            "key": "webhooks",
            "label": "Webhook Status",
            "status": "ok",
            "message": "WhatsApp webhook endpoint registered at /api/webhooks/whatsapp",
            "details": {
                "whatsapp_webhook": "/api/webhooks/whatsapp",
                "telegram_webhook": "/api/v1/telegram/webhook",
            },
        })
        telegram = base.get("telegram_bot") or {}
        tg_ok = telegram.get("configured", False) if isinstance(telegram, dict) else False
        components.append({
            "key": "telegram",
            "label": "Telegram",
            "status": "ok" if tg_ok else "warning",
            "message": (
                "Telegram bot configured"
                if tg_ok
                else "Telegram bot not configured — set TELEGRAM_BOT_TOKEN"
            ),
            "details": telegram if isinstance(telegram, dict) else {},
        })
        wechat_configured = bool(getattr(settings, "WECHAT_APP_ID", None))
        components.append({
            "key": "wechat",
            "label": "WeChat",
            "status": "ok" if wechat_configured else "warning",
            "message": (
                "WeChat foundation ready"
                if wechat_configured
                else "WeChat not configured — foundation tables and APIs available"
            ),
            "details": {"configured": wechat_configured, "foundation": True},
        })
        whatsapp_configured = bool(settings.WHATSAPP_ACCESS_TOKEN)
        components.append({
            "key": "whatsapp",
            "label": "WhatsApp",
            "status": "ok" if whatsapp_configured else "warning",
            "message": (
                "WhatsApp Business API configured"
                if whatsapp_configured
                else "WhatsApp foundation ready — configure WHATSAPP_BUSINESS_TOKEN for live"
            ),
            "details": {"configured": whatsapp_configured, "foundation": True},
        })
        ai = base.get("ai_services") or {}
        ai_ok = ai.get("openai_configured", False) if isinstance(ai, dict) else False
        components.append({
            "key": "ai",
            "label": "AI Services",
            "status": "ok" if ai_ok else "warning",
            "message": (
                "OpenAI configured"
                if ai_ok
                else "OpenAI not configured — AI features degraded"
            ),
            "details": ai if isinstance(ai, dict) else {},
        })

        statuses = [c["status"] for c in components]
        if any(s == "error" for s in statuses):
            overall = "error"
        elif any(s == "degraded" or s == "warning" for s in statuses):
            overall = "degraded"
        else:
            overall = "ok"

        return {
            "overall_status": overall,
            "components": components,
            "refreshed_at": now,
        }
