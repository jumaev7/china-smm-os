"""Shadow-mode auto-ack Phase 1 — eligibility, zero side-effects, scheduler gates."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.access_log_redaction import scrub_audit_details
from app.core.config import settings
from app.services.operator_auto_ack.comparison import classify_shadow_outcome
from app.services.operator_auto_ack.constants import (
    CYCLE_EVENT_TYPE,
    OUTCOME_DISAGREEMENT,
    OUTCOME_MATCH,
    OUTCOME_PENDING,
    OUTCOME_SAFE_NO_ACTION,
    SHADOW_ACTION_WOULD_ACK,
    SHADOW_EVENT_TYPE,
)
from app.services.operator_auto_ack.eligibility import (
    evaluate_auto_ack_candidate,
)
from app.services.operator_auto_ack.scheduler import OperatorAutoAckShadowScheduler
from app.services.operator_auto_ack.shadow import (
    OperatorAutoAckShadowService,
    real_auto_ack_enabled,
    shadow_mode_enabled,
)
from app.services.operator_workspace_metrics import WORKSPACE_ACTION_EVENT
from app.services.publish_resilience import (
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
)


def _now():
    return datetime.now(timezone.utc)


def _alert(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        content_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        state="open",
        alert_type="stale_in_progress",
        severity="warning",
        platform="telegram",
        failure_code="stale_in_progress",
        attempt_status=STATUS_IN_PROGRESS,
        occurrence_count=1,
        latest_occurred_at=_now(),
        first_occurred_at=_now() - timedelta(hours=1),
        acknowledged_at=None,
        resolved_at=None,
        resolved_by_system=False,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _attempt(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        status=STATUS_RETRYING,
        failure_code="stale_in_progress",
        platform="telegram",
        content_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        created_at=_now() - timedelta(minutes=30),
        finished_at=None,
        external_post_id=None,
        response=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ── Kill switches / defaults ────────────────────────────────────────────────


def test_shadow_and_execution_flags_default_false():
    assert settings.OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED is False
    assert settings.OPERATOR_AUTO_ACK_ALERTS_ENABLED is False
    assert shadow_mode_enabled() is False
    assert real_auto_ack_enabled() is False


def test_scheduler_start_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", False)

    async def _run():
        await OperatorAutoAckShadowScheduler.start()
        # No task created when disabled.
        from app.services.operator_auto_ack import scheduler as sched_mod

        assert sched_mod._task is None

    asyncio.run(_run())


def test_run_cycle_skipped_when_shadow_disabled(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", False)

    async def _run():
        db = AsyncMock()
        summary = await OperatorAutoAckShadowService.run_cycle(db)
        assert summary["skipped"] is True
        assert summary["reason"] == "shadow_disabled"
        assert summary["evaluated"] == 0
        db.execute.assert_not_called()

    asyncio.run(_run())


# ── Eligibility matrix ──────────────────────────────────────────────────────


def test_eligible_stale_in_progress_retrying_non_meta():
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id)
    decision = evaluate_auto_ack_candidate(
        alert, attempt=attempt, newer_success_exists=False
    )
    assert decision.eligible is True
    assert decision.shadow_action == SHADOW_ACTION_WOULD_ACK
    assert decision.reason_code == "stale_in_progress_retrying_bookkeeping"
    assert decision.human_action_still_required is True
    assert decision.safety_level == "A_shadow_bookkeeping"


@pytest.mark.parametrize(
    "kwargs,reason",
    [
        ({"severity": "critical"}, "critical_severity"),
        ({"alert_type": "operator_review"}, "alert_type_excluded"),
        ({"alert_type": "exhausted"}, "alert_type_excluded"),
        ({"alert_type": "terminal_failure"}, "alert_type_excluded"),
        ({"alert_type": "recovery"}, "alert_type_excluded"),
        ({"alert_type": "repeated_failure"}, "alert_type_excluded"),
        ({"state": "resolved"}, "already_resolved"),
        ({"state": "acknowledged"}, "already_acknowledged"),
        ({"platform": "facebook"}, "meta_platform_excluded"),
        ({"platform": "instagram"}, "meta_platform_excluded"),
    ],
)
def test_ineligible_exclusions(kwargs, reason):
    alert = _alert(**kwargs)
    attempt = _attempt(id=alert.attempt_id, platform=alert.platform)
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    assert decision.reason_code == reason
    assert decision.shadow_action == "skip"


def test_operator_review_status_excluded():
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, status=STATUS_OPERATOR_REVIEW)
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    assert decision.reason_code == "operator_review_status"


def test_auth_permission_excluded():
    alert = _alert(failure_code="auth_or_permission")
    attempt = _attempt(id=alert.attempt_id, failure_code="auth_or_permission")
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    assert decision.reason_code == "unresolved_auth_or_permission"


def test_credential_decryption_excluded():
    alert = _alert(failure_code="credential_decryption_failed")
    attempt = _attempt(
        id=alert.attempt_id, failure_code="credential_decryption_failed"
    )
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    assert decision.reason_code == "unresolved_auth_or_permission"


def test_in_progress_excluded():
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, status=STATUS_IN_PROGRESS)
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    assert decision.reason_code == "attempt_in_progress"


def test_underlying_success_stale():
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, status=STATUS_SUCCESS)
    decision = evaluate_auto_ack_candidate(
        alert, attempt=attempt, newer_success_exists=False
    )
    assert decision.eligible is False
    assert decision.reason_code == "underlying_success_stale"


def test_newer_success_makes_ineligible():
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, status=STATUS_RETRYING)
    decision = evaluate_auto_ack_candidate(
        alert, attempt=attempt, newer_success_exists=True
    )
    assert decision.eligible is False
    assert decision.reason_code == "underlying_success_stale"


def test_attempt_missing_ineligible():
    alert = _alert()
    decision = evaluate_auto_ack_candidate(alert, attempt=None)
    assert decision.eligible is False
    assert decision.reason_code == "attempt_missing"


def test_allowlist_miss():
    # Force a type not in allowlist and not in exclude set via monkeypatch path:
    # severity warning + open + fake type that isn't allowlisted.
    alert = _alert(alert_type="stale_in_progress")
    # Use severity path already covered; allowlist_miss via patching type after exclude check
    alert.alert_type = "unknown_future_type"
    attempt = _attempt(id=alert.attempt_id)
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    assert decision.reason_code == "allowlist_miss"


# ── Human comparison ────────────────────────────────────────────────────────


def test_comparison_match_human_ack():
    shadow_at = _now() - timedelta(hours=1)
    alert = _alert(
        state="acknowledged",
        acknowledged_at=shadow_at + timedelta(minutes=10),
    )
    outcome = classify_shadow_outcome(
        shadow_details={"shadow_action": SHADOW_ACTION_WOULD_ACK, "eligible": True},
        shadow_created_at=shadow_at,
        alert=alert,
    )
    assert outcome == OUTCOME_MATCH


def test_comparison_safe_no_action_system_resolved():
    shadow_at = _now() - timedelta(hours=1)
    alert = _alert(
        state="resolved",
        resolved_by_system=True,
        resolved_at=shadow_at + timedelta(minutes=5),
    )
    outcome = classify_shadow_outcome(
        shadow_details={"shadow_action": SHADOW_ACTION_WOULD_ACK, "eligible": True},
        shadow_created_at=shadow_at,
        alert=alert,
    )
    assert outcome == OUTCOME_SAFE_NO_ACTION


def test_comparison_disagreement_human_resolve():
    shadow_at = _now() - timedelta(hours=1)
    alert = _alert(
        state="resolved",
        resolved_by_system=False,
        resolved_at=shadow_at + timedelta(minutes=5),
        acknowledged_at=None,
    )
    outcome = classify_shadow_outcome(
        shadow_details={"shadow_action": SHADOW_ACTION_WOULD_ACK, "eligible": True},
        shadow_created_at=shadow_at,
        alert=alert,
    )
    assert outcome == OUTCOME_DISAGREEMENT


def test_comparison_pending_still_open():
    shadow_at = _now() - timedelta(hours=1)
    alert = _alert(state="open")
    outcome = classify_shadow_outcome(
        shadow_details={"shadow_action": SHADOW_ACTION_WOULD_ACK, "eligible": True},
        shadow_created_at=shadow_at,
        alert=alert,
    )
    assert outcome == OUTCOME_PENDING


# ── Shadow service side-effect proofs ───────────────────────────────────────


def test_shadow_evaluate_never_calls_acknowledge(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", True)
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, content_id=alert.content_id)

    async def _run():
        db = AsyncMock()
        db.get = AsyncMock(return_value=attempt)
        with patch(
            "app.services.operator_auto_ack.shadow.PublishResilienceService.find_live_success",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.operator_auto_ack.shadow.OperatorAutoAckShadowService._should_dedupe",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.operator_auto_ack.shadow.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record, patch(
            "app.services.publish_operator_alert_service.PublishOperatorAlertService.acknowledge",
            new=AsyncMock(),
        ) as ack, patch(
            "app.services.publish_operator_alert_service.PublishOperatorAlertService.resolve_manual",
            new=AsyncMock(),
        ) as resolve:
            result = await OperatorAutoAckShadowService.evaluate_and_record(db, alert)
            assert result["decision"].eligible is True
            assert result["audit_written"] is True
            ack.assert_not_awaited()
            resolve.assert_not_awaited()
            kwargs = record.await_args.kwargs
            assert kwargs["event_type"] == SHADOW_EVENT_TYPE
            assert kwargs["actor_type"] == "system"
            assert kwargs["tenant_id"] == alert.tenant_id
            assert kwargs["resource_id"] == str(alert.id)
            details = kwargs["details"]
            assert details["eligible"] is True
            assert details["acknowledge_called"] is False
            assert details["alert_mutated"] is False
            assert details["shadow_action"] == SHADOW_ACTION_WOULD_ACK
            # Alert object unchanged
            assert alert.state == "open"
            assert alert.acknowledged_at is None

    asyncio.run(_run())


def test_cross_tenant_denied(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", True)
    alert = _alert()
    other_tenant = uuid.uuid4()

    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.operator_auto_ack.shadow.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            result = await OperatorAutoAckShadowService.evaluate_and_record(
                db, alert, expected_tenant_id=other_tenant
            )
            assert result["decision"].reason_code == "cross_tenant_denied"
            assert result["decision"].eligible is False
            assert record.await_args.kwargs["details"]["reason_code"] == "cross_tenant_denied"

    asyncio.run(_run())


def test_dedupe_skips_identical_fingerprint(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", True)
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, content_id=alert.content_id)

    async def _run():
        db = AsyncMock()
        db.get = AsyncMock(return_value=attempt)
        with patch(
            "app.services.operator_auto_ack.shadow.PublishResilienceService.find_live_success",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.operator_auto_ack.shadow.OperatorAutoAckShadowService._should_dedupe",
            new=AsyncMock(return_value=True),
        ), patch(
            "app.services.operator_auto_ack.shadow.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            result = await OperatorAutoAckShadowService.evaluate_and_record(db, alert)
            assert result["deduped"] is True
            assert result["audit_written"] is False
            record.assert_not_awaited()

    asyncio.run(_run())


def test_batch_isolates_candidate_failures(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", True)
    good = _alert()
    bad = _alert()
    attempt = _attempt(id=good.attempt_id, content_id=good.content_id)

    async def _run():
        db = AsyncMock()

        async def _eval(db_, alert, **kwargs):
            if alert is bad:
                raise RuntimeError("boom")
            return {
                "decision": evaluate_auto_ack_candidate(
                    alert, attempt=attempt, newer_success_exists=False
                ),
                "deduped": False,
                "audit_written": True,
            }

        with patch(
            "app.services.operator_auto_ack.shadow.OperatorAutoAckShadowService._load_candidate_alerts",
            new=AsyncMock(return_value=[bad, good]),
        ), patch(
            "app.services.operator_auto_ack.shadow.OperatorAutoAckShadowService.evaluate_and_record",
            new=_eval,
        ):
            summary = await OperatorAutoAckShadowService.run_cycle(db)
            assert summary["errors"] == 1
            assert summary["evaluated"] == 1
            assert summary["eligible"] == 1

    asyncio.run(_run())


def test_audit_failure_does_not_mutate_alert(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", True)
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, content_id=alert.content_id)
    original_state = alert.state

    async def _run():
        db = AsyncMock()
        db.get = AsyncMock(return_value=attempt)
        with patch(
            "app.services.operator_auto_ack.shadow.PublishResilienceService.find_live_success",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.operator_auto_ack.shadow.OperatorAutoAckShadowService._should_dedupe",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.operator_auto_ack.shadow.PlatformAuditService.record",
            new=AsyncMock(side_effect=RuntimeError("audit down")),
        ):
            result = await OperatorAutoAckShadowService.evaluate_and_record(db, alert)
            assert result["audit_written"] is False
            assert alert.state == original_state
            assert alert.acknowledged_at is None

    asyncio.run(_run())


def test_cycle_audit_event_type_isolated_from_workspace_actions():
    async def _run():
        db = AsyncMock()
        started = _now()
        with patch(
            "app.services.operator_auto_ack.shadow.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            await OperatorAutoAckShadowService.audit_scheduler_cycle(
                db,
                cycle=3,
                started_at=started,
                completed_at=started,
                totals={"evaluated": 2, "eligible": 1, "errors": 0},
            )
            kwargs = record.await_args.kwargs
            assert kwargs["event_type"] == CYCLE_EVENT_TYPE
            assert kwargs["event_type"] != WORKSPACE_ACTION_EVENT
            assert kwargs["actor_type"] == "system"
            assert kwargs["details"]["acknowledge_called"] is False

    asyncio.run(_run())


def test_audit_payload_secret_safe():
    dirty = {
        "access_token": "SECRET_TOKEN",
        "refresh_token": "SECRET_REFRESH",
        "authorization": "Bearer xyz",
        "eligible": True,
        "reason_code": "stale_in_progress_retrying_bookkeeping",
    }
    scrubbed = scrub_audit_details(dirty)
    blob = str(scrubbed).lower()
    assert "secret_token" not in blob
    assert "secret_refresh" not in blob
    assert "bearer xyz" not in blob
    assert scrubbed["eligible"] is True


def test_real_execution_flag_true_still_never_acknowledges(monkeypatch):
    """Even if future flag is flipped, Phase 1 has no real execution path."""
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_ENABLED", True)
    assert real_auto_ack_enabled() is True
    alert = _alert()
    attempt = _attempt(id=alert.attempt_id, content_id=alert.content_id)

    async def _run():
        db = AsyncMock()
        db.get = AsyncMock(return_value=attempt)
        with patch(
            "app.services.operator_auto_ack.shadow.PublishResilienceService.find_live_success",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.operator_auto_ack.shadow.OperatorAutoAckShadowService._should_dedupe",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.operator_auto_ack.shadow.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record, patch(
            "app.services.publish_operator_alert_service.PublishOperatorAlertService.acknowledge",
            new=AsyncMock(),
        ) as ack:
            await OperatorAutoAckShadowService.evaluate_and_record(db, alert)
            ack.assert_not_awaited()
            assert record.await_args.kwargs["details"]["acknowledge_called"] is False
            assert record.await_args.kwargs["details"]["real_auto_ack_enabled"] is True

    asyncio.run(_run())


def test_ineligible_records_skip_shadow_action(monkeypatch):
    monkeypatch.setattr(settings, "OPERATOR_AUTO_ACK_ALERTS_SHADOW_ENABLED", True)
    alert = _alert(severity="critical")
    attempt = _attempt(id=alert.attempt_id)

    async def _run():
        db = AsyncMock()
        db.get = AsyncMock(return_value=attempt)
        with patch(
            "app.services.operator_auto_ack.shadow.PublishResilienceService.find_live_success",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.operator_auto_ack.shadow.OperatorAutoAckShadowService._should_dedupe",
            new=AsyncMock(return_value=False),
        ), patch(
            "app.services.operator_auto_ack.shadow.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            result = await OperatorAutoAckShadowService.evaluate_and_record(db, alert)
            assert result["decision"].eligible is False
            assert record.await_args.kwargs["details"]["reason_code"] == "critical_severity"
            assert record.await_args.kwargs["details"]["shadow_action"] == "skip"

    asyncio.run(_run())


def test_ambiguous_meta_code_on_non_retrying_excluded():
    alert = _alert(failure_code="publish_timeout")
    attempt = _attempt(
        id=alert.attempt_id,
        status="failed",
        failure_code="publish_timeout",
    )
    decision = evaluate_auto_ack_candidate(alert, attempt=attempt)
    assert decision.eligible is False
    # failed is not retrying — either ambiguous or attempt_not_retrying
    assert decision.reason_code in {
        "ambiguous_meta_outcome",
        "attempt_not_retrying",
    }
