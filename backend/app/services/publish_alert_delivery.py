"""Outbound delivery adapters for publish operator alerts (disabled by default).

Telegram delivery is enqueue-only: durable outbox rows are created when both the
global kill switch and tenant recipient settings allow it. Actual sends happen
in the Telegram alert worker. Email remains an intentional no-op stub.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.publish_operator_alert import PublishOperatorAlert
from app.services.publish_resilience import sanitize_error_message

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def delivery_enabled_any() -> bool:
    return bool(settings.PUBLISH_ALERT_TELEGRAM_ENABLED or settings.PUBLISH_ALERT_EMAIL_ENABLED)


def _within_cooldown(alert: PublishOperatorAlert) -> bool:
    cooldown = max(0, int(settings.PUBLISH_ALERT_DELIVERY_COOLDOWN_SECONDS or 0))
    if cooldown <= 0 or alert.last_delivery_at is None:
        return False
    return alert.last_delivery_at >= _utc_now() - timedelta(seconds=cooldown)


async def deliver_publish_alert(
    db: AsyncSession,
    alert: PublishOperatorAlert,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Best-effort outbound delivery orchestration. Never raises into publishing."""
    result: dict[str, Any] = {
        "telegram": "skipped",
        "email": "skipped",
        "delivered": False,
    }
    try:
        if not force and not delivery_enabled_any():
            return result
        if not force and _within_cooldown(alert):
            result["telegram"] = "cooldown"
            result["email"] = "cooldown"
            return result

        if settings.PUBLISH_ALERT_TELEGRAM_ENABLED:
            result["telegram"] = await _enqueue_telegram(db, alert)
        else:
            result["telegram"] = "disabled"

        if settings.PUBLISH_ALERT_EMAIL_ENABLED:
            result["email"] = await _deliver_email(alert)
        else:
            result["email"] = "disabled"

        # Outbox enqueue is not a completed send — do not mark last_delivery_channel
        # until the worker delivers. Track enqueue attempt time lightly.
        if result["telegram"] == "enqueued":
            alert.last_delivery_error = None
        elif result["telegram"] not in ("disabled", "skipped", "cooldown", "filtered", "misconfigured"):
            if result["telegram"].startswith("error") or result["telegram"] not in (
                "enqueued",
                "duplicate",
            ):
                alert.last_delivery_error = sanitize_error_message(str(result["telegram"]))

        await db.flush()
    except Exception:
        logger.exception(
            "[PublishAlertDelivery] unexpected failure alert_id=%s",
            getattr(alert, "id", None),
        )
        try:
            alert.last_delivery_error = "delivery_exception"
            await db.flush()
        except Exception:
            pass
        result["error"] = "delivery_exception"
    return result


async def _enqueue_telegram(db: AsyncSession, alert: PublishOperatorAlert) -> str:
    """Enqueue durable Telegram outbox row. Never calls Telegram API here."""
    try:
        from app.services.publish_alert_telegram_outbox_service import (
            PublishAlertTelegramOutboxService,
        )

        row = await PublishAlertTelegramOutboxService.enqueue_for_alert(db, alert)
        if row is None:
            # Distinguishing filtered vs duplicate is not critical for callers.
            return "filtered_or_duplicate"
        return "enqueued"
    except Exception as exc:
        logger.warning(
            "[PublishAlertDelivery] telegram enqueue error alert_id=%s detail=%s",
            getattr(alert, "id", None),
            sanitize_error_message(str(exc)),
        )
        return sanitize_error_message(str(exc)) or "enqueue_failed"


async def _deliver_email(alert: PublishOperatorAlert) -> str:
    """Email adapter stub — no SMTP stack exists; never sends."""
    logger.info(
        "[PublishAlertDelivery] email adapter disabled/stub alert_id=%s severity=%s (no SMTP)",
        alert.id,
        alert.severity,
    )
    return "stub_no_smtp"
