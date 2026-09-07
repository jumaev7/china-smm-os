"""Phase 3C.1A — canonical manual retry eligibility safety policy."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.api_auth_context import ApiAuthContext, _auth_ctx
from app.schemas.operator_workspace import OperatorAttentionItem
from app.services.manual_retry_eligibility import (
    ManualRetryLiveState,
    evaluate_manual_retry_eligibility,
)
from app.services.operator_workspace_actions import (
    ACTION_ACKNOWLEDGE_ALERT,
    ACTION_APPROVE_CONTENT,
    ACTION_RETRY_PUBLISH,
    OperatorWorkspaceActionService,
)
from app.services.publish_resilience import (
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
)


def _now():
    return datetime.now(timezone.utc)


def _enable_telegram_rate_limited_conditional(monkeypatch):
    """Test helper: temporarily restore the draft Telegram rate_limited conditional path.

    Production 3C.1A keep this EMPTY; these patches only exercise live-state /
    wiring gates that sit after the failure-code check.
    """
    from app.services import manual_retry_eligibility as mod
    from app.services.publish_resilience import AMBIGUOUS_META_FAILURE_CODES

    monkeypatch.setattr(
        mod,
        "_OPERATOR_REVIEW_FAILURE_CODES",
        frozenset(c for c in mod._OPERATOR_REVIEW_FAILURE_CODES if c != "rate_limited"),
    )
    monkeypatch.setattr(mod, "_CONDITIONAL_TELEGRAM_CODES", frozenset({"rate_limited"}))
    monkeypatch.setattr(
        mod,
        "_KNOWN_FAILURE_CODES",
        mod._PERMANENT_FAILURE_CODES
        | mod._OPERATOR_REVIEW_FAILURE_CODES
        | AMBIGUOUS_META_FAILURE_CODES
        | frozenset({"rate_limited"}),
    )


def _attempt(**kwargs):
    defaults = dict(
        status=STATUS_FAILED,
        platform="telegram",
        failure_code="rate_limited",
        attempt_number=1,
        external_post_id=None,
        publish_version="pv_1",
        next_retry_at=None,
        idempotency_key="idem-1",
        account=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _live(**kwargs):
    defaults = dict(
        has_live_success=False,
        content_status="failed",
        current_publish_version="pv_1",
        account_status="connected",
        now=_now(),
    )
    defaults.update(kwargs)
    return ManualRetryLiveState(**defaults)


def _item(**kwargs) -> OperatorAttentionItem:
    attempt_id = str(uuid.uuid4())
    defaults = dict(
        id=f"publish-attempt:{attempt_id}",
        attention_type="publishing_issue",
        priority="high",
        client_id=uuid.uuid4(),
        company_name="Acme",
        content_id=uuid.uuid4(),
        resource_id=attempt_id,
        title="Telegram publish issue",
        reason="rate limited",
        current_state=STATUS_FAILED,
        responsible_party="provider",
        suggested_action="Review",
        action_path="/content/x",
        source_domain="publishing",
        metadata={
            "platform": "telegram",
            "failure_code": "rate_limited",
            "attempt_number": 1,
            "publish_version": "pv_1",
            "current_publish_version": "pv_1",
            "content_status": "failed",
            "has_live_success": False,
            "attempt_id": attempt_id,
        },
    )
    defaults.update(kwargs)
    return OperatorAttentionItem(**defaults)


# ── Policy matrix ──────────────────────────────────────────────────────────


def test_null_failure_code_blocked():
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code=None), _live(), source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "failure_code_null"
    assert result.safety_class == "OPERATOR_REVIEW"
    assert result.mobile_eligible is False


def test_unknown_failure_code_blocked():
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="totally_unknown_xyz"), _live(), source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "failure_code_unknown"
    assert result.safety_class == "OPERATOR_REVIEW"


@pytest.mark.parametrize(
    "code",
    [
        "publish_timeout",
        "connection_error",
        "stale_in_progress",
        "provider_unavailable",
        "adapter_failure",
        "rate_limited",
        "provider_transient",
    ],
)
def test_ambiguous_codes_operator_review(code):
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code=code, platform="telegram"), _live(), source="workspace",
    )
    assert result.allowed is False
    assert result.safety_class == "OPERATOR_REVIEW"


def test_operator_review_status_blocked():
    result = evaluate_manual_retry_eligibility(
        _attempt(status=STATUS_OPERATOR_REVIEW, failure_code="stale_in_progress"),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "operator_review_required"
    assert result.safety_class == "OPERATOR_REVIEW"


@pytest.mark.parametrize(
    "code",
    [
        "credential_decryption_failed",
        "auth_or_permission",
        "validation_error",
        "unsupported_media",
        "publish_blocked",
        "account_unavailable",
    ],
)
def test_permanent_block_codes(code):
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code=code), _live(), source="workspace",
    )
    assert result.allowed is False
    assert result.safety_class == "PERMANENT_BLOCK"
    assert result.reason_code == code


def test_account_unavailable_via_live_status():
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="rate_limited"),
        _live(account_status="expired"),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "account_unavailable"


def test_live_success_blocked(monkeypatch):
    _enable_telegram_rate_limited_conditional(monkeypatch)
    result = evaluate_manual_retry_eligibility(
        _attempt(), _live(has_live_success=True), source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "live_success_exists"


def test_incompatible_content_state_blocked(monkeypatch):
    _enable_telegram_rate_limited_conditional(monkeypatch)
    result = evaluate_manual_retry_eligibility(
        _attempt(), _live(content_status="published"), source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "incompatible_content_state"


def test_stale_publish_version_blocked(monkeypatch):
    _enable_telegram_rate_limited_conditional(monkeypatch)
    result = evaluate_manual_retry_eligibility(
        _attempt(publish_version="pv_old"),
        _live(current_publish_version="pv_new"),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "stale_publish_version"


def test_retry_budget_exhausted_blocked():
    result = evaluate_manual_retry_eligibility(
        _attempt(status=STATUS_EXHAUSTED, failure_code="rate_limited", attempt_number=5),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "retry_budget_exhausted"


def test_attempt_number_at_max_blocked(monkeypatch):
    monkeypatch.setattr(
        "app.services.manual_retry_eligibility.PublishResilienceService.max_attempts",
        staticmethod(lambda: 5),
    )
    result = evaluate_manual_retry_eligibility(
        _attempt(attempt_number=5, failure_code="rate_limited"),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "retry_budget_exhausted"


def test_conditional_telegram_allowlist_is_empty():
    from app.services import manual_retry_eligibility as mod

    assert mod._CONDITIONAL_TELEGRAM_CODES == frozenset()


def test_telegram_rate_limited_not_allowed_after_classification_gate():
    """Telegram Bot API 429 is not structured into failure_code today — fail closed."""
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="rate_limited", platform="telegram"),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.safety_class == "OPERATOR_REVIEW"
    assert result.mobile_eligible is False


def test_telegram_provider_transient_not_allowed():
    """provider_transient is Meta-text only; never proven for Telegram write boundary."""
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="provider_transient", platform="telegram"),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.safety_class == "OPERATOR_REVIEW"


def test_meta_rate_limited_not_allowed_even_with_live_smoke(monkeypatch):
    monkeypatch.setattr(
        "app.services.manual_retry_eligibility.facebook_live_smoke_enabled",
        lambda: True,
    )
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="rate_limited", platform="facebook"),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.safety_class == "OPERATOR_REVIEW"


def test_facebook_live_smoke_disabled_blocks(monkeypatch):
    monkeypatch.setattr(
        "app.services.manual_retry_eligibility.facebook_live_smoke_enabled",
        lambda: False,
    )
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="rate_limited", platform="facebook"),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "platform_execution_unavailable"


def test_mock_linkedin_blocked():
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="rate_limited", platform="linkedin"),
        _live(),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "mock_platform"


def test_mobile_source_always_blocked():
    result = evaluate_manual_retry_eligibility(
        _attempt(), _live(), source="mobile", actor_role="operator",
    )
    assert result.allowed is False
    assert result.reason_code == "mobile_retry_not_enabled"
    assert result.mobile_eligible is False


def test_admin_cannot_bypass_ambiguous():
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="publish_timeout", platform="facebook"),
        _live(),
        source="admin",
        actor_role="admin",
    )
    assert result.allowed is False
    assert result.safety_class == "OPERATOR_REVIEW"


def test_operator_cannot_bypass_permanent():
    result = evaluate_manual_retry_eligibility(
        _attempt(failure_code="auth_or_permission"),
        _live(),
        source="workspace",
        actor_role="operator",
    )
    assert result.allowed is False
    assert result.safety_class == "PERMANENT_BLOCK"


def test_unknown_live_success_fails_closed(monkeypatch):
    _enable_telegram_rate_limited_conditional(monkeypatch)
    result = evaluate_manual_retry_eligibility(
        _attempt(),
        ManualRetryLiveState(has_live_success=None, content_status="failed"),
        source="workspace",
    )
    assert result.allowed is False
    assert result.reason_code == "live_success_unknown"


def test_no_safe_or_conditional_manual_retry_path_in_3c1a():
    """3C.1A final gate: SAFE and CONDITIONAL allowlists are both empty."""
    result = evaluate_manual_retry_eligibility(_attempt(), _live(), source="workspace")
    assert result.allowed is False
    assert result.safety_class == "OPERATOR_REVIEW"
    assert result.safety_class != "SAFE_MANUAL_RETRY"
    assert result.safety_class != "CONDITIONAL_MANUAL_RETRY"


# ── Workspace actions[] ────────────────────────────────────────────────────


def test_workspace_actions_omit_enabled_retry_when_allowlist_empty():
    actions = OperatorWorkspaceActionService.derive_actions(_item())
    assert all(not (a.action_id == ACTION_RETRY_PUBLISH and a.enabled) for a in actions)


def test_workspace_actions_omit_retry_for_null_failure_code():
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(metadata={
            "platform": "telegram",
            "failure_code": None,
            "attempt_number": 1,
            "has_live_success": False,
            "content_status": "failed",
            "publish_version": "pv_1",
            "current_publish_version": "pv_1",
        }),
    )
    assert all(a.action_id != ACTION_RETRY_PUBLISH for a in actions)


def test_workspace_actions_no_retry_for_exhausted():
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(
            current_state=STATUS_EXHAUSTED,
            metadata={
                "platform": "telegram",
                "failure_code": "rate_limited",
                "attempt_number": 5,
                "has_live_success": False,
                "content_status": "failed",
                "publish_version": "pv_1",
                "current_publish_version": "pv_1",
            },
        ),
    )
    retry = next((a for a in actions if a.action_id == ACTION_RETRY_PUBLISH), None)
    if retry is not None:
        assert retry.enabled is False


def test_workspace_actions_operator_review_navigation_only():
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(current_state=STATUS_OPERATOR_REVIEW),
    )
    assert all(a.action_id != ACTION_RETRY_PUBLISH for a in actions)


# ── Execution-time validation ──────────────────────────────────────────────


def test_execution_uses_same_policy_and_blocks_when_state_changes():
    tenant_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    attempt = _attempt(status=STATUS_FAILED, failure_code="rate_limited")
    attempt.id = attempt_id
    attempt.content_id = uuid.uuid4()

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with (
                patch(
                    "app.services.operator_workspace_actions.PublishAttemptOpsService._load_attempt",
                    new=AsyncMock(return_value=attempt),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishService._get_content",
                    new=AsyncMock(return_value=SimpleNamespace(
                        id=attempt.content_id, client_id=uuid.uuid4(), status="failed",
                        caption_long_ru="", caption_long_en="", caption_short_ru="",
                        hashtags="", media_file_id=None, platforms=["telegram"],
                        updated_at=None,
                    )),
                ),
                patch(
                    "app.services.operator_workspace_actions.build_manual_retry_live_state",
                    new=AsyncMock(return_value=_live(has_live_success=True)),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishAttemptOpsService.manual_retry",
                    new=AsyncMock(),
                ) as retry,
            ):
                with pytest.raises(HTTPException) as exc:
                    await OperatorWorkspaceActionService.execute(
                        db,
                        attention_id=f"publish-attempt:{attempt_id}",
                        action_id=ACTION_RETRY_PUBLISH,
                        actor_id=None,
                        tenant_id=tenant_id,
                        source="web",
                    )
            assert exc.value.status_code == 409
            retry.assert_not_awaited()
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_execution_blocks_when_allowlist_empty_no_provider_io():
    """With EMPTY conditional set, execution revalidates and never calls provider retry."""
    tenant_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    content_id = uuid.uuid4()
    attempt = _attempt(status=STATUS_FAILED, failure_code="rate_limited")
    attempt.id = attempt_id
    attempt.content_id = content_id

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with (
                patch(
                    "app.services.operator_workspace_actions.PublishAttemptOpsService._load_attempt",
                    new=AsyncMock(return_value=attempt),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishService._get_content",
                    new=AsyncMock(return_value=SimpleNamespace(
                        id=content_id, client_id=uuid.uuid4(), status="failed",
                        caption_long_ru="", caption_long_en="", caption_short_ru="",
                        hashtags="", media_file_id=None, platforms=["telegram"],
                        updated_at=None,
                    )),
                ),
                patch(
                    "app.services.operator_workspace_actions.build_manual_retry_live_state",
                    new=AsyncMock(return_value=_live()),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishAttemptOpsService.manual_retry",
                    new=AsyncMock(),
                ) as retry,
            ):
                with pytest.raises(HTTPException) as exc:
                    await OperatorWorkspaceActionService.execute(
                        db,
                        attention_id=f"publish-attempt:{attempt_id}",
                        action_id=ACTION_RETRY_PUBLISH,
                        actor_id=None,
                        tenant_id=tenant_id,
                        source="web",
                    )
            assert exc.value.status_code == 409
            retry.assert_not_awaited()
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_derive_execute_parity_when_conditional_code_temporarily_allowed(monkeypatch):
    """Prove single-policy wiring: derive allow ↔ execute allow when state unchanged."""
    from app.services.manual_retry_eligibility import ManualRetryEligibility

    _enable_telegram_rate_limited_conditional(monkeypatch)

    item = _item()
    actions = OperatorWorkspaceActionService.derive_actions(item)
    retry = next(a for a in actions if a.action_id == ACTION_RETRY_PUBLISH)
    assert retry.enabled is True

    eligibility = evaluate_manual_retry_eligibility(
        _attempt(failure_code="rate_limited", platform="telegram"),
        _live(),
        source="workspace",
    )
    assert eligibility.allowed is True
    assert eligibility.safety_class == "CONDITIONAL_MANUAL_RETRY"
    assert isinstance(eligibility, ManualRetryEligibility)


def test_mobile_source_retry_blocked_server_side():
    tenant_id = uuid.uuid4()
    attempt_id = uuid.uuid4()

    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.operator_workspace_actions.PublishAttemptOpsService.manual_retry",
            new=AsyncMock(),
        ) as retry:
            with pytest.raises(HTTPException) as exc:
                await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"publish-attempt:{attempt_id}",
                    action_id=ACTION_RETRY_PUBLISH,
                    actor_id=None,
                    tenant_id=tenant_id,
                    source="mobile",
                )
        assert exc.value.status_code == 403
        assert "Mobile" in exc.value.detail
        retry.assert_not_awaited()

    asyncio.run(_run())


def test_admin_ops_manual_retry_uses_policy_no_provider_on_deny():
    attempt_id = uuid.uuid4()
    attempt = _attempt(status=STATUS_FAILED, failure_code="publish_timeout", platform="facebook")
    attempt.id = attempt_id
    attempt.content_id = uuid.uuid4()

    async def _run():
        from app.services.publish_attempt_ops_service import PublishAttemptOpsService

        db = AsyncMock()
        with (
            patch.object(
                PublishAttemptOpsService,
                "_load_attempt",
                new=AsyncMock(return_value=attempt),
            ),
            patch(
                "app.services.publish_attempt_ops_service.PublishService._get_content",
                new=AsyncMock(return_value=SimpleNamespace(status="failed")),
            ),
            patch(
                "app.services.publish_attempt_ops_service.build_manual_retry_live_state",
                new=AsyncMock(return_value=_live()),
            ),
            patch(
                "app.services.publish_attempt_ops_service.PublishService.publish_content",
                new=AsyncMock(),
            ) as publish,
        ):
            result = await PublishAttemptOpsService.manual_retry(
                db, attempt_id, tenant_id=uuid.uuid4(), source="admin", actor_role="admin",
            )
        assert result["ok"] is False
        assert result["safety_class"] == "OPERATOR_REVIEW"
        publish.assert_not_awaited()

    asyncio.run(_run())


def test_automatic_retry_path_not_routed_through_manual_policy():
    """ScheduledPublishService must not import/call the new eligibility module."""
    import inspect
    from app.services import scheduled_publish_service

    source = inspect.getsource(scheduled_publish_service)
    assert "manual_retry_eligibility" not in source
    assert "evaluate_manual_retry_eligibility" not in source


def test_approve_content_unaffected():
    content_id = uuid.uuid4()
    actions = OperatorWorkspaceActionService.derive_actions(
        OperatorAttentionItem(
            id=f"content-review:{content_id}",
            attention_type="content_internal_review",
            priority="medium",
            client_id=uuid.uuid4(),
            company_name="Acme",
            content_id=content_id,
            title="Review",
            reason="ready",
            current_state="ready",
            responsible_party="operator",
            suggested_action="Approve",
            action_path=f"/content/{content_id}",
            source_domain="content",
            metadata={"reason_code": "internal_review"},
        ),
    )
    approve = next(a for a in actions if a.action_id == ACTION_APPROVE_CONTENT)
    assert approve.enabled is True


def test_acknowledge_alert_unaffected():
    actions = OperatorWorkspaceActionService.derive_actions(
        OperatorAttentionItem(
            id="publish-alert:11111111-1111-1111-1111-111111111111",
            attention_type="publishing_issue",
            priority="high",
            client_id=uuid.uuid4(),
            company_name="Acme",
            content_id=uuid.uuid4(),
            resource_id="11111111-1111-1111-1111-111111111111",
            title="Alert",
            reason="Needs review",
            current_state="open",
            responsible_party="operator",
            suggested_action="Review",
            action_path="/publishing/alerts",
            source_domain="publishing",
            metadata={"reason_code": "publish_alert", "alert_id": "11111111-1111-1111-1111-111111111111"},
        ),
    )
    assert actions[0].action_id == ACTION_ACKNOWLEDGE_ALERT
    assert actions[0].enabled is True
