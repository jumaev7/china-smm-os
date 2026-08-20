"""Operator Workspace Actions Phase 1 — eligibility, routing, RBAC, safety."""
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
from app.services.operator_workspace_actions import (
    ACTION_ACKNOWLEDGE_ALERT,
    ACTION_APPROVE_CONTENT,
    ACTION_OPEN,
    ACTION_RESOLVE_ALERT,
    ACTION_RETRY_PUBLISH,
    OperatorWorkspaceActionService,
    parse_attention_id,
    workspace_retry_allowed,
)
from app.services.operator_workspace_service import INTERNAL_REVIEW_STATUSES
from app.services.publish_resilience import (
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
)
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService


def _now():
    return datetime.now(timezone.utc)


def _item(**kwargs) -> OperatorAttentionItem:
    defaults = dict(
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
    )
    defaults.update(kwargs)
    return OperatorAttentionItem(**defaults)


def _attempt(*, status: str, external_post_id=None, next_retry_at=None):
    return SimpleNamespace(
        status=status,
        external_post_id=external_post_id,
        next_retry_at=next_retry_at,
        idempotency_key="idem-1",
    )


# ── Derivation ─────────────────────────────────────────────────────────────


def test_parse_attention_id_valid():
    prefix, key = parse_attention_id("publish-alert:abc")
    assert prefix == "publish-alert"
    assert key == "abc"


def test_parse_attention_id_invalid():
    with pytest.raises(HTTPException) as exc:
        parse_attention_id("nope")
    assert exc.value.status_code == 400


def test_alert_open_exposes_ack_resolve_and_open():
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(current_state="open"),
    )
    ids = [a.action_id for a in actions]
    assert ids == [ACTION_ACKNOWLEDGE_ALERT, ACTION_RESOLVE_ALERT, ACTION_OPEN]
    assert actions[0].primary is True
    assert actions[0].requires_confirmation is False
    assert actions[1].requires_confirmation is True


def test_alert_acknowledged_exposes_resolve_as_primary():
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(current_state="acknowledged"),
    )
    ids = [a.action_id for a in actions]
    assert ACTION_ACKNOWLEDGE_ALERT not in ids
    assert actions[0].action_id == ACTION_RESOLVE_ALERT
    assert actions[0].primary is True


def test_failed_publish_exposes_retry():
    attempt_id = str(uuid.uuid4())
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(
            id=f"publish-attempt:{attempt_id}",
            resource_id=attempt_id,
            current_state=STATUS_FAILED,
            metadata={"reason_code": "publish_failed", "attempt_id": attempt_id},
            action_path="/content/x",
        ),
    )
    retry = next(a for a in actions if a.action_id == ACTION_RETRY_PUBLISH)
    assert retry.enabled is True
    assert retry.requires_confirmation is True
    assert retry.external_side_effect is True
    assert "publication again" in (retry.confirmation_message or "")


def test_operator_review_does_not_expose_retry():
    attempt_id = str(uuid.uuid4())
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(
            id=f"publish-attempt:{attempt_id}",
            resource_id=attempt_id,
            current_state=STATUS_OPERATOR_REVIEW,
            metadata={"reason_code": "publish_operator_review", "attempt_id": attempt_id},
        ),
    )
    assert all(a.action_id != ACTION_RETRY_PUBLISH for a in actions)
    assert actions[0].action_id == ACTION_OPEN
    assert actions[0].action_type == "navigation"


def test_in_progress_publish_retry_disabled_or_absent():
    attempt_id = str(uuid.uuid4())
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(
            id=f"publish-attempt:{attempt_id}",
            resource_id=attempt_id,
            current_state=STATUS_IN_PROGRESS,
            metadata={"reason_code": "publish_stuck", "attempt_id": attempt_id},
        ),
    )
    retry = next((a for a in actions if a.action_id == ACTION_RETRY_PUBLISH), None)
    if retry is not None:
        assert retry.enabled is False


def test_content_review_exposes_approve():
    content_id = uuid.uuid4()
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(
            id=f"content-review:{content_id}",
            content_id=content_id,
            attention_type="content_internal_review",
            current_state="ready",
            source_domain="content",
            metadata={"reason_code": "internal_review"},
            action_path=f"/content/{content_id}",
        ),
    )
    approve = next(a for a in actions if a.action_id == ACTION_APPROVE_CONTENT)
    assert approve.enabled is True
    assert approve.requires_confirmation is True
    assert approve.primary is True


