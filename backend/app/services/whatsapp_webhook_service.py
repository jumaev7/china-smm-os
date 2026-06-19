"""WhatsApp Business webhook — safe placeholder until credentials are configured."""
from __future__ import annotations

import hashlib
import hmac
import logging
from typing import Any

from fastapi import HTTPException, Request

from app.core.config import settings

logger = logging.getLogger(__name__)
MARKER = "[WhatsApp Webhook]"


def whatsapp_credentials_configured() -> bool:
    return bool(
        (settings.WHATSAPP_ACCESS_TOKEN or "").strip()
        and (settings.WHATSAPP_PHONE_NUMBER_ID or "").strip()
        and (settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN or "").strip()
    )


def verify_webhook_signature(body: bytes, signature_header: str | None) -> bool:
    secret = (settings.WHATSAPP_APP_SECRET or "").strip()
    if not secret:
        return settings.APP_ENV in ("development", "test")
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", signature_header)


async def handle_verification(hub_mode: str | None, hub_verify_token: str | None, hub_challenge: str | None) -> str:
    if not whatsapp_credentials_configured():
        raise HTTPException(status_code=503, detail="WhatsApp webhook disabled — credentials not configured")
    expected = (settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN or "").strip()
    if hub_mode == "subscribe" and hub_verify_token == expected and hub_challenge:
        logger.info("%s verification succeeded", MARKER)
        return hub_challenge
    raise HTTPException(status_code=403, detail="Webhook verification failed")


async def handle_event(request: Request) -> dict[str, Any]:
    if not whatsapp_credentials_configured():
        raise HTTPException(status_code=503, detail="WhatsApp webhook disabled — credentials not configured")
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")
    # Real API processing will ingest into Communication Hub — architecture-only v1
    logger.info("%s event received (architecture-only, not processed)", MARKER)
    return {"status": "accepted", "processed": False, "architecture_only": True}
