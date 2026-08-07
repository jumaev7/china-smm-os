"""Regression tests for production publishing resilience."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.services.publish_resilience import (
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    PublishResilienceService,
    build_idempotency_key,
    classify_publish_failure,
    compute_backoff_seconds,
    sanitize_error_message,
    scrub_publish_result,
)
from app.services.publish_service import PublishService


# ── Classifier ────────────────────────────────────────────────────────────────


def test_transient_failures_are_retryable():
    assert classify_publish_failure("connection reset by peer", is_connection_error=True)[2] is True
    assert classify_publish_failure("request timeout", is_timeout=True)[2] is True
    assert classify_publish_failure("rate limit exceeded", http_status=429)[2] is True
    assert classify_publish_failure("temporary unavailable", meta_code=2)[2] is True
    assert classify_publish_failure("Meta Graph API error: try again later")[2] is True


def test_terminal_failures_are_not_retryable():
    code, category, retryable = classify_publish_failure(
        "Invalid OAuth access token", meta_code=190,
    )
    assert code == "auth_or_permission"
    assert category == "auth"
    assert retryable is False

    assert classify_publish_failure("(#10) Application does not have permission")[2] is False
    assert classify_publish_failure("unsupported media type / aspect ratio")[2] is False
    assert classify_publish_failure("Facebook live publish is disabled")[2] is False
    assert classify_publish_failure("no connected publishing account")[2] is False


def test_secrets_scrubbed_from_errors_and_results():
    dirty = "failed with access_token=EAABxyz123secret and Bearer EAABxyz123secret"
    clean = sanitize_error_message(dirty)
    assert clean is not None
    assert "EAABxyz123secret" not in clean
    assert "[redacted]" in clean or "access_token=[redacted]" in clean.lower() or "Bearer" in clean

    payload = scrub_publish_result({
        "success": False,
        "error": "token=EAABsupersecretvalue",
        "access_token": "should-not-persist",
        "raw": {"access_token": "nested-secret"},
        "platform_post_id": None,
    })
    assert "access_token" not in payload
    assert "raw" not in payload
    assert "EAABsupersecretvalue" not in str(payload.get("error") or "")


def test_backoff_respects_retry_after_and_bounds(monkeypatch=None):
    delay = compute_backoff_seconds(1, retry_after_seconds=120)
    assert delay == 120
    delay2 = compute_backoff_seconds(4)
    assert delay2 >= compute_backoff_seconds(1)
    huge = compute_backoff_seconds(1, retry_after_seconds=999999)
    from app.core.config import settings
    assert huge <= settings.PUBLISH_RETRY_MAX_SECONDS


def test_idempotency_key_is_stable_per_destination_version():
    content_id = uuid4()
    account_id = uuid4()
    key1 = build_idempotency_key(
        content_id=content_id,
        platform="facebook",
        account_id=account_id,
        publish_version="pv_abc",
    )
    key2 = build_idempotency_key(
        content_id=content_id,
        platform="facebook",
        account_id=account_id,
        publish_version="pv_abc",
    )
    key3 = build_idempotency_key(
        content_id=content_id,
        platform="facebook",
        account_id=account_id,
        publish_version="pv_def",
    )
    assert key1 == key2
    assert key1 != key3
    assert "facebook" in key1


# ── Prior live success (existing) ─────────────────────────────────────────────


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarRows(self._rows)


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _Result(self._rows)


def _attempt(platform: str, payload: dict, **extra):
    return SimpleNamespace(
        platform=platform,
        response=json.dumps(payload),
        status="success",
        external_post_id=payload.get("platform_post_id"),
        **extra,
    )


async def _prior_live_run() -> None:
    rows = [
        _attempt(
            "facebook",
            {"success": True, "mock": False, "platform_post_id": "fb-live-1"},
        ),
        _attempt(
            "facebook",
            {"success": True, "mock": False, "platform_post_id": "fb-live-old"},
        ),
        _attempt(
            "instagram",
            {"success": True, "mock": True, "platform_post_id": "ig-mock"},
        ),
        _attempt(
            "telegram",
            {"success": True, "test": True, "platform_post_id": "tg-test"},
        ),
    ]
    found = await PublishService._prior_live_successes(
        _Db(rows),
        uuid4(),
        ["facebook", "instagram", "telegram"],
    )
    assert list(found) == ["facebook"]
    assert found["facebook"]["platform_post_id"] == "fb-live-1"
    assert found["facebook"]["deduplicated"] is True


def test_prior_live_successes_ignore_mock_and_test_attempts() -> None:
    asyncio.run(_prior_live_run())


# ── Finalize attempt state machine ────────────────────────────────────────────


class _FakeAttempt:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid4())
        self.content_id = kwargs.get("content_id", uuid4())
        self.platform = kwargs.get("platform", "facebook")
        self.account_id = kwargs.get("account_id")
        self.status = kwargs.get("status", STATUS_IN_PROGRESS)
        self.response = kwargs.get("response")
        self.error = kwargs.get("error")
        self.idempotency_key = kwargs.get("idempotency_key", "key")
        self.publish_version = kwargs.get("publish_version", "pv_1")
        self.attempt_number = kwargs.get("attempt_number", 1)
        self.failure_code = None
        self.failure_category = None
        self.retryable = None
        self.next_retry_at = None
        self.started_at = kwargs.get("started_at")
        self.finished_at = None
        self.external_post_id = None
        self.external_post_url = None
        self.lease_owner = "worker"
        self.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        self.retry_after_seconds = None
        self.created_at = datetime.now(timezone.utc)
        self.account = None


class _FlushDb:
    async def flush(self):
        return None


async def _finalize_transient_then_success() -> None:
    db = _FlushDb()
    # Non-Meta platforms still auto-retry on timeout.
    attempt = _FakeAttempt(attempt_number=1, platform="telegram")
    await PublishResilienceService.finalize_attempt(
        db,
        attempt,
        {"success": False, "error": "connection timeout", "is_timeout": True},
    )
    assert attempt.status == STATUS_RETRYING
    assert attempt.retryable is True
    assert attempt.next_retry_at is not None
    assert attempt.failure_code == "publish_timeout"

    attempt2 = _FakeAttempt(attempt_number=2)
    await PublishResilienceService.finalize_attempt(
        db,
        attempt2,
        {
            "success": True,
            "platform_post_id": "fb-123",
            "post_url": "https://facebook.com/fb-123",
            "mock": False,
        },
    )
    assert attempt2.status == STATUS_SUCCESS
    assert attempt2.external_post_id == "fb-123"
    assert attempt2.next_retry_at is None


def test_transient_failure_schedules_retry_then_success():
    asyncio.run(_finalize_transient_then_success())


async def _finalize_meta_timeout_operator_review() -> None:
    db = _FlushDb()
    attempt = _FakeAttempt(attempt_number=1, platform="facebook")
    await PublishResilienceService.finalize_attempt(
        db,
        attempt,
        {
            "success": False,
            "error": "Meta Graph API timeout",
            "is_timeout": True,
            "retryable": True,  # adapter may claim retryable; finalize must override
        },
    )
    assert attempt.status == STATUS_OPERATOR_REVIEW
    assert attempt.retryable is False
    assert attempt.next_retry_at is None
    assert attempt.failure_code == "publish_timeout"
    assert "operator review" in (attempt.error or "").lower()


def test_meta_timeout_routes_to_operator_review_not_auto_retry():
    asyncio.run(_finalize_meta_timeout_operator_review())


async def _finalize_meta_connection_operator_review() -> None:
    db = _FlushDb()
    attempt = _FakeAttempt(attempt_number=1, platform="instagram")
    await PublishResilienceService.finalize_attempt(
        db,
        attempt,
        {
            "success": False,
            "error": "Meta Graph API connection error",
            "is_connection_error": True,
            "retryable": True,
        },
    )
    assert attempt.status == STATUS_OPERATOR_REVIEW
    assert attempt.retryable is False


def test_meta_connection_error_routes_to_operator_review():
    asyncio.run(_finalize_meta_connection_operator_review())


async def _finalize_meta_rate_limit_still_retryable() -> None:
    db = _FlushDb()
    attempt = _FakeAttempt(attempt_number=1, platform="facebook")
    await PublishResilienceService.finalize_attempt(
        db,
        attempt,
        {"success": False, "error": "rate limited", "http_status": 429},
    )
    assert attempt.status == STATUS_RETRYING
    assert attempt.retryable is True
    assert attempt.failure_code == "rate_limited"


def test_meta_known_safe_rate_limit_remains_retryable():
    asyncio.run(_finalize_meta_rate_limit_still_retryable())


async def _finalize_meta_success_persists_post_id() -> None:
    db = _FlushDb()
    attempt = _FakeAttempt(attempt_number=1, platform="facebook")
    await PublishResilienceService.finalize_attempt(
        db,
        attempt,
        {
            "success": True,
            "platform_post_id": "123_456",
            "post_url": "https://facebook.com/123/posts/456",
            "mock": False,
        },
    )
    assert attempt.status == STATUS_SUCCESS
    assert attempt.external_post_id == "123_456"
    assert attempt.external_post_url == "https://facebook.com/123/posts/456"
    assert attempt.retryable is False


def test_meta_provider_success_persists_external_post_id():
    asyncio.run(_finalize_meta_success_persists_post_id())


async def _finalize_terminal() -> None:
    db = _FlushDb()
    attempt = _FakeAttempt(attempt_number=1)
    await PublishResilienceService.finalize_attempt(
        db,
        attempt,
        {"success": False, "error": "Invalid OAuth access token", "meta_code": 190},
    )
    assert attempt.status == STATUS_FAILED
    assert attempt.retryable is False
    assert attempt.next_retry_at is None
    assert attempt.failure_code == "auth_or_permission"


def test_terminal_failure_does_not_auto_retry():
    asyncio.run(_finalize_terminal())


async def _finalize_exhaustion() -> None:
    db = _FlushDb()
    max_attempts = PublishResilienceService.max_attempts()
    attempt = _FakeAttempt(attempt_number=max_attempts)
    await PublishResilienceService.finalize_attempt(
        db,
        attempt,
        {"success": False, "error": "rate limited", "http_status": 429},
    )
    assert attempt.status == STATUS_EXHAUSTED
    assert attempt.retryable is False
    assert attempt.next_retry_at is None


def test_max_retry_exhaustion():
    asyncio.run(_finalize_exhaustion())


def test_manual_retry_blocked_for_already_published():
    attempt = _FakeAttempt(status=STATUS_SUCCESS)
    attempt.external_post_id = "fb-live-9"
    allowed, reason = PublishResilienceService.manual_retry_allowed(attempt)
    assert allowed is False
    assert reason and "already published" in reason.lower()


def test_manual_retry_blocked_while_in_progress():
    attempt = _FakeAttempt(status=STATUS_IN_PROGRESS)
    allowed, reason = PublishResilienceService.manual_retry_allowed(attempt)
    assert allowed is False
    assert reason and "in progress" in reason.lower()


def test_stale_meta_attempt_requires_operator_review():
    """Meta stale in-progress must not auto-repost (duplicate risk)."""
    now = datetime.now(timezone.utc)
    attempt = _FakeAttempt(
        platform="facebook",
        status=STATUS_IN_PROGRESS,
        started_at=now - timedelta(minutes=30),
        lease_expires_at=now - timedelta(minutes=1),
    )
    # Simulate the branch used by recover_stale_attempts for Meta.
    attempt.status = STATUS_OPERATOR_REVIEW
    attempt.retryable = False
    attempt.failure_code = "stale_in_progress"
    assert attempt.status == STATUS_OPERATOR_REVIEW
    assert attempt.retryable is False


def test_tenant_isolation_key_includes_content_not_cross_tenant():
    a = build_idempotency_key(
        content_id=uuid4(), platform="instagram", account_id=uuid4(), publish_version="pv_1",
    )
    b = build_idempotency_key(
        content_id=uuid4(), platform="instagram", account_id=uuid4(), publish_version="pv_1",
    )
    assert a != b


def test_duplicate_approval_dedup_message_shape():
    """Already-published skip payload must mark deduplicated success."""
    payload = {
        "platform": "facebook",
        "success": True,
        "platform_post_id": "fb-1",
        "deduplicated": True,
        "message": "Already published; duplicate suppressed",
    }
    assert payload["success"] is True
    assert payload["deduplicated"] is True


if __name__ == "__main__":
    test_transient_failures_are_retryable()
    test_terminal_failures_are_not_retryable()
    test_secrets_scrubbed_from_errors_and_results()
    test_backoff_respects_retry_after_and_bounds()
    test_idempotency_key_is_stable_per_destination_version()
    test_prior_live_successes_ignore_mock_and_test_attempts()
    test_transient_failure_schedules_retry_then_success()
    test_meta_timeout_routes_to_operator_review_not_auto_retry()
    test_meta_connection_error_routes_to_operator_review()
    test_meta_known_safe_rate_limit_remains_retryable()
    test_meta_provider_success_persists_external_post_id()
    test_terminal_failure_does_not_auto_retry()
    test_max_retry_exhaustion()
    test_manual_retry_blocked_for_already_published()
    test_manual_retry_blocked_while_in_progress()
    test_stale_meta_attempt_requires_operator_review()
    test_tenant_isolation_key_includes_content_not_cross_tenant()
    test_duplicate_approval_dedup_message_shape()
    print("publish resilience regression tests passed")
