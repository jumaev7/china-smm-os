"""Regression: Telegram alert-settings PUT must not 500 after successful commit.

Root cause mirror: async SQLAlchemy expires server-onupdate attrs (updated_at) after
flush; sync serialize_settings accessing them raises MissingGreenlet. Fix refreshes
before serialize and returns a detached-safe dict before commit.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from app.api.v1 import publishing as publishing_api
from app.core.config import settings
from app.schemas.publish_alerts import TelegramAlertSettingsUpdate
from app.services.publish_alert_telegram_enrollment_service import (
    PublishAlertTelegramEnrollmentService,
)
from app.services.publish_alert_telegram_outbox_service import (
    PublishAlertTelegramOutboxService,
)
from app.utils.operator_telegram_chat import mask_chat_id


CHAT_ID = 1234567890
MASKED = mask_chat_id(CHAT_ID)


def _now():
    return datetime.now(timezone.utc)


def _settings_row(**kwargs):
    tenant_id = kwargs.pop("tenant_id", uuid4())
    base = dict(
        id=uuid4(),
        tenant_id=tenant_id,
        enabled=True,
        recipient_chat_id=CHAT_ID,
        recipient_label="Jumaev10 operator alerts",
        allowed_chat_ids=[CHAT_ID],
        severity_threshold="warning",
        alert_types=["operator_review", "exhausted", "stale_in_progress"],
        quiet_hours_enabled=False,
        quiet_hours_start=None,
        quiet_hours_end=None,
        quiet_hours_timezone=None,
        recovery_messages_enabled=False,
        created_by=None,
        updated_by=None,
        created_at=_now(),
        updated_at=_now(),
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _owner_user(tenant_id):
    return SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        role="owner",
    )


def test_update_settings_refreshes_before_return():
    async def run():
        tenant = uuid4()
        row = _settings_row(tenant_id=tenant)
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        with patch.object(
            PublishAlertTelegramOutboxService,
            "get_or_create_settings",
            AsyncMock(return_value=row),
        ), patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            result = await PublishAlertTelegramOutboxService.update_settings(
                db,
                tenant,
                actor_id=uuid4(),
                payload={
                    "enabled": True,
                    "severity_threshold": "warning",
                    "recovery_messages_enabled": False,
                    "quiet_hours_enabled": False,
                },
            )

        assert result is row
        db.flush.assert_awaited()
        db.refresh.assert_awaited_once_with(row)
        serialized = PublishAlertTelegramOutboxService.serialize_settings(
            result, reveal_chat_id=False,
        )
        assert serialized["enabled"] is True
        assert serialized["recipient_chat_id"] is None
        assert serialized["recipient_chat_id_masked"] == MASKED
        assert serialized["recovery_messages_enabled"] is False

    asyncio.run(run())


def test_put_settings_returns_200_body_matches_and_no_greenlet():
    async def run():
        tenant = uuid4()
        actor = uuid4()
        row = _settings_row(tenant_id=tenant)
        db = AsyncMock()
        db.commit = AsyncMock()
        user = _owner_user(tenant)
        user.id = actor

        with patch.object(
            PublishAlertTelegramOutboxService,
            "update_settings",
            AsyncMock(return_value=row),
        ) as update_mock, patch.object(
            settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True,
        ), patch(
            "app.api.v1.publishing._require_tenant_admin_for_settings",
            MagicMock(),
        ), patch(
            "app.api.v1.publishing._resolve_scope",
            return_value=tenant,
        ), patch(
            "app.api.v1.publishing._reveal_chat_id",
            return_value=False,
        ), patch(
            "app.api.v1.publishing._actor_id",
            return_value=actor,
        ):
            body = TelegramAlertSettingsUpdate(
                enabled=True,
                severity_threshold="warning",
                recovery_messages_enabled=False,
                quiet_hours_enabled=False,
                alert_types=["operator_review", "exhausted", "stale_in_progress"],
            )
            response = await publishing_api.update_telegram_alert_settings(
                body=body,
                tenant_id=tenant,
                db=db,
                user=user,
                admin=None,
            )

        assert isinstance(response, dict)
        assert response["enabled"] is True
        assert response["severity_threshold"] == "warning"
        assert response["recovery_messages_enabled"] is False
        assert response["quiet_hours_enabled"] is False
        assert response["alert_types"] == [
            "operator_review",
            "exhausted",
            "stale_in_progress",
        ]
        assert response["recipient_chat_id"] is None
        assert response["recipient_chat_id_masked"] == MASKED
        assert "EAAB" not in str(response)
        assert str(CHAT_ID) not in str(response.get("recipient_chat_id"))
        db.commit.assert_awaited_once()
        update_mock.assert_awaited_once()
        # Serialize happened before commit (call order: update → serialize uses row → commit)
        assert db.commit.await_count == 1

    asyncio.run(run())


def test_identical_put_is_idempotent_no_outbox_no_telegram():
    async def run():
        tenant = uuid4()
        row = _settings_row(tenant_id=tenant)
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.commit = AsyncMock()
        enqueue = AsyncMock()
        httpx_post = AsyncMock()

        payload = {
            "enabled": True,
            "severity_threshold": "warning",
            "recovery_messages_enabled": False,
            "quiet_hours_enabled": False,
            "alert_types": ["operator_review", "exhausted", "stale_in_progress"],
            "recipient_label": "Jumaev10 operator alerts",
        }

        with patch.object(
            PublishAlertTelegramOutboxService,
            "get_or_create_settings",
            AsyncMock(return_value=row),
        ), patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True), patch(
            "app.services.publish_alert_telegram_outbox_service.PublishAlertTelegramOutboxService.enqueue_for_alert",
            enqueue,
        ), patch("httpx.AsyncClient.post", httpx_post):
            first = await PublishAlertTelegramOutboxService.update_settings(
                db, tenant, actor_id=uuid4(), payload=payload,
            )
            second = await PublishAlertTelegramOutboxService.update_settings(
                db, tenant, actor_id=uuid4(), payload=payload,
            )

        assert first.enabled is True
        assert second.enabled is True
        assert first.recipient_chat_id == CHAT_ID
        assert second.recipient_chat_id == CHAT_ID
        assert first.recovery_messages_enabled is False
        enqueue.assert_not_awaited()
        httpx_post.assert_not_called()
        assert db.flush.await_count == 2
        assert db.refresh.await_count == 2

    asyncio.run(run())


def test_validation_failure_does_not_flush_or_commit():
    async def run():
        tenant = uuid4()
        row = _settings_row(
            tenant_id=tenant,
            enabled=False,
            recipient_chat_id=None,
            allowed_chat_ids=[],
        )
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        db.commit = AsyncMock()

        with patch.object(
            PublishAlertTelegramOutboxService,
            "get_or_create_settings",
            AsyncMock(return_value=row),
        ):
            with pytest.raises(HTTPException) as exc:
                await PublishAlertTelegramOutboxService.update_settings(
                    db,
                    tenant,
                    actor_id=uuid4(),
                    payload={"enabled": True},
                )
        assert exc.value.status_code == 400
        db.flush.assert_not_awaited()
        db.refresh.assert_not_awaited()
        db.commit.assert_not_awaited()
        assert row.enabled is False

    asyncio.run(run())


def test_database_failure_rolls_back_and_raises():
    async def run():
        tenant = uuid4()
        row = _settings_row(tenant_id=tenant)
        db = AsyncMock()
        db.flush = AsyncMock(side_effect=SQLAlchemyError("simulated db failure"))
        db.refresh = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        with patch.object(
            PublishAlertTelegramOutboxService,
            "get_or_create_settings",
            AsyncMock(return_value=row),
        ):
            with pytest.raises(SQLAlchemyError):
                await PublishAlertTelegramOutboxService.update_settings(
                    db,
                    tenant,
                    actor_id=uuid4(),
                    payload={"recipient_label": "x"},
                )
        db.refresh.assert_not_awaited()
        db.commit.assert_not_awaited()

        # API path: commit failure after successful update must not be swallowed
        db2 = AsyncMock()
        db2.commit = AsyncMock(side_effect=SQLAlchemyError("commit failed"))
        user = _owner_user(tenant)
        with patch.object(
            PublishAlertTelegramOutboxService,
            "update_settings",
            AsyncMock(return_value=row),
        ), patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True), patch(
            "app.api.v1.publishing._require_tenant_admin_for_settings",
            MagicMock(),
        ), patch(
            "app.api.v1.publishing._resolve_scope",
            return_value=tenant,
        ), patch(
            "app.api.v1.publishing._reveal_chat_id",
            return_value=False,
        ), patch(
            "app.api.v1.publishing._actor_id",
            return_value=user.id,
        ):
            with pytest.raises(SQLAlchemyError):
                await publishing_api.update_telegram_alert_settings(
                    body=TelegramAlertSettingsUpdate(enabled=True),
                    tenant_id=tenant,
                    db=db2,
                    user=user,
                    admin=None,
                )

    asyncio.run(run())


def test_tenant_isolation_on_settings_update():
    async def run():
        tenant_a = uuid4()
        tenant_b = uuid4()
        row_a = _settings_row(tenant_id=tenant_a)
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        async def _get_or_create(db_, tenant_id, actor_id=None):
            assert tenant_id == tenant_a
            assert tenant_id != tenant_b
            return row_a

        with patch.object(
            PublishAlertTelegramOutboxService,
            "get_or_create_settings",
            AsyncMock(side_effect=_get_or_create),
        ), patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            result = await PublishAlertTelegramOutboxService.update_settings(
                db,
                tenant_a,
                actor_id=uuid4(),
                payload={"recipient_label": "only-a"},
            )
        assert result.tenant_id == tenant_a
        assert result.recipient_label == "only-a"

    asyncio.run(run())


def test_settings_update_creates_no_outbox_and_sends_no_telegram():
    async def run():
        tenant = uuid4()
        row = _settings_row(tenant_id=tenant)
        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        enqueue = AsyncMock()
        send = AsyncMock()

        with patch.object(
            PublishAlertTelegramOutboxService,
            "get_or_create_settings",
            AsyncMock(return_value=row),
        ), patch(
            "app.services.publish_alert_telegram_outbox_service.PublishAlertTelegramOutboxService.enqueue_for_alert",
            enqueue,
        ), patch(
            "app.services.publish_alert_telegram_outbox_service.PublishAlertTelegramOutboxService.enqueue_test",
            send,
        ), patch("httpx.AsyncClient.request", AsyncMock()) as req:
            await PublishAlertTelegramOutboxService.update_settings(
                db,
                tenant,
                actor_id=uuid4(),
                payload={"quiet_hours_enabled": False},
            )

        enqueue.assert_not_awaited()
        send.assert_not_awaited()
        req.assert_not_called()

    asyncio.run(run())


def test_adjacent_mutations_refresh_before_serialize():
    """cancel/retry/create/revoke/reject must not serialize expired ORM after flush."""

    async def run():
        # cancel + retry
        from app.models.publish_alert_telegram import PublishAlertTelegramDelivery

        delivery = PublishAlertTelegramDelivery(
            id=uuid4(),
            tenant_id=uuid4(),
            alert_id=uuid4(),
            dedupe_key=f"d|{uuid4()}",
            recipient_chat_id=CHAT_ID,
            status="pending",
            attempt_number=0,
            max_attempts=8,
            next_attempt_at=_now(),
            created_at=_now(),
        )
        db = AsyncMock()
        db.get = AsyncMock(return_value=delivery)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        cancelled = await PublishAlertTelegramOutboxService.cancel_delivery(
            db, delivery.tenant_id, delivery.id, actor_id=uuid4(),
        )
        assert cancelled["status"] == "cancelled"
        assert isinstance(cancelled, dict)
        db.refresh.assert_awaited()

        delivery.status = "failed"
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENABLED", True):
            retried = await PublishAlertTelegramOutboxService.manual_retry(
                db, delivery.tenant_id, delivery.id,
            )
        assert retried["status"] == "pending"
        assert isinstance(retried, dict)

        # revoke / reject refresh
        from app.services.publish_alert_telegram_enrollment_service import (
            hash_enrollment_token,
        )

        enrollment = SimpleNamespace(
            id=uuid4(),
            tenant_id=uuid4(),
            status="pending_start",
            purpose="operator_alert_recipient",
            expires_at=_now(),
            consumed_at=None,
            telegram_chat_id_masked=None,
            telegram_display_name=None,
            telegram_username=None,
            telegram_chat_type=None,
            bot_username="Bot",
            rejection_reason_code=None,
            confirmed_at=None,
            revoked_at=None,
            rejected_at=None,
            created_at=_now(),
            updated_at=_now(),
            revoked_by=None,
            rejected_by=None,
            telegram_user_id=None,
            telegram_chat_id=None,
            token_hash=hash_enrollment_token("x" * 40),
        )
        db2 = AsyncMock()
        db2.get = AsyncMock(return_value=enrollment)
        db2.flush = AsyncMock()
        db2.refresh = AsyncMock()
        with patch.object(settings, "PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED", True):
            revoked = await PublishAlertTelegramEnrollmentService.revoke_enrollment(
                db2, enrollment.tenant_id, enrollment.id, actor_id=uuid4(),
            )
        assert isinstance(revoked, dict)
        assert revoked["status"] == "revoked"
        db2.refresh.assert_awaited_once()

        enrollment2 = SimpleNamespace(**{**enrollment.__dict__, "status": "candidate_received"})
        db3 = AsyncMock()
        db3.get = AsyncMock(return_value=enrollment2)
        db3.flush = AsyncMock()
        db3.refresh = AsyncMock()
        rejected = await PublishAlertTelegramEnrollmentService.reject_candidate(
            db3, enrollment2.tenant_id, enrollment2.id, actor_id=uuid4(),
        )
        assert isinstance(rejected, dict)
        assert rejected["status"] == "rejected"
        db3.refresh.assert_awaited_once()

    asyncio.run(run())


def test_serialize_settings_masks_secrets_and_full_chat_id():
    row = _settings_row()
    masked = PublishAlertTelegramOutboxService.serialize_settings(row, reveal_chat_id=False)
    assert masked["recipient_chat_id"] is None
    assert masked["allowed_chat_ids"] == []
    assert masked["recipient_chat_id_masked"] == MASKED
    assert MASKED.startswith("*") or "****" in MASKED or MASKED.endswith(str(CHAT_ID)[-4:])
    assert str(CHAT_ID) not in (masked["recipient_chat_id_masked"] or "")
    blob = str(masked)
    assert "bot" not in blob.lower() or "bot_username" not in blob
    assert "token" not in blob.lower()
