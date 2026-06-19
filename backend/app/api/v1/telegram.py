"""
Telegram Webhook Endpoint
POST /api/v1/telegram/webhook

Register with Telegram:
  curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://yourdomain.com/api/v1/telegram/webhook"

For local dev, use ngrok:
  ngrok http 8000
  Then register the ngrok URL above.
"""
import logging

import httpx
from fastapi import APIRouter, Depends, Request, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_access import require_admin_permission
from app.core.config import settings
from app.core.database import get_db
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.telegram_service import process_update, log_telegram_debug_update
from app.services.telegram_ingestion_service import TelegramIngestionService
from app.schemas.telegram_ingestion import (
    TelegramIngestionSettingsResponse,
    TelegramIngestionSettingsUpdate,
)

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

router = APIRouter(prefix="/telegram", tags=["telegram"])


def _token_matches(x_telegram_bot_api_secret_token: str | None) -> bool:
    """
    Validate Telegram webhook secret token when TELEGRAM_WEBHOOK_SECRET is configured.
    """
    expected = (getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None) or "").strip()
    if not expected:
        if settings.APP_ENV not in ("development", "test"):
            logger.error("TELEGRAM_WEBHOOK_SECRET is required in production")
            return False
        return True
    return (x_telegram_bot_api_secret_token or "").strip() == expected


@router.post("/webhook")
async def telegram_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive Telegram updates. Telegram sends a POST with JSON body for every message.

    Returns 200 immediately (Telegram retries on non-200 for up to 24 h).
    """
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not _token_matches(secret):
        logger.warning("Telegram webhook rejected: invalid secret token")
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    if not settings.TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram webhook hit but TELEGRAM_BOT_TOKEN is not set")
        # Still return 200 to avoid Telegram retry spam
        return {"ok": True, "ignored": "bot token not configured"}

    try:
        update = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    log_telegram_debug_update(update)
    logger.debug("Telegram update received: update_id=%s", update.get("update_id"))

    try:
        result = await process_update(db, update)
    except Exception as exc:
        # Log but never crash — Telegram must get 200 or it retries forever
        logger.error("Telegram: unhandled error processing update — %s", exc, exc_info=True)
        return {"ok": True, "error": "internal error, draft may not have been created"}

    if result:
        logger.info("Telegram: processed → %s", result)
        return {"ok": True, "created": result}

    return {"ok": True, "skipped": True}


@router.get("/status")
async def telegram_status(
    _admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
):
    """Health check: shows whether the bot token is configured."""
    configured = bool(settings.TELEGRAM_BOT_TOKEN)
    admin_ids = [i.strip() for i in settings.TELEGRAM_ADMIN_ID.split(",") if i.strip()]
    return {
        "configured": configured,
        "admin_filter_active": bool(admin_ids),
        "allowed_senders": len(admin_ids) if admin_ids else "all",
        "webhook_url_hint": "POST /api/v1/telegram/webhook",
    }


@router.get("/debug_telegram_status")
async def debug_telegram_status(
    _admin: CurrentAdminUser = Depends(require_admin_permission("diagnostics.read")),
):
    """Fetch live webhook info from Telegram Bot API."""
    token = settings.TELEGRAM_BOT_TOKEN.strip()
    if not token:
        logger.warning("[Telegram Debug] debug_telegram_status: TELEGRAM_BOT_TOKEN not set")
        return {
            "configured": False,
            "webhook_path": "/api/v1/telegram/webhook",
            "error": "TELEGRAM_BOT_TOKEN is not configured",
        }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(f"{TELEGRAM_API}/bot{token}/getWebhookInfo")
            resp.raise_for_status()
            body = resp.json()
    except Exception as exc:
        logger.error("[Telegram Debug] getWebhookInfo failed: %s", exc)
        return {
            "configured": True,
            "webhook_path": "/api/v1/telegram/webhook",
            "error": str(exc),
        }

    webhook = body.get("result") or {}
    webhook_url = webhook.get("url") or ""
    logger.info("[Telegram Debug] current webhook URL: %s", webhook_url or "(not set)")

    return {
        "configured": True,
        "webhook_path": "/api/v1/telegram/webhook",
        "webhook_url": webhook_url,
        "pending_update_count": webhook.get("pending_update_count"),
        "last_error_date": webhook.get("last_error_date"),
        "last_error_message": webhook.get("last_error_message"),
        "max_connections": webhook.get("max_connections"),
        "allowed_updates": webhook.get("allowed_updates"),
    }


@router.get("/ingestion/settings", response_model=TelegramIngestionSettingsResponse)
async def get_telegram_ingestion_settings(
    db: AsyncSession = Depends(get_db),
    _admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
):
    row = await TelegramIngestionService.get_settings(db)
    return TelegramIngestionService.settings_to_dict(row)


@router.patch("/ingestion/settings", response_model=TelegramIngestionSettingsResponse)
async def update_telegram_ingestion_settings(
    data: TelegramIngestionSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: CurrentAdminUser = Depends(require_admin_permission("platform.settings")),
):
    payload = data.model_dump(exclude_unset=True)
    if "default_tenant_id" in payload and payload["default_tenant_id"] is not None:
        payload["default_tenant_id"] = payload["default_tenant_id"]
    row = await TelegramIngestionService.update_settings(db, payload)
    return TelegramIngestionService.settings_to_dict(row)
