"""Focused tests for secure Telegram operator-recipient self-enrollment."""
from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.models.publish_alert_telegram import ENROLLMENT_PURPOSE
from app.services.publish_alert_telegram_enrollment_service import (
    PublishAlertTelegramEnrollmentService,
    clamp_enrollment_ttl_seconds,
    generate_enrollment_token,
    hash_enrollment_token,
    is_private_user_chat,
    is_valid_bot_username,
    normalize_bot_username,
    parse_enrollment_start_payload,
    redact_start_token_for_logs,
    safe_telegram_display_name,
    safe_telegram_username,
    tokens_equal,
)
from app.utils.operator_telegram_chat import mask_chat_id


def _now():
    return datetime.now(timezone.utc)


def _enrollment(**kwargs):
    tenant_id = kwargs.pop("tenant_id", uuid4())
    base = dict(
        id=uuid4(),
        tenant_id=tenant_id,
        created_by_admin_id=uuid4(),
        token_hash=hash_enrollment_token("opaque-token-value-aaaaaaaa"),
        purpose=ENROLLMENT_PURPOSE,
        status="pending_start",
        expires_at=_now() + timedelta(minutes=10),
        consumed_at=None,
        telegram_user_id=None,
        telegram_chat_id=None,
        telegram_chat_id_masked=None,
        telegram_display_name=None,
        telegram_username=None,
        telegram_chat_type=None,
        source_update_id=None,
        bot_username="ChinaSmmOsBot",
        confirmed_at=None,
        confirmed_by=None,
        revoked_at=None,
        revoked_by=None,
        rejected_at=None,
        rejected_by=None,
        rejection_reason_code=None,
        created_at=_now(),
        updated_at=_now(),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _settings_row(**kwargs):
    base = dict(
        id=uuid4(),
        tenant_id=uuid4(),
        enabled=False,
        recipient_chat_id=None,
        recipient_label=None,
        allowed_chat_ids=[],
        severity_threshold="warning",
        alert_types=None,
        quiet_hours_enabled=False,
        quiet_hours_start=None,
        quiet_hours_end=None,
        quiet_hours_timezone="UTC",
        recovery_messages_enabled=False,
        updated_by=None,
        updated_at=_now(),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


# ── Token / parsing / chat validation ─────────────────────────────────────


def test_enrollment_flags_disabled_by_default():
    assert settings.PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED is False
    assert settings.PUBLISH_ALERT_TELEGRAM_ENABLED is False
    assert settings.PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED is False


def test_generate_token_opaque_and_hash_only_storage():
    token = generate_enrollment_token()
    assert len(token) >= 32
    assert " " not in token
    digest = hash_enrollment_token(token)
    assert digest == hashlib.sha256(token.encode()).hexdigest()
    assert len(digest) == 64
    assert token not in digest
    assert tokens_equal(digest, hash_enrollment_token(token))
    assert not tokens_equal(digest, hash_enrollment_token(token + "x"))


def test_ttl_clamped_to_safe_bounds():
    assert clamp_enrollment_ttl_seconds(10) == 60
    assert clamp_enrollment_ttl_seconds(600) == 600
    assert clamp_enrollment_ttl_seconds(99999) == 1800


def test_bot_username_format_validation():
    assert is_valid_bot_username("ChinaSmmOsBot")
    assert normalize_bot_username("@ChinaSmmOsBot") == "ChinaSmmOsBot"
    assert normalize_bot_username("ab") is None
    assert normalize_bot_username("bad name") is None
    assert normalize_bot_username("../evil") is None
    assert normalize_bot_username("https://t.me/x") is None
    link = PublishAlertTelegramEnrollmentService.build_deep_link(
        "ChinaSmmOsBot", "opaque_token_value_aaaaaaaaaaaa",
    )
    assert link == "https://t.me/ChinaSmmOsBot?start=opaque_token_value_aaaaaaaaaaaa"
    with pytest.raises(ValueError):
        PublishAlertTelegramEnrollmentService.build_deep_link("bad name", "opaque_token_value_aaaaaaaaaaaa")


def test_parse_enrollment_start_payload():
    token = generate_enrollment_token()
    assert parse_enrollment_start_payload(f"/start {token}") == token
    assert parse_enrollment_start_payload(f"/start@MyBot {token}") == token
    assert parse_enrollment_start_payload("/start") is None
    assert parse_enrollment_start_payload("/start ") is None
    assert parse_enrollment_start_payload("/chat_id") is None
    assert parse_enrollment_start_payload(f"/start {token} extra") is None
    assert parse_enrollment_start_payload("hello") is None
    assert parse_enrollment_start_payload("/start ../../etc/passwd") is None


def test_private_chat_accepted_groups_channels_bots_rejected():
    user_id = 123456789
    ok, reason = is_private_user_chat(
        {"id": user_id, "type": "private"},
        {"id": user_id, "is_bot": False},
    )
    assert ok and reason is None

    for chat_type in ("group", "supergroup", "channel"):
        ok, reason = is_private_user_chat(
            {"id": -100123, "type": chat_type},
            {"id": user_id, "is_bot": False},
        )
        assert not ok
        assert reason in ("not_private_chat", "unsupported_chat_type")

    ok, reason = is_private_user_chat(
        {"id": user_id, "type": "private"},
        {"id": user_id, "is_bot": True},
    )
    assert not ok and reason == "is_bot"

    ok, reason = is_private_user_chat(
        {"id": user_id, "type": "private"},
        {"id": user_id, "is_anonymous": True},
    )
    assert not ok and reason == "anonymous_admin"


def test_username_is_metadata_only_not_identity():
    assert safe_telegram_username({"username": "@OpsUser"}) == "OpsUser"
    name = safe_telegram_display_name({"first_name": "Ada", "last_name": "Lovelace"})
    assert name == "Ada Lovelace"
    masked = mask_chat_id(123456789)
    assert masked.endswith("6789")
    assert "123456789" not in (masked or "")


def test_redact_start_token_from_logs(caplog):
    token = generate_enrollment_token()
    redacted = redact_start_token_for_logs(f"/start {token}")
    assert token not in redacted
    assert "<redacted>" in redacted
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("payload %s", redacted)
    assert token not in caplog.text


def test_serialize_enrollment_masks_and_omits_raw_ids():
    row = _enrollment(
        status="candidate_received",
        telegram_chat_id=987654321,
        telegram_chat_id_masked=mask_chat_id(987654321),
        telegram_display_name="Ops",
        telegram_username="ops_user",
    )
    payload = PublishAlertTelegramEnrollmentService.serialize_enrollment(row)
    assert "telegram_chat_id" not in payload or payload.get("telegram_chat_id") is None
    assert payload["telegram_chat_id_masked"] == mask_chat_id(987654321)
    assert "987654321" not in str(payload)
    assert payload["start_token"] is None


# ── Service flows (mocked DB) ──────────────────────────────────────────────


def test_create_enrollment_disabled_raises():
    async def run():
        db = AsyncMock()
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED", False):
            with pytest.raises(HTTPException) as exc:
                await PublishAlertTelegramEnrollmentService.create_enrollment(
                    db, uuid4(), actor_id=uuid4(),
                )
            assert exc.value.status_code == 403

    asyncio.run(run())


def test_create_enrollment_hash_only_and_deep_link():
    async def run():
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        actor = uuid4()
        tenant = uuid4()

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED", True), patch.object(
            settings, "TELEGRAM_BOT_USERNAME", "ChinaSmmOsBot",
        ), patch.object(
            PublishAlertTelegramEnrollmentService,
            "revoke_active_for_creator",
            AsyncMock(return_value=1),
        ):
            result = await PublishAlertTelegramEnrollmentService.create_enrollment(
                db, tenant, actor_id=actor,
            )

        assert result["status"] == "pending_start"
        assert result["start_token"]
        assert result["deep_link"] == f"https://t.me/ChinaSmmOsBot?start={result['start_token']}"
        assert "tenant_id" not in (result["start_token"] or "")
        added = db.add.call_args[0][0]
        assert added.token_hash == hash_enrollment_token(result["start_token"])
        assert result["start_token"] not in added.token_hash
        assert added.tenant_id == tenant
        assert added.created_by_admin_id == actor
        db.refresh.assert_awaited()

    asyncio.run(run())


def test_webhook_private_start_consumes_token_atomically():
    async def run():
        token = generate_enrollment_token()
        enrollment_id = uuid4()
        user_id = 555666777

        db = AsyncMock()
        miss = MagicMock()
        miss.scalar_one_or_none.return_value = None
        consumed = MagicMock()
        consumed.scalar_one_or_none.return_value = enrollment_id
        db.execute = AsyncMock(side_effect=[miss, consumed])
        db.flush = AsyncMock()

        message = {
            "text": f"/start {token}",
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "Ops", "username": "ops1"},
        }

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED", True), patch(
            "app.services.telegram_service._send_telegram_message",
            AsyncMock(return_value=1),
        ) as send_mock:
            result = await PublishAlertTelegramEnrollmentService.try_handle_start_message(
                db, update_id=42, message=message,
            )

        assert result["ok"] is True
        assert result["status"] == "candidate_received"
        send_mock.assert_awaited()
        reply = send_mock.await_args.args[1]
        assert "confirm" in reply.lower()
        assert str(user_id) not in reply
        assert db.execute.await_count == 2

    asyncio.run(run())