def test_waiting_client_is_navigation_only():
    client_id = uuid.uuid4()
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(
            id=f"waiting-client:{client_id}",
            attention_type="waiting_for_client",
            current_state="pending",
            responsible_party="client",
            source_domain="content",
            metadata={"reason_code": "client_pending"},
            action_path="/content",
        ),
    )
    assert len(actions) == 1
    assert actions[0].action_id == ACTION_OPEN
    assert actions[0].action_type == "navigation"


def test_automation_failure_is_navigation_only():
    job_id = uuid.uuid4()
    actions = OperatorWorkspaceActionService.derive_actions(
        _item(
            id=f"automation:{job_id}",
            attention_type="automation_failure",
            current_state="dead_letter",
            source_domain="automation",
            metadata={"reason_code": "automation_dead_letter"},
            action_path="/automation",
        ),
    )
    assert all(a.action_type == "navigation" for a in actions)
    assert all(a.action_id not in (ACTION_RETRY_PUBLISH, ACTION_APPROVE_CONTENT) for a in actions)


def test_workspace_retry_blocks_operator_review():
    allowed, reason = workspace_retry_allowed(_attempt(status=STATUS_OPERATOR_REVIEW))
    assert allowed is False
    assert reason and "verification" in reason.lower()


def test_workspace_retry_allows_failed():
    with patch(
        "app.services.operator_workspace_actions.PublishResilienceService.manual_retry_allowed",
        return_value=(True, None),
    ):
        allowed, reason = workspace_retry_allowed(_attempt(status=STATUS_FAILED))
    assert allowed is True
    assert reason is None


def test_workspace_retry_blocks_in_progress():
    allowed, _ = workspace_retry_allowed(_attempt(status=STATUS_IN_PROGRESS))
    assert allowed is False


# ── Execution ──────────────────────────────────────────────────────────────


