"""Regression tests for tenant-scoped Telegram operator-alert delivery outbox."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.publish_alert_telegram import (
    PublishAlertTelegramDelivery,
    TenantPublishAlertTelegramSettings,
)
from app.models.publish_operator_alert import PublishOperatorAlert
from app.services.publish_alert_delivery import deliver_publish_alert, delivery_enabled_any
from app.services.publish_alert_telegram_outbox_service import (
    PublishAlertTelegramOutboxService,
    build_delivery_dedupe_key,
    classify_telegram_error,
    compute_backoff_seconds,
    format_alert_telegram_html,
    passes_filters,
    recipient_authorized,
)
from app.utils.operator_telegram_chat import (
    escape_html,
    mask_chat_id,
    validate_operator_telegram_chat_id,
)


def _now():
    return datetime.now(timezone.utc)


def _settings_row(**kwargs):
    base = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        enabled=True,
        recipient_chat_id=123456789,
        recipient_label="ops",
        allowed_chat_ids=[123456789],
        severity_threshold="warning",
        alert_types=None,
        quiet_hours_enabled=False,
        quiet_hours_start=None,
        quiet_hours_end=None,
        quiet_hours_timezone="UTC",
        recovery_messages_enabled=True,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _alert(**kwargs):
    tenant_id = kwargs.pop("tenant_id", uuid4())
    base = dict(
        id=uuid4(),
        tenant_id=tenant_id,
        dedupe_key="k",
        alert_type="operator_review",
        state="open",
        severity="critical",
        title="Publish attempt needs operator review",
        body="timeout",
        company_name="Acme <Export>",
        platform="facebook",
        failure_code="stale_in_progress",
        failure_message="access_token=EAABSECRET failed",
        attempt_number=2,
        next_retry_at=_now() + timedelta(minutes=5),
        action_url="/publishing/alerts",
        last_delivery_at=None,
        last_delivery_channel=None,
        last_delivery_error=None,
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _delivery(**kwargs):
    base = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        alert_id=uuid4(),
        dedupe_key="d",
        channel="telegram",
        message_kind="alert",
        alert_version=1,
        recipient_chat_id=123456789,
        recipient_label="ops",
        status="sending",
        attempt_number=1,
        max_attempts=8,
        next_attempt_at=_now(),
        lease_owner="worker-1",
        lease_expires_at=_now() + timedelta(minutes=2),
        telegram_message_id=None,
        failure_code=None,
        failure_message=None,
        delivered_at=None,
        cancelled_at=None,
        cancelled_by=None,
        last_attempt_at=_now(),
        payload_snapshot={},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── Config / validation ───────────────────────────────────────────────────


def test_global_and_worker_flags_disabled_by_default():
    assert settings.PUBLISH_ALERT_TELEGRAM_ENABLED is False
    assert settings.PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED is False
    assert settings.PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED is False
    assert delivery_enabled_any() is False


def test_numeric_chat_id_validation():
    assert validate_operator_telegram_chat_id("123456789") == 123456789
    assert validate_operator_telegram_chat_id(-1001234567890) == -1001234567890
    with pytest.raises(ValueError):
        validate_operator_telegram_chat_id("@Jumaev7")
    with pytest.raises(ValueError):
        validate_operator_telegram_chat_id("Jumaev10")
    with pytest.raises(ValueError):
        validate_operator_telegram_chat_id("12")


def test_html_escaping_and_secret_redaction_in_message():
    alert = _alert()
    html = format_alert_telegram_html(alert, message_kind="alert", attempt_number=2)
    assert "Acme &lt;Export&gt;" in html
    assert "EAABSECRET" not in html
    assert "https://app.chinasmmos.com/publishing/alerts" in html
    assert escape_html("<b>") == "&lt;b&gt;"
    assert mask_chat_id(123456789) == "*****6789"


def test_recipient_allowlist_and_filters():
    cfg = _settings_row(allowed_chat_ids=[999999999], recipient_chat_id=123456789)
    assert recipient_authorized(cfg) is False
    cfg2 = _settings_row()
    assert recipient_authorized(cfg2) is True
    alert = _alert(severity="info")
    assert passes_filters(_settings_row(severity_threshold="warning"), alert) is False
    alert2 = _alert(alert_type="recovery", severity="info")
    with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED", False):
        assert passes_filters(_settings_row(recovery_messages_enabled=True), alert2) is False
    with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED", True):
        assert passes_filters(_settings_row(recovery_messages_enabled=False), alert2) is False
    assert passes_filters(
        _settings_row(alert_types=["exhausted"]),
        _alert(alert_type="operator_review"),
    ) is False


def test_classify_telegram_errors_and_backoff():
    code, terminal, retry = classify_telegram_error("Forbidden: bot was blocked by the user")
    assert code == "bot_blocked" and terminal is True
    code, terminal, retry = classify_telegram_error("Too Many Requests: retry after 42")
    assert code == "rate_limited" and terminal is False and retry == 42
    assert compute_backoff_seconds(1, retry_after=42) == 42
    code, terminal, _ = classify_telegram_error("Bad Request: chat not found")
    assert terminal is True and code == "invalid_chat"


# ── Enqueue gates ─────────────────────────────────────────────────────────


def test_global_kill_switch_skips_enqueue():
    async def run():
        alert = _alert()
        db = AsyncMock()
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", False):
            row = await PublishAlertTelegramOutboxService.enqueue_for_alert(db, alert)
        assert row is None
        db.execute.assert_not_called()

    asyncio.run(run())


def test_tenant_disabled_skips_enqueue():
    async def run():
        alert = _alert()
        cfg = _settings_row(tenant_id=alert.tenant_id, enabled=False)
        db = AsyncMock()
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                row = await PublishAlertTelegramOutboxService.enqueue_for_alert(db, alert)
        assert row is None

    asyncio.run(run())


def test_missing_recipient_skips_enqueue():
    async def run():
        alert = _alert()
        cfg = _settings_row(
            tenant_id=alert.tenant_id,
            recipient_chat_id=None,
            allowed_chat_ids=[],
        )
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                row = await PublishAlertTelegramOutboxService.enqueue_for_alert(AsyncMock(), alert)
        assert row is None

    asyncio.run(run())


def test_enqueue_eligible_alert_creates_delivery():
    async def run():
        alert = _alert()
        cfg = _settings_row(tenant_id=alert.tenant_id)
        delivery_id = uuid4()

        class _Exec:
            def scalar_one_or_none(self):
                return delivery_id

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_Exec())
        db.get = AsyncMock(return_value=_delivery(id=delivery_id, alert_id=alert.id))
        db.flush = AsyncMock()

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                row = await PublishAlertTelegramOutboxService.enqueue_for_alert(db, alert)
        assert row is not None
        assert row.id == delivery_id
        db.execute.assert_awaited()

    asyncio.run(run())


def test_duplicate_event_deduplication():
    async def run():
        alert = _alert()
        cfg = _settings_row(tenant_id=alert.tenant_id)

        class _Exec:
            def scalar_one_or_none(self):
                return None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_Exec())
        db.flush = AsyncMock()

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                row = await PublishAlertTelegramOutboxService.enqueue_for_alert(db, alert)
        assert row is None

    asyncio.run(run())


def test_no_historical_delivery_via_adapter_when_disabled():
    async def run():
        alert = _alert()
        db = AsyncMock()
        db.flush = AsyncMock()
        result = await deliver_publish_alert(db, alert)
        assert result["telegram"] == "skipped"
        assert result["delivered"] is False

    asyncio.run(run())


def test_delivery_failure_does_not_raise_into_publishing():
    async def run():
        alert = _alert()
        db = AsyncMock()
        db.flush = AsyncMock()
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch(
                "app.services.publish_alert_telegram_outbox_service.PublishAlertTelegramOutboxService.enqueue_for_alert",
                AsyncMock(side_effect=RuntimeError("boom")),
            ):
                result = await deliver_publish_alert(db, alert)
        assert "telegram" in result

    asyncio.run(run())


# ── Worker claim / process ─────────────────────────────────────────────────


def test_concurrent_claim_uses_skip_locked():
    async def run():
        captured = {}

        class _Scalars:
            def all(self):
                return []

        async def fake_scalars(query):
            captured["query"] = query
            return _Scalars()

        db = AsyncMock()
        db.scalars = fake_scalars
        db.flush = AsyncMock()

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            rows = await PublishAlertTelegramOutboxService.claim_batch(
                db, worker_id="w1", batch_size=2,
            )
        assert rows == []
        assert "query" in captured

    asyncio.run(run())


def test_successful_delivery_stores_message_id():
    async def run():
        alert = _alert()
        delivery = _delivery(
            tenant_id=alert.tenant_id,
            alert_id=alert.id,
            lease_owner="worker-1",
            status="sending",
            attempt_number=1,
        )
        cfg = _settings_row(tenant_id=alert.tenant_id)

        async def fake_send(chat_id, text):
            assert chat_id == 123456789
            assert "operator_review" in text
            return True, 42, None

        db = AsyncMock()
        db.get = AsyncMock(return_value=alert)
        db.flush = AsyncMock()

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                status = await PublishAlertTelegramOutboxService.process_delivery(
                    db, delivery, worker_id="worker-1", send_fn=fake_send,
                )
        assert status == "delivered"
        assert delivery.status == "delivered"
        assert delivery.telegram_message_id == 42

    asyncio.run(run())


def test_transient_failure_retries_and_rate_limit():
    async def run():
        alert = _alert()
        delivery = _delivery(
            tenant_id=alert.tenant_id,
            alert_id=alert.id,
            lease_owner="w1",
            attempt_number=1,
            max_attempts=5,
        )
        cfg = _settings_row(tenant_id=alert.tenant_id)
        db = AsyncMock()
        db.get = AsyncMock(return_value=alert)
        db.flush = AsyncMock()

        async def rate_limited(chat_id, text):
            return False, None, "Too Many Requests: retry after 30"

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                status = await PublishAlertTelegramOutboxService.process_delivery(
                    db, delivery, worker_id="w1", send_fn=rate_limited,
                )
        assert status == "retrying"
        assert delivery.status == "retrying"
        assert delivery.failure_code == "rate_limited"

    asyncio.run(run())


def test_terminal_forbidden_stops_retry():
    async def run():
        alert = _alert()
        delivery = _delivery(
            tenant_id=alert.tenant_id,
            alert_id=alert.id,
            lease_owner="w1",
            attempt_number=1,
        )
        cfg = _settings_row(tenant_id=alert.tenant_id)
        db = AsyncMock()
        db.get = AsyncMock(return_value=alert)
        db.flush = AsyncMock()

        async def forbidden(chat_id, text):
            return False, None, "Forbidden: bot is not a member of the channel chat"

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                status = await PublishAlertTelegramOutboxService.process_delivery(
                    db, delivery, worker_id="w1", send_fn=forbidden,
                )
        assert status == "failed"
        assert delivery.status == "failed"
        assert delivery.failure_code == "forbidden"

    asyncio.run(run())


def test_max_retry_exhaustion():
    async def run():
        alert = _alert()
        delivery = _delivery(
            tenant_id=alert.tenant_id,
            alert_id=alert.id,
            lease_owner="w1",
            attempt_number=8,
            max_attempts=8,
        )
        cfg = _settings_row(tenant_id=alert.tenant_id)
        db = AsyncMock()
        db.get = AsyncMock(return_value=alert)
        db.flush = AsyncMock()

        async def transient(chat_id, text):
            return False, None, "timeout connecting"

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with patch.object(
                PublishAlertTelegramOutboxService,
                "get_settings",
                AsyncMock(return_value=cfg),
            ):
                status = await PublishAlertTelegramOutboxService.process_delivery(
                    db, delivery, worker_id="w1", send_fn=transient,
                )
        assert status == "exhausted"
        assert delivery.status == "exhausted"

    asyncio.run(run())


def test_recovery_notification_respects_flag():
    alert = _alert(alert_type="recovery", severity="info")
    cfg = _settings_row(
        tenant_id=alert.tenant_id,
        severity_threshold="info",
        recovery_messages_enabled=True,
    )
    # Both global and tenant recovery flags required.
    with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED", True):
        assert passes_filters(cfg, alert) is True
    with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED", False):
        assert passes_filters(cfg, alert) is False
    cfg_off = _settings_row(
        tenant_id=alert.tenant_id,
        severity_threshold="info",
        recovery_messages_enabled=False,
    )
    with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED", True):
        assert passes_filters(cfg_off, alert) is False
    with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED", False):
        assert passes_filters(cfg_off, alert) is False


def test_cancel_and_manual_retry():
    async def run():
        delivery = PublishAlertTelegramDelivery(
            id=uuid4(),
            tenant_id=uuid4(),
            alert_id=uuid4(),
            dedupe_key=f"d|{uuid4()}",
            recipient_chat_id=123456789,
            status="pending",
            attempt_number=0,
            max_attempts=8,
            next_attempt_at=_now(),
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        result = await PublishAlertTelegramOutboxService.cancel_delivery(
            db, delivery.tenant_id, delivery.id, actor_id=uuid4(),
        )
        assert result["status"] == "cancelled"
        db.refresh.assert_awaited()

        delivery.status = "failed"
        delivery.attempt_number = 3
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            result = await PublishAlertTelegramOutboxService.manual_retry(
                db, delivery.tenant_id, delivery.id,
            )
        assert result["status"] == "pending"
        assert db.refresh.await_count == 2

    asyncio.run(run())


def test_tenant_isolation_on_cancel():
    async def run():
        delivery = PublishAlertTelegramDelivery(
            id=uuid4(),
            tenant_id=uuid4(),
            alert_id=uuid4(),
            dedupe_key=f"d|{uuid4()}",
            recipient_chat_id=123456789,
            status="pending",
            attempt_number=0,
            max_attempts=8,
            next_attempt_at=_now(),
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)
        with pytest.raises(HTTPException) as exc:
            await PublishAlertTelegramOutboxService.cancel_delivery(
                db, uuid4(), delivery.id, actor_id=None,
            )
        assert exc.value.status_code == 404

    asyncio.run(run())


def test_test_endpoint_blocked_when_global_disabled():
    async def run():
        db = AsyncMock()
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", False):
            with pytest.raises(HTTPException) as exc:
                await PublishAlertTelegramOutboxService.enqueue_test(
                    db, uuid4(), actor_id=None, confirm=True,
                )
        assert exc.value.status_code == 400
        assert "PUBLISH_ALERT_TELEGRAM_ENABLED" in str(exc.value.detail)

    asyncio.run(run())


def test_test_endpoint_requires_confirm():
    async def run():
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            with pytest.raises(HTTPException) as exc:
                await PublishAlertTelegramOutboxService.enqueue_test(
                    AsyncMock(), uuid4(), actor_id=None, confirm=False,
                )
        assert "confirm" in str(exc.value.detail).lower()

    asyncio.run(run())


def test_dedupe_key_stable():
    alert_id = uuid4()
    k1 = build_delivery_dedupe_key(
        alert_id=alert_id,
        recipient_chat_id=1,
        channel="telegram",
        alert_version=1,
        message_kind="alert",
    )
    k2 = build_delivery_dedupe_key(
        alert_id=alert_id,
        recipient_chat_id=1,
        channel="telegram",
        alert_version=1,
        message_kind="alert",
    )
    assert k1 == k2
    k3 = build_delivery_dedupe_key(
        alert_id=alert_id,
        recipient_chat_id=1,
        channel="telegram",
        alert_version=1,
        message_kind="recovery",
    )
    assert k1 != k3


def test_settings_serialization_masks_chat_id():
    row = TenantPublishAlertTelegramSettings(
        id=uuid4(),
        tenant_id=uuid4(),
        enabled=True,
        recipient_chat_id=123456789,
        recipient_label="ops",
        allowed_chat_ids=[123456789],
        severity_threshold="warning",
    )
    masked = PublishAlertTelegramOutboxService.serialize_settings(row, reveal_chat_id=False)
    assert masked["recipient_chat_id"] is None
    assert masked["recipient_chat_id_masked"].endswith("6789")
    revealed = PublishAlertTelegramOutboxService.serialize_settings(row, reveal_chat_id=True)
    assert revealed["recipient_chat_id"] == 123456789