def test_webhook_rejects_group_enrollment():
    async def run():
        token = generate_enrollment_token()
        db = AsyncMock()
        message = {
            "text": f"/start {token}",
            "chat": {"id": -100123456, "type": "supergroup", "title": "Intake"},
            "from": {"id": 111, "is_bot": False},
        }
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED", True), patch(
            "app.services.telegram_service._send_telegram_message",
            AsyncMock(return_value=1),
        ) as send_mock:
            result = await PublishAlertTelegramEnrollmentService.try_handle_start_message(
                db, update_id=7, message=message,
            )
        assert result["ok"] is False
        assert result["reason"] == "not_private_chat"
        assert "invalid or expired" in send_mock.await_args.args[1].lower()
        db.execute.assert_not_awaited()

    asyncio.run(run())


def test_webhook_invalid_token_generic_reply():
    async def run():
        db = AsyncMock()
        miss = MagicMock()
        miss.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(side_effect=[miss, miss, miss])
        user_id = 42424242
        message = {
            "text": f"/start {generate_enrollment_token()}",
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": "X"},
        }
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED", True), patch(
            "app.services.telegram_service._send_telegram_message",
            AsyncMock(return_value=1),
        ) as send_mock:
            result = await PublishAlertTelegramEnrollmentService.try_handle_start_message(
                db, update_id=9, message=message,
            )
        assert result["ok"] is False
        assert result["reason"] == "token_invalid"
        assert "invalid or expired" in send_mock.await_args.args[1].lower()

    asyncio.run(run())


