"""Integration Health Automation Phase 1 — taxonomy, checks, isolation, safety."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.api_auth_context import ApiAuthContext, _auth_ctx
from app.services.integration_health.persistence import (
    apply_transient_failure,
    clear_transient_state,
    is_stale,
    read_diagnostic,
    write_diagnostic,
)
from app.services.integration_health.taxonomy import (
    REASON_CODES,
    REASON_DISCONNECTED,
    REASON_EXPIRED_TOKEN,
    REASON_HEALTHY,
    REASON_MISSING_OPTIONAL_SCOPE,
    REASON_MISSING_REQUIRED_SCOPE,
    REASON_NEVER_CHECKED,
    REASON_TRANSIENT_PROVIDER_ERROR,
    TRANSIENT_ESCALATION_THRESHOLD,
    TRANSIENT_WINDOW_SECONDS,
    reason_meta,
)
from app.services.integration_health.checks import _build_result, evaluate_meta_account
from app.services.integration_health.service import IntegrationHealthService
from app.services.meta_graph_client import MetaGraphError
from app.services.operator_workspace_service import OperatorWorkspaceService
from app.services.tenant_auth_service import TenantAuthService


def _now():
    return datetime.now(timezone.utc)


def _account(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        platform="facebook",
        account_name="Acme Page",
        account_id="page-1",
        access_token_encrypted="enc-token",
        refresh_token_encrypted=None,
        expires_at=_now() + timedelta(days=30),
        facebook_page_id="123",
        instagram_business_account_id=None,
        permissions_json=json.dumps([
            "pages_show_list",
            "instagram_basic",
            "business_management",
            "pages_manage_posts",
            "pages_read_engagement",
            "pages_read_user_content",
        ]),
        account_metadata_json=None,
        status="connected",
        created_at=_now(),
        updated_at=_now(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _user(role: str):
    return SimpleNamespace(
        role=role,
        tenant_id=uuid.uuid4(),
        has_permission=lambda _p: False,
    )


def test_all_reason_codes_have_meta():
    for code in REASON_CODES:
        meta = reason_meta(code)
        assert meta["status"]
        assert "requires_operator_action" in meta
        assert "safe_auto_recheck" in meta
        assert meta["explanation"]


def test_unknown_reason_falls_back():
    assert reason_meta("not_a_real_code")["status"] == "unknown"


def test_write_read_roundtrip_no_secrets():
    acct = _account()
    write_diagnostic(
        acct,
        {
            "status": "healthy",
            "reason_code": "healthy",
            "checked_at": _now().isoformat(),
            "access_token": "SHOULD_NOT_PERSIST",
            "token_secret": "nope",
        },
    )
    diag = read_diagnostic(acct)
    assert diag["status"] == "healthy"
    assert "access_token" not in diag
    raw = acct.account_metadata_json or ""
    assert "SHOULD_NOT_PERSIST" not in raw
    assert "nope" not in raw


def test_transient_escalation_and_clear():
    diag: dict = {}
    now = _now()
    for i in range(TRANSIENT_ESCALATION_THRESHOLD):
        diag = apply_transient_failure(
            diag,
            now=now + timedelta(minutes=i),
            window_seconds=TRANSIENT_WINDOW_SECONDS,
            threshold=TRANSIENT_ESCALATION_THRESHOLD,
        )
    assert diag["escalated"] is True
    cleared = clear_transient_state(diag)
    assert cleared["transient_failure_count"] == 0
    assert cleared["escalated"] is False


def test_stale_detection():
    assert is_stale(None, stale_after_seconds=60) is True
    assert is_stale(_now(), stale_after_seconds=3600) is False
    assert is_stale(_now() - timedelta(hours=2), stale_after_seconds=3600) is True


def test_healthy_integration():
    async def _run():
        acct = _account()
        with patch(
            "app.services.integration_health.checks.meta_oauth_configured",
            return_value=False,
        ):
            return await evaluate_meta_account(acct, live_check=False)

    result = asyncio.run(_run())
    assert result.status in ("healthy", "degraded")
    assert any(c.name == "publishing" for c in result.capabilities)
    assert "enc-token" not in json.dumps(result.to_public_dict())


def test_disconnected_action_required():
    result = asyncio.run(evaluate_meta_account(_account(status="disconnected"), live_check=False))
    assert result.status == "action_required"
    assert result.reason_code == REASON_DISCONNECTED
    assert result.requires_operator_action is True


def test_expired_authorization():
    result = asyncio.run(
        evaluate_meta_account(_account(expires_at=_now() - timedelta(hours=1)), live_check=False)
    )
    assert result.reason_code == REASON_EXPIRED_TOKEN
    assert result.status == "action_required"


def test_missing_required_scope():
    result = asyncio.run(
        evaluate_meta_account(
            _account(permissions_json=json.dumps(["pages_show_list"])),
            live_check=False,
        )
    )
    assert result.reason_code == REASON_MISSING_REQUIRED_SCOPE
    pub = next(c for c in result.capabilities if c.name == "publishing")
    assert pub.status == "action_required"


def test_missing_optional_listening_does_not_break_publishing():
    result = asyncio.run(
        evaluate_meta_account(
            _account(
                permissions_json=json.dumps([
                    "pages_show_list",
                    "instagram_basic",
                    "business_management",
                    "pages_manage_posts",
                ]),
            ),
            live_check=False,
        )
    )
    pub = next(c for c in result.capabilities if c.name == "publishing")
    listen = next(c for c in result.capabilities if c.name == "listening")
    assert pub.status == "healthy"
    assert listen.status == "action_required"
    assert listen.reason_code == REASON_MISSING_OPTIONAL_SCOPE
    assert result.reason_code == REASON_MISSING_OPTIONAL_SCOPE
    assert result.status == "degraded"


def test_provider_timeout_transient():
    async def _run():
        with (
            patch(
                "app.services.integration_health.checks.meta_oauth_configured",
                return_value=True,
            ),
            patch(
                "app.services.integration_health.checks.decrypt_token",
                return_value="tok",
            ),
            patch(
                "app.services.integration_health.checks.debug_token",
                side_effect=MetaGraphError("timeout", is_timeout=True, is_transient=True),
            ),
        ):
            return await evaluate_meta_account(_account(), live_check=True, prior_diag={})

    result = asyncio.run(_run())
    assert result.reason_code == REASON_TRANSIENT_PROVIDER_ERROR
    assert result.status == "degraded"
    assert result.requires_operator_action is False
    assert result.responsible_party == "system"
    assert result.transient_failure_count == 1


def test_repeated_transient_escalates():
    prior = {
        "transient_failure_count": TRANSIENT_ESCALATION_THRESHOLD - 1,
        "transient_window_started_at": _now().isoformat(),
        "escalated": False,
    }

    async def _run():
        with (
            patch(
                "app.services.integration_health.checks.meta_oauth_configured",
                return_value=True,
            ),
            patch(
                "app.services.integration_health.checks.decrypt_token",
                return_value="tok",
            ),
            patch(
                "app.services.integration_health.checks.debug_token",
                side_effect=MetaGraphError("timeout", is_timeout=True),
            ),
        ):
            return await evaluate_meta_account(_account(), live_check=True, prior_diag=prior)

    result = asyncio.run(_run())
    assert result.transient_failure_count >= TRANSIENT_ESCALATION_THRESHOLD
    assert result.status == "unavailable"
    assert result.responsible_party == "provider"
    assert result.requires_operator_action is False


def test_later_success_clears_transient():
    prior = {
        "transient_failure_count": 2,
        "transient_window_started_at": _now().isoformat(),
        "escalated": False,
    }

    async def _run():
        with (
            patch(
                "app.services.integration_health.checks.meta_oauth_configured",
                return_value=True,
            ),
            patch(
                "app.services.integration_health.checks.decrypt_token",
                return_value="tok",
            ),
            patch(
                "app.services.integration_health.checks.debug_token",
                AsyncMock(
                    return_value={
                        "is_valid": True,
                        "scopes": [
                            "pages_show_list",
                            "instagram_basic",
                            "business_management",
                            "pages_manage_posts",
                            "pages_read_engagement",
                            "pages_read_user_content",
                        ],
                    }
                ),
            ),
        ):
            return await evaluate_meta_account(_account(), live_check=True, prior_diag=prior)

    result = asyncio.run(_run())
    assert result.transient_failure_count == 0
    assert result.status in ("healthy", "degraded")


def test_stale_healthy_not_trusted():
    result = _build_result(
        integration_id="x",
        platform="facebook",
        provider="meta",
        tenant_id=uuid.uuid4(),
        client_id=None,
        account_name="A",
        reason_code=REASON_HEALTHY,
        checked_at=_now() - timedelta(days=21),
        last_success_at=_now() - timedelta(days=21),
        stale_after_seconds=12 * 3600,
    )
    assert result.stale is True
    assert result.status != "healthy"


def test_never_checked_not_falsely_healthy():
    result = _build_result(
        integration_id="x",
        platform="facebook",
        provider="meta",
        tenant_id=uuid.uuid4(),
        client_id=None,
        account_name="A",
        reason_code=REASON_HEALTHY,
        checked_at=None,
        last_success_at=None,
        stale_after_seconds=3600,
        never_checked=True,
    )
    assert result.status == "unknown"
    assert result.reason_code == REASON_NEVER_CHECKED


def test_healthy_absent_from_workspace():
    async def _run():
        tid = uuid.uuid4()
        acct = _account(tenant_id=tid, status="connected")
        write_diagnostic(
            acct,
            {
                "status": "healthy",
                "reason_code": "healthy",
                "requires_operator_action": False,
                "checked_at": _now().isoformat(),
            },
        )

        class _Scalars:
            def all(self):
                return [acct]

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_Scalars())
        items = []
        with patch.object(OperatorWorkspaceService, "_tenant_filter", return_value=None):
            await OperatorWorkspaceService._collect_integration_issues(db, tid, items.append)
        return items

    assert asyncio.run(_run()) == []


def test_actionable_appears_in_workspace():
    async def _run():
        tid = uuid.uuid4()
        acct = _account(tenant_id=tid, status="expired")
        write_diagnostic(
            acct,
            {
                "status": "action_required",
                "reason_code": "expired_token",
                "reason": "Authorization expired",
                "requires_operator_action": True,
                "responsible_party": "client",
                "recommended_next_step": "Reconnect",
                "checked_at": _now().isoformat(),
            },
        )

        class _Scalars:
            def all(self):
                return [acct]

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_Scalars())
        items = []
        with patch.object(OperatorWorkspaceService, "_tenant_filter", return_value=None):
            await OperatorWorkspaceService._collect_integration_issues(db, tid, items.append)
        return items

    items = asyncio.run(_run())
    assert len(items) == 1
    assert items[0].attention_type == "integration_issue"
    assert items[0].metadata["reason_code"] == "expired_token"
    assert items[0].responsible_party == "client"


def test_system_owned_transient_not_operator_action():
    async def _run():
        tid = uuid.uuid4()
        acct = _account(tenant_id=tid, status="connected")
        write_diagnostic(
            acct,
            {
                "status": "degraded",
                "reason_code": "transient_provider_error",
                "requires_operator_action": False,
                "responsible_party": "system",
                "transient_failure_count": 1,
                "escalated": False,
                "checked_at": _now().isoformat(),
            },
        )

        class _Scalars:
            def all(self):
                return [acct]

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_Scalars())
        items = []
        with patch.object(OperatorWorkspaceService, "_tenant_filter", return_value=None):
            await OperatorWorkspaceService._collect_integration_issues(db, tid, items.append)
        return items

    assert asyncio.run(_run()) == []


def test_sales_viewer_denied():
    with pytest.raises(HTTPException) as exc:
        TenantAuthService.assert_role(_user("sales"), "owner", "manager", "operator")
    assert exc.value.status_code == 403


def test_owner_allowed():
    TenantAuthService.assert_role(_user("owner"), "owner", "manager", "operator")


def test_manager_operator_allowed():
    TenantAuthService.assert_role(_user("manager"), "owner", "manager", "operator")
    TenantAuthService.assert_role(_user("operator"), "owner", "manager", "operator")


def test_viewer_denied():
    with pytest.raises(HTTPException):
        TenantAuthService.assert_role(_user("viewer"), "owner", "manager", "operator")


def test_cross_tenant_denied():
    tid_a = uuid.uuid4()
    tid_b = uuid.uuid4()
    token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tid_a, client_ids=()))
    try:
        from app.services.integration_health.service import _tenant_scope

        with pytest.raises(HTTPException) as exc:
            _tenant_scope(tid_b)
        assert exc.value.status_code == 404
    finally:
        _auth_ctx.reset(token)


def test_cross_tenant_client_filter_denied():
    tid = uuid.uuid4()
    allowed = uuid.uuid4()
    denied = uuid.uuid4()
    token = _auth_ctx.set(
        ApiAuthContext(kind="tenant", tenant_id=tid, client_ids=(allowed,))
    )
    try:
        from app.services.integration_health.service import _client_allowed

        with pytest.raises(HTTPException) as exc:
            _client_allowed(denied)
        assert exc.value.status_code == 404
    finally:
        _auth_ctx.reset(token)


def test_one_failure_does_not_stop_batch():
    async def _run():
        tid = uuid.uuid4()
        good = _account(tenant_id=tid, platform="facebook")
        bad = _account(tenant_id=tid, platform="instagram")

        class _Scalars:
            def all(self):
                return [good, bad]

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_Scalars())
        db.commit = AsyncMock()
        call_count = {"n": 0}

        async def _eval(db, account, *, live_check=False, persist=True):
            call_count["n"] += 1
            if account.platform == "instagram":
                raise RuntimeError("boom")
            return await evaluate_meta_account(account, live_check=False)

        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tid, client_ids=()))
        try:
            with (
                patch.object(IntegrationHealthService, "evaluate_account", side_effect=_eval),
                patch(
                    "app.services.integration_health.service.evaluate_telegram_tenant",
                    AsyncMock(return_value=[]),
                ),
                patch(
                    "app.services.integration_health.service.evaluate_advertising_accounts",
                    AsyncMock(return_value=[]),
                ),
                patch(
                    "app.services.integration_health.service.evaluate_listening_sources",
                    AsyncMock(return_value=[]),
                ),
            ):
                result = await IntegrationHealthService.list_health(
                    db,
                    tenant_id=tid,
                    live_check=False,
                )
            return result, call_count["n"]
        finally:
            _auth_ctx.reset(token)

    result, n = asyncio.run(_run())
    assert result["total"] >= 1
    assert n == 2


def test_no_provider_mutation_symbols_in_checks():
    import inspect
    import app.services.integration_health.checks as checks_mod

    src = inspect.getsource(checks_mod)
    for banned in (
        "publish_instagram",
        "publish_facebook",
        "send_message",
        "setWebhook",
        "start_oauth",
        "exchange_for_long_lived",
        "disconnect(",
    ):
        assert banned not in src


def test_public_payload_has_no_encrypted_token():
    result = _build_result(
        integration_id=str(uuid.uuid4()),
        platform="facebook",
        provider="meta",
        tenant_id=uuid.uuid4(),
        client_id=None,
        account_name="Acme",
        reason_code=REASON_HEALTHY,
        checked_at=_now(),
        last_success_at=_now(),
        stale_after_seconds=3600,
    )
    payload = json.dumps(result.to_public_dict())
    assert "access_token" not in payload
    assert "encrypted" not in payload


def test_summary_counts():
    items = [
        _build_result(
            integration_id="1",
            platform="facebook",
            provider="meta",
            tenant_id=uuid.uuid4(),
            client_id=None,
            account_name="A",
            reason_code=REASON_HEALTHY,
            checked_at=_now(),
            last_success_at=_now(),
            stale_after_seconds=999999,
        ),
        _build_result(
            integration_id="2",
            platform="facebook",
            provider="meta",
            tenant_id=uuid.uuid4(),
            client_id=None,
            account_name="B",
            reason_code=REASON_DISCONNECTED,
            checked_at=_now(),
            last_success_at=None,
            stale_after_seconds=999999,
        ),
    ]
    summary = IntegrationHealthService.summarize(items)
    assert summary["healthy"] == 1
    assert summary["action_required"] == 1


def test_rate_limit_classified():
    async def _run():
        with (
            patch(
                "app.services.integration_health.checks.meta_oauth_configured",
                return_value=True,
            ),
            patch(
                "app.services.integration_health.checks.decrypt_token",
                return_value="tok",
            ),
            patch(
                "app.services.integration_health.checks.debug_token",
                side_effect=MetaGraphError("rate", status_code=429, error_code=4, is_transient=True),
            ),
        ):
            return await evaluate_meta_account(_account(), live_check=True, prior_diag={})

    result = asyncio.run(_run())
    assert result.reason_code == "provider_rate_limited"
    assert result.requires_operator_action is False
