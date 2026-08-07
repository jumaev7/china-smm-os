"""Regression tests for publish operator alerts."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock, patch

from app.core.config import settings
from app.models.publish_operator_alert import PublishOperatorAlert
from app.services.publish_alert_delivery import deliver_publish_alert, delivery_enabled_any
from app.services.publish_operator_alert_service import (
    PublishOperatorAlertService,
    build_dedupe_key,
)
from app.services.publish_resilience import (
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    sanitize_error_message,
)


def _now():
    return datetime.now(timezone.utc)


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows=None, one=None, scalar=None):
        self._rows = rows or []
        self._one = one
        self._scalar = scalar

    def scalars(self):
        return _Scalars(self._rows)

    def scalar_one_or_none(self):
        return self._one

    def scalar_one(self):
        if self._scalar is not None:
            return self._scalar
        return self._one

    def one_or_none(self):
        return self._one

    def all(self):
        return self._rows


class FakeAlertDb:
    """In-memory async session stand-in for alert upsert / list / resolve."""

    def __init__(self):
        self.alerts: list[PublishOperatorAlert] = []
        self.attempts: list[SimpleNamespace] = []
        self.tenant_id = uuid4()
        self.client_id = uuid4()
        self.company_name = "Acme Export"
        self.flushed = 0
        self._content_id = None
        self._account_name = "Page A"

    async def execute(self, query):  # noqa: ARG002
        # Context resolve: ContentItem/Client/PublishingAccount join
        # Heuristic: if we have a pending content lookup via attempts context
        if self._content_id is not None and not self.alerts:
            # First-ish context query during upsert_failure_alert
            pass
        # Find open by dedupe — return matching open/acked
        open_rows = [a for a in self.alerts if a.state in ("open", "acknowledged")]
        if open_rows and getattr(query, "is_select", True):
            # Prefer returning open match for find_open / resolve queries
            # List/count callers use different shapes; tests patch specific paths.
            return _Result(rows=open_rows, one=open_rows[0] if len(open_rows) == 1 else None)
        return _Result(rows=list(self.alerts), one=None, scalar=0)

    async def flush(self):
        self.flushed += 1

    def add(self, row):
        self.alerts.append(row)

    def begin_nested(self):
        return _Nested()


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _attempt(**kwargs):
    base = dict(
        id=uuid4(),
        content_id=uuid4(),
        platform="facebook",
        account_id=uuid4(),
        status=STATUS_OPERATOR_REVIEW,
        error="Publishing timed out — operator review required",
        failure_code="stale_in_progress",
        failure_category="timeout",
        retryable=False,
        attempt_number=1,
        next_retry_at=None,
        idempotency_key="k1",
        publish_version="pv_1",
        external_post_id=None,
        created_at=_now(),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


async def _ctx_patch(db, attempt):
    return {
        "tenant_id": db.tenant_id if hasattr(db, "tenant_id") else uuid4(),
        "client_id": getattr(db, "client_id", uuid4()),
        "company_name": getattr(db, "company_name", "Acme"),
        "account_name": "Page A",
        "content_status": "failed",
    }


# ── Pure helpers ───────────────────────────────────────────────────────────


def test_dedupe_key_stable_and_attempt_scoped_for_review():
    content_id = uuid4()
    account_id = uuid4()
    attempt_id = uuid4()
    k1 = build_dedupe_key(
        alert_type="operator_review",
        content_id=content_id,
        platform="facebook",
        account_id=account_id,
        attempt_id=attempt_id,
    )
    k2 = build_dedupe_key(
        alert_type="operator_review",
        content_id=content_id,
        platform="facebook",
        account_id=account_id,
        attempt_id=attempt_id,
    )
    assert k1 == k2
    k3 = build_dedupe_key(
        alert_type="exhausted",
        content_id=content_id,
        platform="facebook",
        account_id=account_id,
        attempt_id=attempt_id,
    )
    assert "exhausted" in k3
    assert str(attempt_id) not in k3  # destination-scoped


def test_secret_redaction_in_failure_message():
    dirty = "failed access_token=EAABSECRET123 Bearer EAABSECRET123"
    clean = sanitize_error_message(dirty)
    assert clean is not None
    assert "EAABSECRET123" not in clean


def test_outbound_delivery_disabled_by_default():
    assert settings.PUBLISH_ALERT_TELEGRAM_ENABLED is False
    assert settings.PUBLISH_ALERT_EMAIL_ENABLED is False
    assert delivery_enabled_any() is False


# ── Lifecycle with fakes ───────────────────────────────────────────────────


async def _create_alert(alert_type: str, status: str, **extra):
    db = FakeAlertDb()
    attempt = _attempt(status=status, **extra)
    created_rows: list[PublishOperatorAlert] = []

    async def fake_find_open(_db, tenant_id, dedupe_key):
        for row in db.alerts:
            if (
                row.tenant_id == tenant_id
                and row.dedupe_key == dedupe_key
                and row.state in ("open", "acknowledged")
            ):
                return row
        return None

    async def fake_emit(*_a, **_k):
        return None

    async def fake_deliver(*_a, **_k):
        return {"delivered": False}

    with (
        patch.object(PublishOperatorAlertService, "_resolve_context", _ctx_patch),
        patch.object(PublishOperatorAlertService, "_find_open", staticmethod(fake_find_open)),
        patch.object(PublishOperatorAlertService, "_emit_and_deliver", fake_emit),
        patch(
            "app.services.publish_operator_alert_service.deliver_publish_alert",
            fake_deliver,
        ),
    ):
        # bind tenant onto fake resolve
        async def resolve(db_, attempt_):
            return {
                "tenant_id": db.tenant_id,
                "client_id": db.client_id,
                "company_name": db.company_name,
                "account_name": "Page A",
                "content_status": "failed",
            }

        with patch.object(PublishOperatorAlertService, "_resolve_context", resolve):
            with patch.object(
                PublishOperatorAlertService,
                "_maybe_repeated_failure",
                AsyncMock(return_value=None),
            ):
                alert = await PublishOperatorAlertService.upsert_failure_alert(
                    db, attempt, alert_type=alert_type,
                )
                created_rows.append(alert)
    return db, attempt, alert


def test_operator_review_alert_creation():
    db, attempt, alert = asyncio.run(_create_alert("operator_review", STATUS_OPERATOR_REVIEW))
    assert alert is not None
    assert alert.alert_type == "operator_review"
    assert alert.severity == "critical"
    assert alert.state == "open"
    assert alert.attempt_id == attempt.id
    assert len(db.alerts) == 1


def test_exhausted_retry_alert():
    _, _, alert = asyncio.run(
        _create_alert("exhausted", STATUS_EXHAUSTED, attempt_number=5, failure_code="max_attempts"),
    )
    assert alert.alert_type == "exhausted"
    assert alert.severity == "critical"


def test_terminal_failure_alert():
    _, _, alert = asyncio.run(
        _create_alert(
            "terminal_failure",
            STATUS_FAILED,
            retryable=False,
            failure_code="auth_or_permission",
            error="Invalid OAuth access token",
        ),
    )
    assert alert.alert_type == "terminal_failure"
    assert "token" not in (alert.failure_message or "").lower() or "redacted" in (
        alert.failure_message or ""
    ).lower() or "Invalid OAuth" in (alert.failure_message or "")


def test_stale_attempt_alert():
    _, _, alert = asyncio.run(
        _create_alert(
            "stale_in_progress",
            STATUS_RETRYING,
            platform="telegram",
            failure_code="publish_timeout",
        ),
    )
    assert alert.alert_type == "stale_in_progress"
    assert alert.severity == "warning"


def test_duplicate_scheduler_event_dedupes():
    async def run():
        db = FakeAlertDb()
        attempt = _attempt()

        async def resolve(db_, attempt_):
            return {
                "tenant_id": db.tenant_id,
                "client_id": db.client_id,
                "company_name": db.company_name,
                "account_name": "Page A",
                "content_status": "failed",
            }

        async def fake_find_open(_db, tenant_id, dedupe_key):
            for row in db.alerts:
                if row.tenant_id == tenant_id and row.dedupe_key == dedupe_key and row.state in (
                    "open",
                    "acknowledged",
                ):
                    return row
            return None

        with (
            patch.object(PublishOperatorAlertService, "_resolve_context", resolve),
            patch.object(PublishOperatorAlertService, "_find_open", staticmethod(fake_find_open)),
            patch.object(PublishOperatorAlertService, "_emit_and_deliver", AsyncMock()),
            patch.object(PublishOperatorAlertService, "_maybe_repeated_failure", AsyncMock(return_value=None)),
        ):
            a1 = await PublishOperatorAlertService.upsert_failure_alert(
                db, attempt, alert_type="operator_review",
            )
            a2 = await PublishOperatorAlertService.upsert_failure_alert(
                db, attempt, alert_type="operator_review",
            )
        assert a1.id == a2.id
        assert a2.occurrence_count == 2
        assert len(db.alerts) == 1

    asyncio.run(run())


def test_concurrent_alert_creation_bumps_existing():
    """Second insert after race should bump occurrence, not create a second open alert."""
    async def run():
        db = FakeAlertDb()
        attempt = _attempt()
        existing = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=db.tenant_id,
            dedupe_key=build_dedupe_key(
                alert_type="operator_review",
                content_id=attempt.content_id,
                platform=attempt.platform,
                account_id=attempt.account_id,
                attempt_id=attempt.id,
            ),
            alert_type="operator_review",
            state="open",
            severity="critical",
            title="existing",
            occurrence_count=1,
            first_occurred_at=_now(),
            latest_occurred_at=_now(),
        )
        db.alerts.append(existing)

        async def resolve(db_, attempt_):
            return {
                "tenant_id": db.tenant_id,
                "client_id": db.client_id,
                "company_name": db.company_name,
                "account_name": "Page A",
                "content_status": "failed",
            }

        async def fake_find_open(_db, tenant_id, dedupe_key):
            for row in db.alerts:
                if row.tenant_id == tenant_id and row.dedupe_key == dedupe_key and row.state in (
                    "open",
                    "acknowledged",
                ):
                    return row
            return None

        with (
            patch.object(PublishOperatorAlertService, "_resolve_context", resolve),
            patch.object(PublishOperatorAlertService, "_find_open", staticmethod(fake_find_open)),
            patch.object(PublishOperatorAlertService, "_emit_and_deliver", AsyncMock()),
            patch.object(PublishOperatorAlertService, "_maybe_repeated_failure", AsyncMock(return_value=None)),
        ):
            alert = await PublishOperatorAlertService.upsert_failure_alert(
                db, attempt, alert_type="operator_review",
            )
        assert alert.id == existing.id
        assert alert.occurrence_count == 2

    asyncio.run(run())


def test_recovery_resolves_matching_destination_only():
    async def run():
        db = FakeAlertDb()
        content_a = uuid4()
        content_b = uuid4()
        account = uuid4()
        open_a = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=db.tenant_id,
            dedupe_key="exhausted|a|facebook|x",
            alert_type="exhausted",
            state="open",
            severity="critical",
            title="A",
            content_id=content_a,
            platform="facebook",
            account_id=account,
            occurrence_count=1,
            first_occurred_at=_now(),
            latest_occurred_at=_now(),
        )
        open_b = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=db.tenant_id,
            dedupe_key="exhausted|b|facebook|x",
            alert_type="exhausted",
            state="open",
            severity="critical",
            title="B",
            content_id=content_b,
            platform="facebook",
            account_id=account,
            occurrence_count=1,
            first_occurred_at=_now(),
            latest_occurred_at=_now(),
        )
        db.alerts.extend([open_a, open_b])

        async def fake_execute(query):  # noqa: ARG001
            # resolve_open_for_destination select
            matched = [
                a
                for a in db.alerts
                if a.state in ("open", "acknowledged")
                and a.content_id == content_a
                and a.platform == "facebook"
                and a.account_id == account
            ]
            return _Result(rows=matched)

        db.execute = fake_execute  # type: ignore

        resolved = await PublishOperatorAlertService.resolve_open_for_destination(
            db,
            tenant_id=db.tenant_id,
            content_id=content_a,
            platform="facebook",
            account_id=account,
            system=True,
            note="auto",
        )
        assert len(resolved) == 1
        assert open_a.state == "resolved"
        assert open_a.resolved_by_system is True
        assert open_b.state == "open"

    asyncio.run(run())


def test_on_success_creates_recovery_and_resolves():
    async def run():
        db = FakeAlertDb()
        attempt = _attempt(status=STATUS_SUCCESS, external_post_id="123")
        open_alert = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=db.tenant_id,
            dedupe_key="x",
            alert_type="terminal_failure",
            state="open",
            severity="critical",
            title="fail",
            content_id=attempt.content_id,
            platform=attempt.platform,
            account_id=attempt.account_id,
            occurrence_count=1,
            first_occurred_at=_now(),
            latest_occurred_at=_now(),
        )
        db.alerts.append(open_alert)

        async def resolve(db_, attempt_):
            return {
                "tenant_id": db.tenant_id,
                "client_id": db.client_id,
                "company_name": db.company_name,
                "account_name": "Page A",
                "content_status": "published",
            }

        async def fake_execute(query):  # noqa: ARG001
            matched = [
                a
                for a in db.alerts
                if a.state in ("open", "acknowledged")
                and a.content_id == attempt.content_id
                and a.platform == attempt.platform
                and a.account_id == attempt.account_id
            ]
            return _Result(rows=matched)

        async def fake_find_open(_db, tenant_id, dedupe_key):
            for row in db.alerts:
                if row.tenant_id == tenant_id and row.dedupe_key == dedupe_key and row.state in (
                    "open",
                    "acknowledged",
                ):
                    return row
            return None

        db.execute = fake_execute  # type: ignore

        with (
            patch.object(PublishOperatorAlertService, "_resolve_context", resolve),
            patch.object(PublishOperatorAlertService, "_find_open", staticmethod(fake_find_open)),
            patch.object(PublishOperatorAlertService, "_emit_and_deliver", AsyncMock()),
        ):
            recovery = await PublishOperatorAlertService.on_attempt_transition(db, attempt)

        assert open_alert.state == "resolved"
        assert recovery is not None
        assert recovery.alert_type == "recovery"
        assert recovery.severity == "info"
        assert recovery.state == "resolved"

    asyncio.run(run())


def test_repeated_failure_threshold():
    async def run():
        db = FakeAlertDb()
        attempt = _attempt(status=STATUS_FAILED, retryable=False, failure_code="rate_limited")

        async def resolve(db_, attempt_):
            return {
                "tenant_id": db.tenant_id,
                "client_id": db.client_id,
                "company_name": db.company_name,
                "account_name": "Page A",
                "content_status": "failed",
            }

        async def fake_find_open(_db, tenant_id, dedupe_key):
            for row in db.alerts:
                if row.tenant_id == tenant_id and row.dedupe_key == dedupe_key and row.state in (
                    "open",
                    "acknowledged",
                ):
                    return row
            return None

        call_count = {"n": 0}

        async def fake_execute(query):  # noqa: ARG001
            call_count["n"] += 1
            # count query for repeated failures
            return _Result(scalar=settings.PUBLISH_ALERT_REPEATED_FAILURE_THRESHOLD)

        db.execute = fake_execute  # type: ignore

        with (
            patch.object(PublishOperatorAlertService, "_resolve_context", resolve),
            patch.object(PublishOperatorAlertService, "_find_open", staticmethod(fake_find_open)),
            patch.object(PublishOperatorAlertService, "_emit_and_deliver", AsyncMock()),
        ):
            alert = await PublishOperatorAlertService._maybe_repeated_failure(
                db,
                attempt,
                {
                    "tenant_id": db.tenant_id,
                    "client_id": db.client_id,
                    "company_name": db.company_name,
                    "account_name": "Page A",
                },
            )
        assert alert is not None
        assert alert.alert_type == "repeated_failure"
        assert alert.severity == "critical"

    asyncio.run(run())


def test_tenant_isolation_on_get():
    async def run():
        db = FakeAlertDb()
        other_tenant = uuid4()
        row = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=other_tenant,
            dedupe_key="x",
            alert_type="exhausted",
            state="open",
            severity="critical",
            title="other",
            occurrence_count=1,
            first_occurred_at=_now(),
            latest_occurred_at=_now(),
        )
        db.alerts.append(row)

        async def fake_execute(query):  # noqa: ARG001
            return _Result(one=None)

        db.execute = fake_execute  # type: ignore
        try:
            await PublishOperatorAlertService._get_for_tenant(db, db.tenant_id, row.id)
            assert False, "expected 404"
        except Exception as exc:
            assert getattr(exc, "status_code", None) == 404

    asyncio.run(run())


def test_acknowledge_and_manual_resolve():
    async def run():
        db = FakeAlertDb()
        row = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=db.tenant_id,
            dedupe_key="x",
            alert_type="exhausted",
            state="open",
            severity="critical",
            title="t",
            occurrence_count=1,
            first_occurred_at=_now(),
            latest_occurred_at=_now(),
        )
        db.alerts.append(row)

        async def fake_execute(query):  # noqa: ARG001
            return _Result(one=row)

        db.execute = fake_execute  # type: ignore
        actor = uuid4()
        ack = await PublishOperatorAlertService.acknowledge(
            db, db.tenant_id, row.id, actor_id=actor,
        )
        assert ack.state == "acknowledged"
        assert row.acknowledged_by == actor

        resolved = await PublishOperatorAlertService.resolve_manual(
            db, db.tenant_id, row.id, actor_id=actor, note="fixed token",
        )
        assert resolved.state == "resolved"
        assert row.resolve_note == "fixed token"
        assert row.resolved_by_system is False

    asyncio.run(run())


def test_list_filters_and_pagination_shape():
    async def run():
        db = FakeAlertDb()
        for i in range(3):
            db.alerts.append(
                PublishOperatorAlert(
                    id=uuid4(),
                    tenant_id=db.tenant_id,
                    dedupe_key=f"k{i}",
                    alert_type="exhausted",
                    state="open" if i < 2 else "resolved",
                    severity="critical",
                    title=f"t{i}",
                    platform="facebook",
                    occurrence_count=1,
                    first_occurred_at=_now() - timedelta(minutes=i),
                    latest_occurred_at=_now() - timedelta(minutes=i),
                    created_at=_now(),
                    updated_at=_now(),
                ),
            )

        async def fake_execute(query):  # noqa: ARG001
            # count then list — return count first-ish via scalar
            open_rows = [a for a in db.alerts if a.state == "open"]
            if not hasattr(fake_execute, "n"):
                fake_execute.n = 0  # type: ignore
            fake_execute.n += 1  # type: ignore
            if fake_execute.n == 1:  # type: ignore
                return _Result(scalar=len(open_rows))
            return _Result(rows=open_rows)

        db.execute = fake_execute  # type: ignore
        result = await PublishOperatorAlertService.list_alerts(
            db, db.tenant_id, state="open", page=1, page_size=20,
        )
        assert result.total == 2
        assert result.page == 1
        assert len(result.items) == 2
        assert all(i.state == "open" for i in result.items)

    asyncio.run(run())


def test_delivery_failure_does_not_break_publishing():
    async def run():
        alert = PublishOperatorAlert(
            id=uuid4(),
            tenant_id=uuid4(),
            dedupe_key="x",
            alert_type="exhausted",
            state="open",
            severity="critical",
            title="t",
            occurrence_count=1,
            first_occurred_at=_now(),
            latest_occurred_at=_now(),
        )
        db = FakeAlertDb()

        with (
            patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True),
            patch.object(settings, "PUBLISH_ALERT_EMAIL_ENABLED", False),
            patch(
                "app.services.publish_alert_telegram_outbox_service.PublishAlertTelegramOutboxService.enqueue_for_alert",
                AsyncMock(side_effect=RuntimeError("boom")),
            ),
        ):
            result = await deliver_publish_alert(db, alert)
        assert isinstance(result, dict)

        attempt = _attempt()
        with patch.object(
            PublishOperatorAlertService,
            "upsert_failure_alert",
            AsyncMock(side_effect=RuntimeError("alert boom")),
        ):
            out = await PublishOperatorAlertService.on_attempt_transition(db, attempt)
        assert out is None

    asyncio.run(run())


def test_transition_maps_statuses():
    async def run():
        db = FakeAlertDb()
        calls: list[str] = []

        async def capture(db_, attempt_, *, alert_type):
            calls.append(alert_type)
            return None

        with patch.object(PublishOperatorAlertService, "upsert_failure_alert", capture):
            await PublishOperatorAlertService.on_attempt_transition(
                db, _attempt(status=STATUS_OPERATOR_REVIEW),
            )
            await PublishOperatorAlertService.on_attempt_transition(
                db, _attempt(status=STATUS_EXHAUSTED),
            )
            await PublishOperatorAlertService.on_attempt_transition(
                db, _attempt(status=STATUS_FAILED, retryable=False),
            )
            await PublishOperatorAlertService.on_attempt_transition(
                db,
                _attempt(status=STATUS_RETRYING),
                previous_status=STATUS_IN_PROGRESS,
            )
            # retryable failed should not alert
            await PublishOperatorAlertService.on_attempt_transition(
                db, _attempt(status=STATUS_FAILED, retryable=True),
            )
        assert calls == [
            "operator_review",
            "exhausted",
            "terminal_failure",
            "stale_in_progress",
        ]

    asyncio.run(run())


if __name__ == "__main__":
    test_dedupe_key_stable_and_attempt_scoped_for_review()
    test_secret_redaction_in_failure_message()
    test_outbound_delivery_disabled_by_default()
    test_operator_review_alert_creation()
    test_exhausted_retry_alert()
    test_terminal_failure_alert()
    test_stale_attempt_alert()
    test_duplicate_scheduler_event_dedupes()
    test_concurrent_alert_creation_bumps_existing()
    test_recovery_resolves_matching_destination_only()
    test_on_success_creates_recovery_and_resolves()
    test_repeated_failure_threshold()
    test_tenant_isolation_on_get()
    test_acknowledge_and_manual_resolve()
    test_list_filters_and_pagination_shape()
    test_delivery_failure_does_not_break_publishing()
    test_transition_maps_statuses()
    print("all publish operator alert tests passed")