def test_replayed_update_is_idempotent():
    async def run():
        existing = _enrollment(status="candidate_received", source_update_id=99)
        db = AsyncMock()
        found = MagicMock()
        found.scalar_one_or_none.return_value = existing
        db.execute = AsyncMock(return_value=found)
        user_id = 111222333
        message = {
            "text": f"/start {generate_enrollment_token()}",
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False},
        }
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED", True), patch(
            "app.services.telegram_service._send_telegram_message",
            AsyncMock(return_value=1),
        ):
            result = await PublishAlertTelegramEnrollmentService.try_handle_start_message(
                db, update_id=99, message=message,
            )
        assert result["duplicate_update"] is True
        assert result["ok"] is True

    asyncio.run(run())


def test_confirm_writes_settings_without_enabling_delivery():
    async def run():
        tenant = uuid4()
        actor = uuid4()
        chat_id = 777888999
        row = _enrollment(
            tenant_id=tenant,
            status="candidate_received",
            telegram_chat_id=chat_id,
            telegram_chat_id_masked=mask_chat_id(chat_id),
            telegram_display_name="Operator",
        )
        settings_row = _settings_row(tenant_id=tenant, enabled=False)

        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock()

        with patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.get_or_create_settings",
            AsyncMock(return_value=settings_row),
        ), patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.serialize_settings",
            return_value={"enabled": False, "recipient_chat_id_masked": mask_chat_id(chat_id)},
        ):
            result = await PublishAlertTelegramEnrollmentService.confirm_candidate(
                db, tenant, row.id, actor_id=actor,
            )

        assert row.status == "confirmed"
        assert settings_row.recipient_chat_id == chat_id
        assert settings_row.allowed_chat_ids == [chat_id]
        assert settings_row.enabled is False
        assert result["delivery_enabled"] is False
        assert result["idempotent"] is False
        assert db.refresh.await_count == 2

    asyncio.run(run())


def test_confirm_idempotent():
    async def run():
        tenant = uuid4()
        row = _enrollment(tenant_id=tenant, status="confirmed", telegram_chat_id=1)
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        with patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.get_settings",
            AsyncMock(return_value=_settings_row(tenant_id=tenant)),
        ), patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.serialize_settings",
            return_value={"enabled": False},
        ):
            result = await PublishAlertTelegramEnrollmentService.confirm_candidate(
                db, tenant, row.id, actor_id=uuid4(),
            )
        assert result["idempotent"] is True

    asyncio.run(run())


def test_confirm_tenant_isolation():
    async def run():
        db = AsyncMock()
        row = _enrollment(tenant_id=uuid4(), status="candidate_received", telegram_chat_id=1)
        db.get = AsyncMock(return_value=row)
        with pytest.raises(HTTPException) as exc:
            await PublishAlertTelegramEnrollmentService.confirm_candidate(
                db, uuid4(), row.id, actor_id=uuid4(),
            )
        assert exc.value.status_code == 404

    asyncio.run(run())


