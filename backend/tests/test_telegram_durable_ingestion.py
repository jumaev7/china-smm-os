"""HIGH-2: Telegram durable ingestion — claim after success, reclaimable leases."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.telegram_group_agent_service import (
    claim_update,
    is_update_already_processed,
    mark_update_processed,
)
from app.services.telegram_webhook_queue_service import TelegramWebhookQueueService


class _GetDb:
    """Minimal async session for processed-update helpers."""

    def __init__(self):
        self.rows: dict[int, object] = {}
        self.added: list[object] = []

    async def get(self, model, key):
        return self.rows.get(key)

    def add(self, obj):
        self.added.append(obj)
        update_id = getattr(obj, "update_id", None)
        if update_id is not None:
            self.rows[update_id] = obj

    async def flush(self):
        return None


async def _claim_does_not_permanently_mark() -> None:
    db = _GetDb()
    assert await claim_update(db, 101) is True
    assert await is_update_already_processed(db, 101) is False
    assert db.added == []

    await mark_update_processed(db, 101)
    assert await is_update_already_processed(db, 101) is True
    assert await claim_update(db, 101) is False


def test_claim_update_no_longer_permanently_marks_before_work():
    asyncio.run(_claim_does_not_permanently_mark())


async def _duplicate_update_id_safe() -> None:
    db = _GetDb()
    await mark_update_processed(db, 55)
    assert await claim_update(db, 55) is False
    # Second mark is a no-op
    await mark_update_processed(db, 55)
    assert len(db.added) == 1


def test_duplicate_update_id_remains_safe_after_success_mark():
    asyncio.run(_duplicate_update_id_safe())


class _QueueRow:
    def __init__(self, **kwargs):
        now = datetime.now(timezone.utc)
        self.id = kwargs.get("id", uuid4())
        self.update_id = kwargs.get("update_id", 1)
        self.payload = kwargs.get("payload", {"update_id": 1})
        self.status = kwargs.get("status", "pending")
        self.attempts = kwargs.get("attempts", 0)
        self.available_at = kwargs.get("available_at", now - timedelta(seconds=1))
        self.lease_owner = kwargs.get("lease_owner")
        self.lease_expires_at = kwargs.get("lease_expires_at")
        self.last_error = None
        self.processed_at = None
        self.created_at = kwargs.get("created_at", now - timedelta(minutes=1))
        self.updated_at = now


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _QueueDb:
    def __init__(self, rows):
        self.rows = rows
        self.by_id = {r.id: r for r in rows}

    async def scalars(self, _query):
        return _Scalars(list(self.rows))

    async def get(self, _model, key):
        return self.by_id.get(key)

    async def flush(self):
        return None


async def _stale_processing_reclaim() -> None:
    now = datetime.now(timezone.utc)
    row = _QueueRow(
        status="processing",
        attempts=1,
        lease_owner="dead-worker",
        lease_expires_at=now - timedelta(seconds=5),
        payload={"update_id": 99, "message": {"text": "hi"}},
    )
    db = _QueueDb([row])
    claimed = await TelegramWebhookQueueService.claim_batch(
        db, worker_id="new-worker", batch_size=5, lease_seconds=180,
    )
    assert len(claimed) == 1
    assert claimed[0][0] == row.id
    assert row.status == "processing"
    assert row.lease_owner == "new-worker"
    assert row.attempts == 2
    assert row.lease_expires_at > now


def test_stale_processing_lease_is_reclaimable():
    asyncio.run(_stale_processing_reclaim())


async def _mark_completed_and_failed() -> None:
    now = datetime.now(timezone.utc)
    ok = _QueueRow(status="processing", lease_owner="w1", attempts=1)
    bad = _QueueRow(status="processing", lease_owner="w1", attempts=1)
    db = _QueueDb([ok, bad])

    await TelegramWebhookQueueService.mark_completed(db, ok.id, worker_id="w1")
    assert ok.status == "completed"
    assert ok.processed_at is not None
    assert ok.lease_owner is None

    await TelegramWebhookQueueService.mark_failed(
        db, bad.id, worker_id="w1", error=RuntimeError("boom"),
    )
    assert bad.status == "retry"
    assert bad.last_error == "RuntimeError"
    assert bad.lease_owner is None
    assert bad.available_at > now


def test_successful_and_failed_processing_states():
    asyncio.run(_mark_completed_and_failed())


async def _crash_after_claim_leaves_no_processed_row() -> None:
    """Simulate worker crash after queue claim but before success mark."""
    db = _GetDb()
    update_id = 777
    # Queue claim would have happened separately; process_update starts:
    assert await claim_update(db, update_id) is True
    # Crash before mark_update_processed — no durable processed row.
    assert await is_update_already_processed(db, update_id) is False
    # Reclaim path can process again:
    assert await claim_update(db, update_id) is True
    await mark_update_processed(db, update_id)
    assert await claim_update(db, update_id) is False


def test_worker_crash_after_claim_does_not_lose_update():
    asyncio.run(_crash_after_claim_leaves_no_processed_row())


async def _retry_does_not_double_mark() -> None:
    db = _GetDb()
    await mark_update_processed(db, 42)
    # Content dedupe is handled by telegram_message_id; processed table blocks re-entry.
    assert await claim_update(db, 42) is False


def test_retry_after_success_does_not_reprocess():
    asyncio.run(_retry_does_not_double_mark())


if __name__ == "__main__":
    test_claim_update_no_longer_permanently_marks_before_work()
    test_duplicate_update_id_remains_safe_after_success_mark()
    test_stale_processing_lease_is_reclaimable()
    test_successful_and_failed_processing_states()
    test_worker_crash_after_claim_does_not_lose_update()
    test_retry_after_success_does_not_reprocess()
    print("telegram durable ingestion tests passed")
