"""Focused Phase 4 webhook contract checks (run with PYTHONPATH=backend)."""
from __future__ import annotations

import hashlib
import hmac
import json
import asyncio
from uuid import uuid4
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal, ensure_listening_schema
from app.models.listening import (
    TenantListeningProject,
    TenantListeningSource,
    TenantListeningWebhookEvent,
)
from app.models.tenant import Tenant

from app.services.listening.webhook_service import (
    MAX_WEBHOOK_BYTES,
    _event_key,
    _safe_summary,
    verify_challenge,
    verify_signature,
    enqueue_payload,
    process_due_events,
    replay_event,
)


async def database_contracts() -> None:
    await ensure_listening_schema()
    tenant_id, project_id = uuid4(), uuid4()
    source_ids = [uuid4(), uuid4()]
    async with AsyncSessionLocal() as db:
        db.add(Tenant(id=tenant_id, company_name="Phase 4 webhook test"))
        await db.commit()
        db.add(TenantListeningProject(id=project_id, tenant_id=tenant_id, name="Webhook test"))
        await db.commit()
        for source_id, source_type in zip(source_ids, ("facebook_page_comments", "facebook_page_mentions")):
            db.add(TenantListeningSource(
                id=source_id, tenant_id=tenant_id, project_id=project_id,
                source_type=source_type, source_key=source_type,
                display_name=source_type, provider_resource_ref="page-phase4",
                capability_status="live", is_enabled=True,
            ))
        await db.commit()
        payload = {"object": "page", "entry": [{"id": "page-phase4", "changes": [{
            "field": "feed", "value": {"item": "comment", "verb": "add", "comment_id": "c1", "message": "do not store"},
        }]}]}
        first = await enqueue_payload(db, payload)
        await db.commit()
        second = await enqueue_payload(db, payload)
        await db.commit()
        assert first == {"accepted": 2, "duplicates": 0, "unrouted": 0}
        assert second == {"accepted": 0, "duplicates": 2, "unrouted": 0}
        rows = list((await db.execute(select(TenantListeningWebhookEvent).where(
            TenantListeningWebhookEvent.tenant_id == tenant_id,
        ))).scalars().all())
        assert len(rows) == 2
        replay_event_id = rows[0].id
        assert all("message" not in json.dumps(row.payload_summary_json) for row in rows)
        assert {row.source_id for row in rows} == set(source_ids)
        fake_sync = AsyncMock(return_value=SimpleNamespace(id=uuid4()))
        with patch("app.services.listening.webhook_service.sync_live_source", new=fake_sync):
            outcomes = await process_due_events(db, tenant_id=tenant_id)
        assert len(outcomes) == 2 and all(item["status"] == "succeeded" for item in outcomes)
        assert fake_sync.await_count == 2
        replayed = await replay_event(db, tenant_id=tenant_id, event_id=replay_event_id)
        assert replayed is not None and replayed.status == "pending"
        assert await replay_event(db, tenant_id=uuid4(), event_id=replay_event_id) is None
        await db.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await db.commit()


def main() -> None:
    body = json.dumps({"object": "page", "entry": []}).encode()
    secret = "phase4-test-secret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    with patch("app.services.listening.webhook_service.settings.META_APP_SECRET", secret):
        assert verify_signature(body, signature)
        assert not verify_signature(body + b" ", signature)
        assert not verify_signature(body, None)

    with patch("app.services.listening.webhook_service.settings.LISTENING_META_WEBHOOK_VERIFY_TOKEN", "verify-me"):
        assert verify_challenge("subscribe", "verify-me", "123") == "123"
        assert verify_challenge("subscribe", "wrong", "123") is None

    change = {
        "field": "feed",
        "value": {
            "item": "comment", "verb": "add", "post_id": "p1", "comment_id": "c1",
            "message": "private content", "access_token": "must-not-persist",
        },
    }
    summary = _safe_summary(change)
    encoded = json.dumps(summary)
    assert "private content" not in encoded and "access_token" not in encoded
    assert _event_key("page1", "feed", change) == _event_key("page1", "feed", change)
    assert len(_event_key("page1", "feed", change)) == 64
    assert MAX_WEBHOOK_BYTES <= 1_000_000
    asyncio.run(database_contracts())
    print("PASS: Social Listening Phase 4 webhook contracts")


if __name__ == "__main__":
    main()