def test_reject_candidate_clears_internal_ids():
    async def run():
        tenant = uuid4()
        row = _enrollment(
            tenant_id=tenant,
            status="candidate_received",
            telegram_chat_id=12345,
            telegram_user_id=12345,
            telegram_chat_id_masked="***2345",
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.flush = AsyncMock()
        result = await PublishAlertTelegramEnrollmentService.reject_candidate(
            db, tenant, row.id, actor_id=uuid4(),
        )
        assert row.status == "rejected"
        assert row.telegram_chat_id is None
        assert row.telegram_user_id is None
        assert result["rejection_reason_code"] == "user_rejected"

    asyncio.run(run())


def test_remove_recipient_clears_settings_and_disables():
    async def run():
        tenant = uuid4()
        settings_row = _settings_row(
            tenant_id=tenant,
            enabled=True,
            recipient_chat_id=111,
            allowed_chat_ids=[111],
        )
        confirmed = _enrollment(tenant_id=tenant, status="confirmed", telegram_chat_id=111)
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        found = MagicMock()
        found.scalar_one_or_none.return_value = confirmed
        db.execute = AsyncMock(return_value=found)

        with patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.get_or_create_settings",
            AsyncMock(return_value=settings_row),
        ), patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.serialize_settings",
            return_value={"enabled": False, "recipient_chat_id": None},
        ):
            result = await PublishAlertTelegramEnrollmentService.remove_recipient(
                db, tenant, actor_id=uuid4(),
            )

        assert settings_row.recipient_chat_id is None
        assert settings_row.allowed_chat_ids == []
        assert settings_row.enabled is False
        assert confirmed.status == "revoked"
        assert result["removed"] is True

    asyncio.run(run())


def test_confirm_does_not_create_outbox_records():
    async def run():
        tenant = uuid4()
        chat_id = 222333444
        row = _enrollment(
            tenant_id=tenant,
            status="candidate_received",
            telegram_chat_id=chat_id,
            telegram_chat_id_masked=mask_chat_id(chat_id),
        )
        settings_row = _settings_row(tenant_id=tenant)
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.execute = AsyncMock()

        with patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.get_or_create_settings",
            AsyncMock(return_value=settings_row),
        ), patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.serialize_settings",
            return_value={"enabled": False},
        ), patch(
            "app.services.publish_alert_telegram_outbox_service.PublishAlertTelegramOutboxService.enqueue_for_alert",
            AsyncMock(),
        ) as enqueue:
            await PublishAlertTelegramEnrollmentService.confirm_candidate(
                db, tenant, row.id, actor_id=uuid4(),
            )
        enqueue.assert_not_awaited()
        assert db.refresh.await_count == 2

    asyncio.run(run())


def test_process_update_enrollment_bypasses_ingestion():
    async def run():
        from app.services.telegram_service import process_update

        token = generate_enrollment_token()
        user_id = 999888777
        update = {
            "update_id": 1001,
            "message": {
                "text": f"/start {token}",
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "is_bot": False, "first_name": "Ops"},
            },
        }
        db = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch(
            "app.services.telegram_service.claim_update",
            AsyncMock(return_value=True),
        ), patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramEnrollmentService.try_handle_start_message",
            AsyncMock(return_value={"enrollment": True, "ok": True, "status": "candidate_received"}),
        ) as enroll, patch(
            "app.services.telegram_service._find_or_create_client",
            AsyncMock(),
        ) as find_client:
            result = await process_update(db, update)

        assert result["enrollment"] is True
        enroll.assert_awaited()
        find_client.assert_not_awaited()

    asyncio.run(run())


def test_bare_start_without_token_does_not_enter_enrollment():
    assert parse_enrollment_start_payload("/start") is None

    async def run():
        from app.services.telegram_service import process_update

        user_id = 12121212
        update = {
            "update_id": 55,
            "message": {
                "text": "/start",
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": user_id, "is_bot": False},
            },
        }
        db = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch(
            "app.services.telegram_service.claim_update",
            AsyncMock(return_value=True),
        ), patch(
            "app.services.telegram_service._is_allowed_sender",
            return_value=False,
        ), patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramEnrollmentService.try_handle_start_message",
            AsyncMock(),
        ) as enroll:
            result = await process_update(db, update)

        enroll.assert_not_awaited()
        assert result is None

    asyncio.run(run())


def test_confirm_replace_guard_when_recipient_exists():
    async def run():
        tenant = uuid4()
        row = _enrollment(
            tenant_id=tenant,
            status="candidate_received",
            telegram_chat_id=222,
            telegram_chat_id_masked="***0222",
        )
        settings_row = _settings_row(tenant_id=tenant, recipient_chat_id=111, allowed_chat_ids=[111])
        db = AsyncMock()
        db.get = AsyncMock(return_value=row)

        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_MAX_CONFIRMED_RECIPIENTS", 1), patch(
            "app.services.publish_alert_telegram_enrollment_service.PublishAlertTelegramOutboxService.get_or_create_settings",
            AsyncMock(return_value=settings_row),
        ):
            with pytest.raises(HTTPException) as exc:
                await PublishAlertTelegramEnrollmentService.confirm_candidate(
                    db, tenant, row.id, actor_id=uuid4(), replace_existing=False,
                )
            assert exc.value.status_code == 409

    asyncio.run(run())
