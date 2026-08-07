"""Public Meta webhook for Social Listening notifications."""
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.listening.webhook_service import MAX_WEBHOOK_BYTES, enqueue_payload, verify_challenge, verify_signature

router = APIRouter(prefix="/meta-listening", tags=["listening-webhook"])


@router.get("")
async def verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    challenge = verify_challenge(hub_mode, hub_verify_token, hub_challenge)
    if challenge is None:
        raise HTTPException(status_code=403, detail="Webhook verification failed")
    return int(challenge) if challenge.isdigit() else challenge


@router.post("")
async def receive(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload too large")
    if not verify_signature(body, request.headers.get("x-hub-signature-256")):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    counts = await enqueue_payload(db, payload)
    await db.commit()
    return {"status": "accepted", **counts}
