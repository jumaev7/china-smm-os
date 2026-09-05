"""Acknowledge alert — semantics, idempotency, no external side effects.

Phase 3B audit companion: documents canonical acknowledge behavior for mobile.
Row-lock concurrency coverage lives in test_acknowledge_alert_concurrency.py.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.api_auth_context import ApiAuthContext, _auth_ctx
from app.core.config import settings
from app.services.operator_auto_ack.comparison import classify_shadow_outcome
from app.services.operator_auto_ack.constants import (
    OUTCOME_MATCH,
    SHADOW_ACTION_WOULD_ACK,
)
from app.services.operator_auto_ack.eligibility import evaluate_auto_ack_candidate
from app.services.operator_auto_ack.shadow import real_auto_ack_enabled
from app.services.operator_workspace_actions import (
    ACTION_ACKNOWLEDGE_ALERT,
    OperatorWorkspaceActionService,
)
from app.services.publish_operator_alert_service import PublishOperatorAlertService
from app.services.publish_resilience import STATUS_RETRYING


def _now():
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def _mute_workspace_action_audit(monkeypatch):
    monkeypatch.setattr(
        "app.services.operator_workspace_actions.OperatorWorkspaceMetricsService.record_action",
        AsyncMock(return_value=None),
    )


def test_acknowledge_open_sets_state_and_actor_fields():
    """open → acknowledged; sets acknowledged_at / acknowledged_by; no side effects."""

    async def run():
        tenant_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        row = SimpleNamespace(
            id=alert_id,
            tenant_id=tenant_id,
            state="open",
            acknowledged_at=None,
            acknowledged_by=None,
        )

        async def fake_get(_db, tid, aid, *, for_update: bool = False):
            assert tid == tenant_id
            assert aid == alert_id
            assert for_update is True
            return row

        with (
            patch.object(
                PublishOperatorAlertService,
                "_get_for_tenant",
                new=AsyncMock(side_effect=fake_get),
            ),
            patch(
                "app.services.publish_operator_alert_service.utc_now",
                return_value=_now(),
            ),
        ):
            db = AsyncMock()
            resp = await PublishOperatorAlertService.acknowledge(
                db, tenant_id, alert_id, actor_id=actor_id,
            )

        assert resp.state == "acknowledged"
        assert row.state == "acknowledged"
        assert row.acknowledged_by == actor_id
        assert row.acknowledged_at is not None
        db.flush.assert_awaited()

    asyncio.run(run())


def test_acknowledge_already_acknowledged_is_idempotent_no_overwrite():
    """Sequential re-ack succeeds and does not overwrite acknowledged_by."""

    async def run():
        tenant_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        first_actor = uuid.uuid4()
        second_actor = uuid.uuid4()
        stamped = _now()
        row = SimpleNamespace(
            id=alert_id,
            tenant_id=tenant_id,
            state="acknowledged",
            acknowledged_at=stamped,
            acknowledged_by=first_actor,
        )

        with patch.object(
            PublishOperatorAlertService,
            "_get_for_tenant",
            new=AsyncMock(return_value=row),
        ):
            db = AsyncMock()
            resp = await PublishOperatorAlertService.acknowledge(
                db, tenant_id, alert_id, actor_id=second_actor,
            )

        assert resp.state == "acknowledged"
        assert row.acknowledged_by == first_actor
        assert row.acknowledged_at == stamped
        db.flush.assert_not_awaited()

    asyncio.run(run())


def test_acknowledge_resolved_rejected():
    async def run():
        row = SimpleNamespace(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            state="resolved",
            acknowledged_at=None,
            acknowledged_by=None,
        )
        with patch.object(
            PublishOperatorAlertService,
            "_get_for_tenant",
            new=AsyncMock(return_value=row),
        ):
            with pytest.raises(HTTPException) as exc:
                await PublishOperatorAlertService.acknowledge(
                    AsyncMock(), row.tenant_id, row.id, actor_id=uuid.uuid4(),
                )
        assert exc.value.status_code == 400
        assert "resolved" in str(exc.value.detail).lower()

    asyncio.run(run())


def test_workspace_acknowledge_resolved_returns_409():
    """Workspace layer maps resolved → 409 before calling canonical service."""

    async def run():
        tenant_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        alert = SimpleNamespace(
            id=alert_id,
            tenant_id=tenant_id,
            content_id=None,
            state="resolved",
        )
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with (
                patch.object(
                    OperatorWorkspaceActionService,
                    "_load_alert_scoped",
                    new=AsyncMock(return_value=(alert, tenant_id, None)),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishOperatorAlertService.acknowledge",
                    new=AsyncMock(),
                ) as ack,
            ):
                with pytest.raises(HTTPException) as exc:
                    await OperatorWorkspaceActionService.execute(
                        AsyncMock(),
                        attention_id=f"publish-alert:{alert_id}",
                        action_id=ACTION_ACKNOWLEDGE_ALERT,
                        actor_id=uuid.uuid4(),
                        tenant_id=tenant_id,
                    )
            assert exc.value.status_code == 409
            ack.assert_not_awaited()
        finally:
            _auth_ctx.reset(token)

    asyncio.run(run())


def test_workspace_acknowledge_source_mobile_recorded():
    """X-Client-Source / body source=mobile reaches metrics audit."""

    async def run():
        tenant_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        alert = SimpleNamespace(
            id=alert_id,
            tenant_id=tenant_id,
            content_id=None,
            state="open",
        )
        ack_response = SimpleNamespace(id=alert_id, state="acknowledged")
        record = AsyncMock(return_value=None)

        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with (
                patch.object(
                    OperatorWorkspaceActionService,
                    "_load_alert_scoped",
                    new=AsyncMock(return_value=(alert, tenant_id, None)),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishOperatorAlertService.acknowledge",
                    new=AsyncMock(return_value=ack_response),
                ),
                patch(
                    "app.services.operator_workspace_actions.OperatorWorkspaceMetricsService.record_action",
                    new=record,
                ),
            ):
                result = await OperatorWorkspaceActionService.execute(
                    AsyncMock(),
                    attention_id=f"publish-alert:{alert_id}",
                    action_id=ACTION_ACKNOWLEDGE_ALERT,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    source="mobile",
                )
            assert result.success is True
            assert result.attention_still_relevant is True
            assert result.message == "Alert acknowledged"
            record.assert_awaited()
            kwargs = record.await_args.kwargs
            assert kwargs["action_id"] == ACTION_ACKNOWLEDGE_ALERT
            assert kwargs["source"] == "mobile"
            assert kwargs["actor_id"] == actor_id
            assert kwargs["tenant_id"] == tenant_id
            assert kwargs["outcome"] == "success"
        finally:
            _auth_ctx.reset(token)

    asyncio.run(run())


def test_acknowledge_has_no_provider_or_notification_side_effects():
    """Canonical acknowledge only mutates alert row fields — no publish/Telegram/Meta."""
    src = PublishOperatorAlertService.acknowledge.__code__.co_names
    # Soft check: method body must not reference known side-effect entrypoints.
    forbidden = {
        "manual_retry",
        "send_message",
        "telegram",
        "meta",
        "publish",
        "resolve_manual",
    }
    lowered = {n.lower() for n in src}
    # co_names includes attribute lookups; ensure none of the dangerous APIs appear.
    assert not forbidden.intersection(lowered)


def test_human_ack_classifies_as_match_for_shadow_comparison():
    """Manual acknowledge after shadow would-ack → MATCH; does not trigger Auto-Ack."""
    shadow_at = _now()
    alert = SimpleNamespace(
        state="acknowledged",
        acknowledged_at=shadow_at,
        resolved_at=None,
        resolved_by_system=False,
    )
    outcome = classify_shadow_outcome(
        shadow_details={
            "shadow_action": SHADOW_ACTION_WOULD_ACK,
            "eligible": True,
        },
        shadow_created_at=shadow_at,
        alert=alert,
        now=shadow_at,
    )
    assert outcome == OUTCOME_MATCH
    assert real_auto_ack_enabled() is False or settings.OPERATOR_AUTO_ACK_ALERTS_ENABLED is False


def test_acknowledged_alert_ineligible_for_auto_ack_candidate():
    alert = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        client_id=None,
        content_id=None,
        account_id=None,
        attempt_id=uuid.uuid4(),
        state="acknowledged",
        alert_type="stale_in_progress",
        severity="warning",
        platform="telegram",
        failure_code="stale_in_progress",
        attempt_status=STATUS_RETRYING,
        occurrence_count=1,
        latest_occurred_at=_now(),
        first_occurred_at=_now(),
    )
    attempt = SimpleNamespace(
        status=STATUS_RETRYING,
        failure_code="stale_in_progress",
        platform="telegram",
        finished_at=None,
        created_at=_now(),
    )
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    assert decision.reason_code == "already_acknowledged"


def test_acknowledge_uses_for_update_locked_get():
    """acknowledge loads via _get_for_tenant(..., for_update=True)."""

    async def run():
        tenant_id = uuid.uuid4()
        alert_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        row = SimpleNamespace(
            id=alert_id,
            tenant_id=tenant_id,
            state="open",
            acknowledged_at=None,
            acknowledged_by=None,
        )
        get = AsyncMock(return_value=row)

        with (
            patch.object(PublishOperatorAlertService, "_get_for_tenant", get),
            patch(
                "app.services.publish_operator_alert_service.utc_now",
                return_value=_now(),
            ),
        ):
            await PublishOperatorAlertService.acknowledge(
                AsyncMock(), tenant_id, alert_id, actor_id=actor_id,
            )

        get.assert_awaited_once()
        assert get.await_args.kwargs.get("for_update") is True
        assert row.acknowledged_by == actor_id

    asyncio.run(run())