def test_open_action_rejected_on_mutation_endpoint():
    async def _run():
        with pytest.raises(HTTPException) as exc:
            await OperatorWorkspaceActionService.execute(
                MagicMock(),
                attention_id="publish-alert:11111111-1111-1111-1111-111111111111",
                action_id=ACTION_OPEN,
                actor_id=None,
                tenant_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 400
        assert "Navigation" in exc.value.detail

    asyncio.run(_run())


def test_acknowledge_alert_delegates_to_canonical_service():
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    alert = SimpleNamespace(
        id=alert_id,
        tenant_id=tenant_id,
        content_id=uuid.uuid4(),
        state="open",
    )
    content = SimpleNamespace(id=alert.content_id, client_id=uuid.uuid4())

    ack_response = SimpleNamespace(id=alert_id, state="acknowledged")

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=(content.client_id,)))
        try:
            with (
                patch.object(
                    OperatorWorkspaceActionService,
                    "_load_alert_scoped",
                    new=AsyncMock(return_value=(alert, tenant_id)),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishOperatorAlertService.acknowledge",
                    new=AsyncMock(return_value=ack_response),
                ) as ack,
            ):
                result = await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"publish-alert:{alert_id}",
                    action_id=ACTION_ACKNOWLEDGE_ALERT,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                )
            ack.assert_awaited_once()
            assert result.success is True
            assert result.attention_still_relevant is True
            assert result.canonical_state["state"] == "acknowledged"
            db.commit.assert_awaited()
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_duplicate_acknowledge_is_safe():
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    alert = SimpleNamespace(
        id=alert_id,
        tenant_id=tenant_id,
        content_id=uuid.uuid4(),
        state="acknowledged",
    )
    ack_response = SimpleNamespace(id=alert_id, state="acknowledged")

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with (
                patch.object(
                    OperatorWorkspaceActionService,
                    "_load_alert_scoped",
                    new=AsyncMock(return_value=(alert, tenant_id)),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishOperatorAlertService.acknowledge",
                    new=AsyncMock(return_value=ack_response),
                ) as ack,
            ):
                result = await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"publish-alert:{alert_id}",
                    action_id=ACTION_ACKNOWLEDGE_ALERT,
                    actor_id=None,
                    tenant_id=tenant_id,
                )
            ack.assert_awaited_once()
            assert result.success is True
            assert result.canonical_state["state"] == "acknowledged"
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_resolve_alert_clears_attention():
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    alert = SimpleNamespace(
        id=alert_id,
        tenant_id=tenant_id,
        content_id=uuid.uuid4(),
        state="open",
    )
    resolve_response = SimpleNamespace(id=alert_id, state="resolved")

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with (
                patch.object(
                    OperatorWorkspaceActionService,
                    "_load_alert_scoped",
                    new=AsyncMock(return_value=(alert, tenant_id)),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishOperatorAlertService.resolve_manual",
                    new=AsyncMock(return_value=resolve_response),
                ),
            ):
                result = await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"publish-alert:{alert_id}",
                    action_id=ACTION_RESOLVE_ALERT,
                    actor_id=uuid.uuid4(),
                    tenant_id=tenant_id,
                )
            assert result.success is True
            assert result.attention_still_relevant is False
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_acknowledge_resolved_alert_returns_conflict():
    tenant_id = uuid.uuid4()
    alert_id = uuid.uuid4()
    alert = SimpleNamespace(
        id=alert_id,
        tenant_id=tenant_id,
        content_id=uuid.uuid4(),
        state="resolved",
    )

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with patch.object(
                OperatorWorkspaceActionService,
                "_load_alert_scoped",
                new=AsyncMock(return_value=(alert, tenant_id)),
            ):
                with pytest.raises(HTTPException) as exc:
                    await OperatorWorkspaceActionService.execute(
                        db,
                        attention_id=f"publish-alert:{alert_id}",
                        action_id=ACTION_ACKNOWLEDGE_ALERT,
                        actor_id=None,
                        tenant_id=tenant_id,
                    )
            assert exc.value.status_code == 409
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_retry_delegates_to_canonical_manual_retry():
    tenant_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    content_id = uuid.uuid4()
    attempt = SimpleNamespace(
        id=attempt_id,
        status=STATUS_FAILED,
        external_post_id=None,
        next_retry_at=None,
        idempotency_key="k1",
        content_id=content_id,
    )

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
                    "app.services.operator_workspace_actions.PublishResilienceService.find_live_success",
                    new=AsyncMock(return_value=None),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishResilienceService.manual_retry_allowed",
                    return_value=(True, None),
                ),
                patch(
                    "app.services.operator_workspace_actions.PublishAttemptOpsService.manual_retry",
                    new=AsyncMock(return_value={
                        "ok": True,
                        "message": "Publish completed",
                        "content_id": content_id,
                        "status": "published",
                    }),
                ) as retry,
            ):
                result = await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"publish-attempt:{attempt_id}",
                    action_id=ACTION_RETRY_PUBLISH,
                    actor_id=None,
                    tenant_id=tenant_id,
                )
            retry.assert_awaited_once_with(db, attempt_id, tenant_id=tenant_id)
            assert result.success is True
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_retry_operator_review_returns_conflict():
    tenant_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    attempt = SimpleNamespace(
        id=attempt_id,
        status=STATUS_OPERATOR_REVIEW,
        external_post_id=None,
        next_retry_at=None,
        idempotency_key="k1",
        content_id=uuid.uuid4(),
    )

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
                    )
            assert exc.value.status_code == 409
            retry.assert_not_awaited()
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_retry_in_progress_returns_conflict():
    tenant_id = uuid.uuid4()
    attempt_id = uuid.uuid4()
    attempt = SimpleNamespace(
        id=attempt_id,
        status=STATUS_IN_PROGRESS,
        external_post_id=None,
        next_retry_at=None,
        idempotency_key=None,
        content_id=uuid.uuid4(),
    )

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=()))
        try:
            with patch(
                "app.services.operator_workspace_actions.PublishAttemptOpsService._load_attempt",
                new=AsyncMock(return_value=attempt),
            ):
                with pytest.raises(HTTPException) as exc:
                    await OperatorWorkspaceActionService.execute(
                        db,
                        attention_id=f"publish-attempt:{attempt_id}",
                        action_id=ACTION_RETRY_PUBLISH,
                        actor_id=None,
                        tenant_id=tenant_id,
                    )
            assert exc.value.status_code == 409
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_approve_delegates_to_content_service():
    content_id = uuid.uuid4()
    item = SimpleNamespace(
        id=content_id,
        status="ready",
        approved_at=None,
        client_review_status=None,
        client_id=uuid.uuid4(),
    )
    approved = SimpleNamespace(
        id=content_id,
        status="approved",
        client_review_status="pending",
    )

    async def _run():
        db = AsyncMock()
        with (
            patch(
                "app.services.operator_workspace_actions.ContentService.get",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "app.services.operator_workspace_actions.ContentService.approve",
                new=AsyncMock(return_value=approved),
            ) as approve,
        ):
            result = await OperatorWorkspaceActionService.execute(
                db,
                attention_id=f"content-review:{content_id}",
                action_id=ACTION_APPROVE_CONTENT,
                actor_id=None,
                tenant_id=uuid.uuid4(),
            )
        approve.assert_awaited_once_with(db, content_id)
        assert result.success is True
        assert result.canonical_state["client_review_status"] == "pending"
        assert result.attention_still_relevant is False

    asyncio.run(_run())


