"""Additional claim / stale-recovery resilience regressions."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.publish_resilience import (
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    PublishResilienceService,
)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows=None, one=None):
        self._rows = rows or []
        self._one = one

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._one


class _StaleDb:
    """Minimal async session stand-in for recover_stale_attempts."""

    def __init__(self, attempts):
        self.attempts = attempts
        self.flushed = False

    async def execute(self, query):
        # find_live_success / recover query — return matching in_progress rows
        return _Result(rows=list(self.attempts))

    async def scalars(self, query):
        return _Scalars(list(self.attempts))

    async def flush(self):
        self.flushed = True


async def _stale_meta_to_operator_review() -> None:
    now = datetime.now(timezone.utc)
    attempt = SimpleNamespace(
        id=uuid4(),
        content_id=uuid4(),
        platform="facebook",
        status=STATUS_IN_PROGRESS,
        idempotency_key="c:facebook:a:pv",
        started_at=now - timedelta(minutes=30),
        lease_expires_at=now - timedelta(minutes=1),
        created_at=now - timedelta(minutes=30),
        error=None,
        failure_code=None,
        failure_category=None,
        retryable=None,
        next_retry_at=None,
        finished_at=None,
        lease_owner="worker",
        attempt_number=1,
        external_post_id=None,
    )
    db = _StaleDb([attempt])

    # Patch find_live_success to return None (no confirmed post).
    original = PublishResilienceService.find_live_success

    async def _none(*_a, **_k):
        return None

    PublishResilienceService.find_live_success = staticmethod(_none)  # type: ignore
    try:
        recovered = await PublishResilienceService.recover_stale_attempts(db)
    finally:
        PublishResilienceService.find_live_success = original  # type: ignore

    assert recovered == 1
    assert attempt.status == STATUS_OPERATOR_REVIEW
    assert attempt.retryable is False
    assert attempt.failure_code == "stale_in_progress"
    assert "operator review" in (attempt.error or "").lower()


def test_worker_restart_stale_meta_goes_to_operator_review():
    asyncio.run(_stale_meta_to_operator_review())


async def _stale_telegram_safe_retry() -> None:
    now = datetime.now(timezone.utc)
    attempt = SimpleNamespace(
        id=uuid4(),
        content_id=uuid4(),
        platform="telegram",
        status=STATUS_IN_PROGRESS,
        idempotency_key="c:telegram:a:pv",
        started_at=now - timedelta(minutes=30),
        lease_expires_at=now - timedelta(minutes=1),
        created_at=now - timedelta(minutes=30),
        error=None,
        failure_code=None,
        failure_category=None,
        retryable=None,
        next_retry_at=None,
        finished_at=None,
        lease_owner="worker",
        attempt_number=1,
        external_post_id=None,
    )
    db = _StaleDb([attempt])
    original = PublishResilienceService.find_live_success

    async def _none(*_a, **_k):
        return None

    PublishResilienceService.find_live_success = staticmethod(_none)  # type: ignore
    try:
        recovered = await PublishResilienceService.recover_stale_attempts(db)
    finally:
        PublishResilienceService.find_live_success = original  # type: ignore

    assert recovered == 1
    assert attempt.status == STATUS_RETRYING
    assert attempt.retryable is True
    assert attempt.next_retry_at is not None


def test_worker_restart_stale_telegram_schedules_safe_retry():
    asyncio.run(_stale_telegram_safe_retry())


async def _stale_after_success_closes_claim() -> None:
    now = datetime.now(timezone.utc)
    attempt = SimpleNamespace(
        id=uuid4(),
        content_id=uuid4(),
        platform="facebook",
        status=STATUS_IN_PROGRESS,
        idempotency_key="c:facebook:a:pv",
        started_at=now - timedelta(minutes=30),
        lease_expires_at=now - timedelta(minutes=1),
        created_at=now - timedelta(minutes=30),
        error=None,
        failure_code=None,
        failure_category=None,
        retryable=None,
        next_retry_at=None,
        finished_at=None,
        lease_owner="worker",
        attempt_number=2,
        external_post_id=None,
    )
    prior = SimpleNamespace(
        id=uuid4(),
        status=STATUS_SUCCESS,
        external_post_id="fb-done",
    )
    db = _StaleDb([attempt])
    original = PublishResilienceService.find_live_success

    async def _prior(*_a, **_k):
        return prior

    PublishResilienceService.find_live_success = staticmethod(_prior)  # type: ignore
    try:
        recovered = await PublishResilienceService.recover_stale_attempts(db)
    finally:
        PublishResilienceService.find_live_success = original  # type: ignore

    assert recovered == 1
    assert attempt.status == STATUS_FAILED
    assert attempt.retryable is False
    assert attempt.failure_code == "stale_after_success"


def test_already_published_destination_closes_stale_claim():
    asyncio.run(_stale_after_success_closes_claim())


def test_two_workers_active_claim_detection():
    """Active unexpired lease must be treated as concurrent claim."""
    now = datetime.now(timezone.utc)
    active = SimpleNamespace(
        id=uuid4(),
        status=STATUS_IN_PROGRESS,
        lease_expires_at=now + timedelta(minutes=4),
    )

    class _Db:
        async def execute(self, _q):
            return _Result(one=active)

    async def _run():
        found = await PublishResilienceService.find_active_claim(
            _Db(), "c:facebook:a:pv", now=now,
        )
        assert found is active

        expired = SimpleNamespace(
            id=uuid4(),
            status=STATUS_IN_PROGRESS,
            lease_expires_at=now - timedelta(seconds=1),
        )

        class _Db2:
            async def execute(self, _q):
                return _Result(one=expired)

        assert await PublishResilienceService.find_active_claim(
            _Db2(), "c:facebook:a:pv", now=now,
        ) is None

    asyncio.run(_run())


if __name__ == "__main__":
    test_worker_restart_stale_meta_goes_to_operator_review()
    test_worker_restart_stale_telegram_schedules_safe_retry()
    test_already_published_destination_closes_stale_claim()
    test_two_workers_active_claim_detection()
    print("publish claim/stale resilience tests passed")
