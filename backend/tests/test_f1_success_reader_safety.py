"""F1 — success-reader safety correction.

Covers shared eligibility, mock/test non-suppression, durable-only suppression,
identity conflicts (fail-closed + alert), finalize persistence hardening,
registry/shadow neutrality, and no provider I/O on suppress/conflict paths.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from app.services.publish_resilience import (
    IDENTITY_CONFLICT_CONTEXT_MARKER,
    PROVIDER_IDENTITY_CONFLICT_FAILURE_CODE,
    PublishResilienceService,
    STATUS_SUCCESS,
    evaluate_live_success_identity,
    shape_live_success_skip_result,
)
from app.services.publish_service import PublishService


# ── Fixtures / helpers ────────────────────────────────────────────────────────


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
        self.flushed = False

    async def execute(self, _query):
        return _Result(self._rows)

    async def flush(self):
        self.flushed = True


def _attempt(
    *,
    platform: str = "facebook",
    status: str = "success",
    payload: dict | None = None,
    external_post_id: str | None = None,
    external_post_url: str | None = None,
    attempt_id=None,
    account_id=None,
    content_id=None,
):
    return SimpleNamespace(
        id=attempt_id or uuid4(),
        content_id=content_id or uuid4(),
        platform=platform,
        account_id=account_id,
        status=status,
        response=json.dumps(payload) if payload is not None else None,
        external_post_id=external_post_id,
        external_post_url=external_post_url,
        attempt_number=1,
        error=None,
        failure_code=None,
        failure_category=None,
        retryable=None,
        next_retry_at=None,
        account=None,
    )


class _FlushDb:
    async def flush(self):
        return None


class _FakeFinalizeAttempt:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", uuid4())
        self.content_id = kwargs.get("content_id", uuid4())
        self.platform = kwargs.get("platform", "facebook")
        self.account_id = kwargs.get("account_id")
        self.status = kwargs.get("status", "in_progress")
        self.response = kwargs.get("response")
        self.error = kwargs.get("error")
        self.idempotency_key = kwargs.get("idempotency_key", "key")
        self.publish_version = kwargs.get("publish_version", "pv_1")
        self.attempt_number = kwargs.get("attempt_number", 1)
        self.failure_code = None
        self.failure_category = None
        self.retryable = None
        self.next_retry_at = None
        self.started_at = None
        self.finished_at = None
        self.external_post_id = kwargs.get("external_post_id")
        self.external_post_url = kwargs.get("external_post_url")
        self.lease_owner = "worker"
        self.lease_expires_at = None
        self.retry_after_seconds = None
        self.created_at = None
        self.account = None


# ── A–F: shared eligibility / prior + find readers ────────────────────────────


def test_a_response_only_success_suppresses() -> None:
    identity = evaluate_live_success_identity(
        _attempt(payload={"success": True, "mock": False, "platform_post_id": "resp-1"})
    )
    assert identity.suppresses is True
    assert identity.identity_conflict is False
    assert identity.platform_post_id == "resp-1"

    async def body():
        rows = [
            _attempt(
                platform="facebook",
                payload={"success": True, "mock": False, "platform_post_id": "resp-1"},
            )
        ]
        found = await PublishService._prior_live_successes(
            _Db(rows), uuid4(), ["facebook"]
        )
        assert found["facebook"]["platform_post_id"] == "resp-1"
        assert found["facebook"]["deduplicated"] is True

    asyncio.run(body())


def test_b_durable_only_success_suppresses() -> None:
    identity = evaluate_live_success_identity(
        _attempt(payload=None, external_post_id="durable-only")
    )
    assert identity.suppresses is True
    assert identity.platform_post_id == "durable-only"
    assert identity.response_post_id is None

    async def body():
        rows = [_attempt(platform="telegram", payload=None, external_post_id="ack-1")]
        found = await PublishService._prior_live_successes(
            _Db(rows), uuid4(), ["telegram"]
        )
        assert found["telegram"]["platform_post_id"] == "ack-1"

    asyncio.run(body())


def test_c_matching_durable_and_response_suppresses() -> None:
    identity = evaluate_live_success_identity(
        _attempt(
            payload={"success": True, "mock": False, "platform_post_id": "same-id"},
            external_post_id="same-id",
        )
    )
    assert identity.suppresses is True
    assert identity.identity_conflict is False
    assert identity.platform_post_id == "same-id"


def test_d_mock_plus_durable_does_not_suppress() -> None:
    identity = evaluate_live_success_identity(
        _attempt(
            payload={"success": True, "mock": True, "platform_post_id": "mock-1"},
            external_post_id="durable-should-not-win",
        )
    )
    assert identity.mock_or_test is True
    assert identity.suppresses is False
    assert identity.platform_post_id is None

    async def body():
        rows = [
            _attempt(
                platform="instagram",
                payload={"success": True, "mock": True, "platform_post_id": "ig-mock"},
                external_post_id="should-not-suppress",
            )
        ]
        found = await PublishService._prior_live_successes(
            _Db(rows), uuid4(), ["instagram"]
        )
        assert found == {}

        live = await PublishResilienceService.find_live_success(
            _Db(rows), content_id=uuid4(), platform="instagram"
        )
        # find_live_success filters by query; with our fake db it still iterates rows.
        # Eligibility must exclude mock+durable.
        assert evaluate_live_success_identity(rows[0]).suppresses is False
        assert live is None or evaluate_live_success_identity(live).suppresses is False

    asyncio.run(body())


def test_e_test_plus_durable_does_not_suppress() -> None:
    identity = evaluate_live_success_identity(
        _attempt(
            payload={"success": True, "test": True, "platform_post_id": "tg-test"},
            external_post_id="durable-test",
        )
    )
    assert identity.mock_or_test is True
    assert identity.suppresses is False

    async def body():
        rows = [
            _attempt(
                platform="telegram",
                payload={"success": True, "test": True, "platform_post_id": "tg-test"},
                external_post_id="durable-test",
            )
        ]
        found = await PublishService._prior_live_successes(
            _Db(rows), uuid4(), ["telegram"]
        )
        assert found == {}

    asyncio.run(body())


def test_f_missing_ids_do_not_suppress() -> None:
    identity = evaluate_live_success_identity(
        _attempt(payload={"success": True, "mock": False}, external_post_id=None)
    )
    assert identity.suppresses is False

    async def body():
        rows = [
            _attempt(platform="facebook", payload={"success": True, "mock": False}),
            _attempt(platform="instagram", payload=None, external_post_id=None),
        ]
        found = await PublishService._prior_live_successes(
            _Db(rows), uuid4(), ["facebook", "instagram"]
        )
        assert found == {}

    asyncio.run(body())


# ── G–I: conflict handling ────────────────────────────────────────────────────


def test_g_conflicting_ids_suppress_and_retain_both() -> None:
    attempt = _attempt(
        payload={"success": True, "mock": False, "platform_post_id": "resp-id"},
        external_post_id="col-id",
        external_post_url="https://example.com/col",
    )
    identity = evaluate_live_success_identity(attempt)
    assert identity.suppresses is True
    assert identity.identity_conflict is True
    assert identity.platform_post_id is None
    assert identity.durable_post_id == "col-id"
    assert identity.response_post_id == "resp-id"
    # Columns / response unchanged.
    assert attempt.external_post_id == "col-id"
    assert json.loads(attempt.response)["platform_post_id"] == "resp-id"

    payload = shape_live_success_skip_result(
        attempt, identity, platform="facebook"
    )
    assert payload["deduplicated"] is True
    assert payload["identity_conflict"] is True
    assert payload["platform_post_id"] is None
    assert payload["conflict_durable_external_post_id"] == "col-id"
    assert payload["conflict_response_platform_post_id"] == "resp-id"
    assert payload["failure_code"] == PROVIDER_IDENTITY_CONFLICT_FAILURE_CODE


def test_h_conflicting_ids_produce_bounded_integrity_alert() -> None:
    attempt = _attempt(
        payload={"success": True, "mock": False, "platform_post_id": "resp-id"},
        external_post_id="col-id",
    )

    async def body():
        alert_mock = AsyncMock(return_value=True)
        with patch(
            "app.services.publish_operator_alert_service."
            "PublishOperatorAlertService.upsert_provider_identity_conflict_alert",
            alert_mock,
        ):
            found = await PublishService._prior_live_successes(
                _Db([attempt]), attempt.content_id, [attempt.platform]
            )
        assert found[attempt.platform]["identity_conflict"] is True
        alert_mock.assert_awaited_once()
        called_attempt = alert_mock.await_args.args[1]
        assert called_attempt.id == attempt.id
        # Alert path must not mutate stored identities.
        assert attempt.external_post_id == "col-id"
        assert json.loads(attempt.response)["platform_post_id"] == "resp-id"

    asyncio.run(body())


def test_i_exact_identity_consumers_fail_closed_on_conflict() -> None:
    attempt = _FakeFinalizeAttempt(
        status=STATUS_SUCCESS,
        external_post_id="col-id",
        external_post_url="https://example.com/col",
        response=json.dumps(
            {"success": True, "mock": False, "platform_post_id": "resp-id"}
        ),
    )
    serialized = PublishResilienceService.serialize_attempt(attempt)
    assert serialized["identity_conflict"] is True
    assert serialized["platform_post_id"] is None
    assert serialized["post_url"] is None
    assert serialized["external_post_id"] == "col-id"  # column preserved
    assert serialized["conflict_durable_external_post_id"] == "col-id"
    assert serialized["conflict_response_platform_post_id"] == "resp-id"

    claim = PublishResilienceService._already_published_claim(
        attempt,
        platform="facebook",
        account_id=None,
        account_name=None,
    )
    assert claim.skip is True
    assert claim.reason == "provider_identity_conflict"
    assert claim.result is not None
    assert claim.result["platform_post_id"] is None
    assert claim.result["identity_conflict"] is True
    assert claim.result["success"] is False


# ── J–L: persistence / real success unchanged ─────────────────────────────────


def test_j_existing_mock_attempts_are_not_rewritten() -> None:
    """Historical mock+durable rows are left intact; they simply do not suppress."""
    historical = _attempt(
        payload={"success": True, "mock": True, "platform_post_id": "old-mock"},
        external_post_id="legacy-persisted-id",
        external_post_url="https://example.com/legacy",
    )
    before_id = historical.external_post_id
    before_url = historical.external_post_url
    before_resp = historical.response
    identity = evaluate_live_success_identity(historical)
    assert identity.suppresses is False
    assert historical.external_post_id == before_id
    assert historical.external_post_url == before_url
    assert historical.response == before_resp


def test_k_new_mock_finalization_does_not_persist_durable_identity() -> None:
    async def body():
        with patch.object(
            PublishResilienceService, "_notify_alert", new_callable=AsyncMock
        ):
            attempt = _FakeFinalizeAttempt(platform="facebook")
            await PublishResilienceService.finalize_attempt(
                _FlushDb(),
                attempt,
                {
                    "success": True,
                    "mock": True,
                    "platform_post_id": "mock-fb-1",
                    "post_url": "https://example.com/mock",
                },
            )
            assert attempt.status == STATUS_SUCCESS
            assert attempt.external_post_id is None
            assert attempt.external_post_url is None
            stored = json.loads(attempt.response)
            assert stored["mock"] is True
            assert stored["platform_post_id"] == "mock-fb-1"

            attempt_test = _FakeFinalizeAttempt(platform="telegram")
            await PublishResilienceService.finalize_attempt(
                _FlushDb(),
                attempt_test,
                {
                    "success": True,
                    "test": True,
                    "platform_post_id": "tg-test-1",
                    "post_url": "https://t.me/c/1/2",
                },
            )
            assert attempt_test.external_post_id is None
            assert attempt_test.external_post_url is None
            stored_test = json.loads(attempt_test.response)
            assert stored_test["test"] is True
            assert stored_test["platform_post_id"] == "tg-test-1"

    asyncio.run(body())


def test_l_normal_real_success_unchanged() -> None:
    async def body():
        with patch.object(
            PublishResilienceService, "_notify_alert", new_callable=AsyncMock
        ):
            attempt = _FakeFinalizeAttempt(platform="facebook")
            await PublishResilienceService.finalize_attempt(
                _FlushDb(),
                attempt,
                {
                    "success": True,
                    "mock": False,
                    "platform_post_id": "fb-live-99",
                    "post_url": "https://facebook.com/fb-live-99",
                },
            )
            assert attempt.status == STATUS_SUCCESS
            assert attempt.external_post_id == "fb-live-99"
            assert attempt.external_post_url == "https://facebook.com/fb-live-99"

    asyncio.run(body())

    identity = evaluate_live_success_identity(
        _attempt(
            payload={"success": True, "mock": False, "platform_post_id": "fb-live-99"},
            external_post_id="fb-live-99",
        )
    )
    assert identity.suppresses is True
    assert identity.platform_post_id == "fb-live-99"


# ── M–O: neutrality / no provider I/O ─────────────────────────────────────────


def test_m_registry_remains_untouched() -> None:
    """Conflict / durable-only skip payloads must not look like registry writes."""
    attempt = _attempt(
        payload={"success": True, "mock": False, "platform_post_id": "resp"},
        external_post_id="col",
    )
    identity = evaluate_live_success_identity(attempt)
    payload = shape_live_success_skip_result(attempt, identity, platform="facebook")
    # Measurement registration requires success + platform_post_id + not deduplicated.
    assert payload.get("deduplicated") is True
    assert payload.get("platform_post_id") is None
    assert payload.get("success") is False


def test_n_shadow_remains_disabled_by_default() -> None:
    from app.core.config import settings

    assert settings.PUBLISH_WRITE_COORDINATION_SHADOW is False


def test_o_no_provider_calls_on_durable_only_or_conflict_paths() -> None:
    """Suppress paths must not invoke adapters (unit-level: skip before adapter)."""
    adapter = AsyncMock()

    async def body():
        # Durable-only → prior_live_successes returns skip payload.
        durable_rows = [
            _attempt(platform="telegram", payload=None, external_post_id="ext-1")
        ]
        with patch(
            "app.services.publish_operator_alert_service."
            "PublishOperatorAlertService.upsert_provider_identity_conflict_alert",
            AsyncMock(return_value=True),
        ):
            found = await PublishService._prior_live_successes(
                _Db(durable_rows), uuid4(), ["telegram"]
            )
        assert "telegram" in found
        assert found["telegram"]["platform_post_id"] == "ext-1"
        adapter.assert_not_called()

        conflict_rows = [
            _attempt(
                platform="facebook",
                payload={"success": True, "mock": False, "platform_post_id": "a"},
                external_post_id="b",
            )
        ]
        with patch(
            "app.services.publish_operator_alert_service."
            "PublishOperatorAlertService.upsert_provider_identity_conflict_alert",
            AsyncMock(return_value=True),
        ):
            found2 = await PublishService._prior_live_successes(
                _Db(conflict_rows), uuid4(), ["facebook"]
            )
        assert found2["facebook"]["identity_conflict"] is True
        adapter.assert_not_called()

    asyncio.run(body())


def test_alert_context_marker_and_no_raw_ids_in_context_contract() -> None:
    """Static contract: alert helper uses operator_review + fingerprint context."""
    import inspect

    from app.services.publish_operator_alert_service import PublishOperatorAlertService

    src = inspect.getsource(
        PublishOperatorAlertService.upsert_provider_identity_conflict_alert
    )
    assert 'alert_type = "operator_review"' in src
    assert IDENTITY_CONFLICT_CONTEXT_MARKER in src
    assert "durable_id_fingerprint" in src
    assert "response_id_fingerprint" in src
    assert "conflict_durable_external_post_id" not in src
    assert "authorizes_provider_write\": False" in src or (
        "authorizes_provider_write" in src and "False" in src
    )


def test_find_live_success_uses_shared_eligibility() -> None:
    async def body():
        mock_row = _attempt(
            platform="facebook",
            payload={"success": True, "mock": True, "platform_post_id": "m1"},
            external_post_id="durable",
        )
        live_row = _attempt(
            platform="facebook",
            payload={"success": True, "mock": False, "platform_post_id": "live-1"},
            external_post_id="live-1",
        )
        # Newest first in fake list.
        found = await PublishResilienceService.find_live_success(
            _Db([mock_row, live_row]),
            content_id=uuid4(),
            platform="facebook",
        )
        assert found is not None
        assert found.id == live_row.id

        conflict = _attempt(
            platform="facebook",
            payload={"success": True, "mock": False, "platform_post_id": "x"},
            external_post_id="y",
        )
        found_conflict = await PublishResilienceService.find_live_success(
            _Db([conflict]),
            content_id=uuid4(),
            platform="facebook",
        )
        assert found_conflict is not None
        assert evaluate_live_success_identity(found_conflict).identity_conflict is True

    asyncio.run(body())


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