def test_approve_already_approved_is_idempotent():
    content_id = uuid.uuid4()
    item = SimpleNamespace(
        id=content_id,
        status="approved",
        approved_at=_now(),
        client_review_status="pending",
        client_id=uuid.uuid4(),
    )

    async def _run():
        db = AsyncMock()
        with (
            patch(
                "app.services.operator_workspace_actions.ContentService.get",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "app.services.operator_workspace_actions.ContentService.approve",
                new=AsyncMock(),
            ) as approve,
        ):
            result = await OperatorWorkspaceActionService.execute(
                db,
                attention_id=f"content-review:{content_id}",
                action_id=ACTION_APPROVE_CONTENT,
                actor_id=None,
                tenant_id=uuid.uuid4(),
            )
        approve.assert_not_awaited()
        assert result.success is True
        assert "already approved" in result.message.lower()

    asyncio.run(_run())


def test_approve_does_not_bypass_client_pending():
    content_id = uuid.uuid4()
    item = SimpleNamespace(
        id=content_id,
        status="ready",
        approved_at=None,
        client_review_status="pending",
        client_id=uuid.uuid4(),
    )

    async def _run():
        db = AsyncMock()
        with (
            patch(
                "app.services.operator_workspace_actions.ContentService.get",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "app.services.operator_workspace_actions.ContentService.approve",
                new=AsyncMock(),
            ) as approve,
        ):
            with pytest.raises(HTTPException) as exc:
                await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"content-review:{content_id}",
                    action_id=ACTION_APPROVE_CONTENT,
                    actor_id=None,
                    tenant_id=uuid.uuid4(),
                )
        assert exc.value.status_code == 409
        approve.assert_not_awaited()

    asyncio.run(_run())


def test_stale_content_status_returns_conflict():
    content_id = uuid.uuid4()
    item = SimpleNamespace(
        id=content_id,
        status="published",
        approved_at=_now(),
        client_review_status="approved",
        client_id=uuid.uuid4(),
    )

    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.operator_workspace_actions.ContentService.get",
            new=AsyncMock(return_value=item),
        ):
            with pytest.raises(HTTPException) as exc:
                await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"content-review:{content_id}",
                    action_id=ACTION_APPROVE_CONTENT,
                    actor_id=None,
                    tenant_id=uuid.uuid4(),
                )
        assert exc.value.status_code == 409

    asyncio.run(_run())


def test_cross_tenant_alert_rejected():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    alert_id = uuid.uuid4()
    alert = SimpleNamespace(
        id=alert_id,
        tenant_id=tenant_b,
        content_id=uuid.uuid4(),
        state="open",
    )

    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_a, client_ids=()))
        try:
            with pytest.raises(HTTPException) as exc:
                await OperatorWorkspaceActionService._resolve_alert_tenant(
                    db, alert, tenant_id=tenant_a,
                )
            assert exc.value.status_code == 404
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_sales_role_denied_by_workspace_gate():
    user = CurrentTenantUser(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="sales@example.com",
        role="sales",
        status="active",
        permissions=[],
    )
    with pytest.raises(HTTPException) as exc:
        TenantAuthService.assert_role(user, "owner", "manager", "operator")
    assert exc.value.status_code == 403


def test_viewer_role_denied_by_workspace_gate():
    user = CurrentTenantUser(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        email="viewer@example.com",
        role="viewer",
        status="active",
        permissions=[],
    )
    with pytest.raises(HTTPException) as exc:
        TenantAuthService.assert_role(user, "owner", "manager", "operator")
    assert exc.value.status_code == 403


def test_owner_manager_operator_roles_allowed():
    for role in ("owner", "manager", "operator"):
        user = CurrentTenantUser(
            id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            email=f"{role}@example.com",
            role=role,
            status="active",
            permissions=[],
        )
        TenantAuthService.assert_role(user, "owner", "manager", "operator")


def test_action_on_wrong_attention_prefix_rejected():
    async def _run():
        with pytest.raises(HTTPException) as exc:
            await OperatorWorkspaceActionService.execute(
                MagicMock(),
                attention_id=f"automation:{uuid.uuid4()}",
                action_id=ACTION_RETRY_PUBLISH,
                actor_id=None,
                tenant_id=uuid.uuid4(),
            )
        assert exc.value.status_code == 400

    asyncio.run(_run())


def test_internal_review_statuses_cover_approve_gate():
    assert "ready" in INTERNAL_REVIEW_STATUSES
    assert "approved" not in INTERNAL_REVIEW_STATUSES
    assert "published" not in INTERNAL_REVIEW_STATUSES
