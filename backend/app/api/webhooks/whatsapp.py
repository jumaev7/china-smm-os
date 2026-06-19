"""Public WhatsApp Business webhook — disabled unless credentials are configured."""
from fastapi import APIRouter, Query, Request

from app.services.whatsapp_webhook_service import handle_event, handle_verification

router = APIRouter(prefix="/whatsapp", tags=["whatsapp-webhook"])


@router.get("")
async def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    challenge = await handle_verification(hub_mode, hub_verify_token, hub_challenge)
    return int(challenge) if challenge.isdigit() else challenge


@router.post("")
async def whatsapp_webhook_event(request: Request):
    return await handle_event(request)
