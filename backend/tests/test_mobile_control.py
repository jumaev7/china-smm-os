"""Mobile Operator Control Plane Phase 1 — aggregation, RBAC, safety, no leaks."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.schemas.mobile_control import (
    MobileBackupStatus,
    MobileControlCapabilities,
    MobileControlHomeResponse,
    MobileSystemStatusSummary,
)
from app.schemas.operator_workspace import OperatorAttentionItem, OperatorWorkspaceSummary
from app.services.mobile_control_service import (
    DEFAULT_URGENT_LIMIT,
    URGENT_PRIORITIES,
    MobileControlService,
)
from app.services.operator_workspace_actions import (
    ACTION_ACKNOWLEDGE_ALERT,
    ACTION_APPROVE_CONTENT,
    ACTION_OPEN,
    ACTION_RESOLVE_ALERT,
    ACTION_RETRY_PUBLISH,
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
        metadata={"reason_code": "publish_alert"},
    )
    defaults.update(kwargs)
    return OperatorAttentionItem(**defaults)


# ── Capabilities / schema ───────────────────────────────────────────────────


def test_capabilities_are_conservative_phase1():
    caps = MobileControlService.capabilities()
    assert isinstance(caps, MobileControlCapabilities)
    assert caps.push_registration is False
    assert caps.backup_status_live is False
    assert caps.internal_content_reject is False
    assert caps.realtime_channel is False
    assert set(caps.actions_supported) == {
        ACTION_OPEN,
        ACTION_ACKNOWLEDGE_ALERT,
        ACTION_RESOLVE_ALERT,
        ACTION_RETRY_PUBLISH,
        ACTION_APPROVE_CONTENT,
    }


def test_backup_status_default_is_unavailable_no_paths():
    backup = MobileBackupStatus()
    assert backup.status == "unavailable"
    assert backup.last_successful_at is None
    blob = backup.model_dump_json().lower()
    assert "/var/" not in blob
    assert "r2" not in blob or "not exposed" in blob
    assert "password" not in blob
    assert "secret" not in blob
    assert "credential" not in blob


# ── Role gate (same as Operator Workspace) ───────────────────────────────────


def test_owner_manager_operator_allowed_for_mobile():
    for role in ("owner", "manager", "operator"):
        user = MagicMock(spec=CurrentTenantUser)
        user.role = role
        user.has_permission = MagicMock(return_value=True)
        TenantAuthService.assert_role(user, "owner", "manager", "operator")


def test_sales_viewer_denied_for_mobile():
    for role in ("sales", "viewer"):
        user = MagicMock(spec=CurrentTenantUser)
        user.role = role
        user.has_permission = MagicMock(return_value=False)
        with pytest.raises(HTTPException) as exc:
            TenantAuthService.assert_role(user, "owner", "manager", "operator")
        assert exc.value.status_code == 403


# ── Urgent selection + actions[] ─────────────────────────────────────────────


def test_select_urgent_prefers_critical_high_and_attaches_actions():
    low = _item(id="a", priority="low", attention_type="content_internal_review")
    medium = _item(id="b", priority="medium", attention_type="content_internal_review")
    high = _item(
        id="publish-alert:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        priority="high",
        current_state="open",
        resource_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    )
    critical = _item(
        id="publish-alert:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        priority="critical",
        current_state="open",
        resource_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    page = MobileControlService._select_urgent(
        [low, medium, high, critical],
        limit=10,
    )
    assert all(i.priority in URGENT_PRIORITIES for i in page)
    assert page[0].priority == "critical"
    assert page[1].priority == "high"
    assert len(page) == 2
    for item in page:
        assert item.actions, "actions[] must be attached for mobile UI"
        assert any(a.action_id == ACTION_OPEN for a in item.actions)


def test_select_urgent_respects_bounded_limit():
    items = [
        _item(
            id=f"publish-alert:{uuid.uuid4()}",
            priority="high",
            current_state="open",
            resource_id=str(uuid.uuid4()),
        )
        for _ in range(40)
    ]
    page = MobileControlService._select_urgent(items, limit=5)
    assert len(page) == 5


# ── System health sanitization ───────────────────────────────────────────────


def test_build_system_status_strips_secrets_and_pool_internals():
    async def _run():
        db = AsyncMock()
        raw = {
            "status": "ok",
            "uptime": 12345,
            "database": "ok",
            "db_pool": {"checked_out": 3, "pool_size": 10, "max_overflow": 5},
            "scheduler": "running",
            "ai_services": "ok",
            "telegram_bot": "configured",
            "demo_mode": False,
            "total_clients": 22,
            "total_leads": 100,
            "total_deals": 50,
            "total_content": 200,
            "total_posts": 150,
            "total_revenue": 999999,
            "total_commissions": 111,
            "OPENAI_API_KEY": "sk-secret",
            "DATABASE_URL": "postgresql://user:pass@host/db",
        }
        with patch(
            "app.services.mobile_control_service.SystemHealthService.health",
            new=AsyncMock(return_value=raw),
        ):
            status = await MobileControlService.build_system_status(
                db,
                integration_attention_count=2,
            )

        assert isinstance(status, MobileSystemStatusSummary)
        dumped = status.model_dump()
        blob = str(dumped).lower()
        assert "sk-secret" not in blob
        assert "postgresql://" not in blob
        assert "password" not in blob
        assert "db_pool" not in dumped
        assert "total_revenue" not in dumped
        assert "total_clients" not in dumped
        assert "openai" not in blob or "attention" in blob
        assert status.database == "ok"
        assert status.scheduler == "ok"
        assert status.telegram_bot == "ok"
        assert status.integration_attention_count == 2
        assert status.backup.status == "unavailable"
        assert status.uptime_seconds == 12345

    asyncio.run(_run())


def test_build_system_status_degraded_on_db_error():
    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.mobile_control_service.SystemHealthService.health",
            new=AsyncMock(return_value={"status": "degraded", "database": "error", "uptime": 1}),
        ):
            status = await MobileControlService.build_system_status(db)
        assert status.overall == "degraded"
        assert status.database == "degraded"

    asyncio.run(_run())


def test_build_system_status_failure_is_degraded_not_exception():
    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.mobile_control_service.SystemHealthService.health",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ):
            status = await MobileControlService.build_system_status(db)
        assert status.overall == "degraded"
        assert status.backup.status == "unavailable"

    asyncio.run(_run())


# ── Home aggregation ─────────────────────────────────────────────────────────


def test_get_home_aggregates_without_provider_calls_or_mutations():
    tenant_id = uuid.uuid4()
    items = [
        _item(
            id="content-review:cccccccc-cccc-cccc-cccc-cccccccccccc",
            attention_type="content_internal_review",
            priority="medium",
            current_state="ready_for_approval",
        ),
        _item(
            id="publish-alert:dddddddd-dddd-dddd-dddd-dddddddddddd",
            attention_type="publishing_issue",
            priority="critical",
            current_state="open",
            resource_id="dddddddd-dddd-dddd-dddd-dddddddddddd",
        ),
        _item(
            id="integration:eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
            attention_type="integration_issue",
            priority="high",
            current_state="disconnected",
        ),
        _item(
            id="waiting:ffffffff-ffff-ffff-ffff-ffffffffffff",
            attention_type="waiting_for_client",
            priority="low",
            responsible_party="client",
        ),
    ]
    summary = OperatorWorkspaceSummary(
        needs_action_now=2,
        waiting_for_client=1,
        publishing_issues=1,
        integration_issues=1,
        total=4,
    )

    async def _run():
        db = AsyncMock()
        with (
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._collect_items",
                new=AsyncMock(return_value=items),
            ) as collect,
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._build_summary",
                return_value=summary,
            ),
            patch(
                "app.services.mobile_control_service.NotificationService.get_unread_count",
                new=AsyncMock(return_value=SimpleNamespace(unread_count=3)),
            ) as unread,
            patch(
                "app.services.mobile_control_service.SystemHealthService.health",
                new=AsyncMock(
                    return_value={
                        "status": "ok",
                        "database": "ok",
                        "scheduler": "running",
                        "ai_services": "ok",
                        "telegram_bot": "configured",
                        "uptime": 9,
                    },
                ),
            ) as health,
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceActionService.execute",
                new=AsyncMock(),
            ) as mutate,
        ):
            home = await MobileControlService.get_home(
                db,
                urgent_limit=10,
                tenant_id=tenant_id,
            )

        assert isinstance(home, MobileControlHomeResponse)
        assert home.approvals_count == 1
        assert home.problems_count == 2  # publishing + integration
        assert home.waiting_for_client == 1
        assert home.unread_notifications == 3
        assert home.urgent_limit == 10
        assert len(home.urgent_items) == 2  # critical + high only
        assert all(i.priority in ("critical", "high") for i in home.urgent_items)
        assert home.capabilities.push_registration is False
        assert home.system_status.backup.status == "unavailable"
        assert home.deep_link_base == "/operator-workspace"
        collect.assert_awaited_once()
        unread.assert_awaited_once()
        health.assert_awaited_once()
        mutate.assert_not_awaited()

    asyncio.run(_run())


def test_get_home_clamps_urgent_limit():
    async def _run():
        db = AsyncMock()
        with (
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._collect_items",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._build_summary",
                return_value=OperatorWorkspaceSummary(),
            ),
            patch(
                "app.services.mobile_control_service.SystemHealthService.health",
                new=AsyncMock(return_value={"status": "ok", "database": "ok", "uptime": 1}),
            ),
        ):
            home = await MobileControlService.get_home(db, urgent_limit=999, tenant_id=None)
        assert home.urgent_limit == 25

    asyncio.run(_run())


def test_get_home_skips_notifications_without_tenant():
    async def _run():
        db = AsyncMock()
        with (
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._collect_items",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._build_summary",
                return_value=OperatorWorkspaceSummary(),
            ),
            patch(
                "app.services.mobile_control_service.NotificationService.get_unread_count",
                new=AsyncMock(),
            ) as unread,
            patch(
                "app.services.mobile_control_service.SystemHealthService.health",
                new=AsyncMock(return_value={"status": "ok", "database": "ok", "uptime": 1}),
            ),
        ):
            home = await MobileControlService.get_home(db, tenant_id=None)
        assert home.unread_notifications == 0
        unread.assert_not_awaited()

    asyncio.run(_run())


def test_get_system_reuses_sanitized_projection():
    async def _run():
        db = AsyncMock()
        with (
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._collect_items",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "app.services.mobile_control_service.OperatorWorkspaceService._build_summary",
                return_value=OperatorWorkspaceSummary(integration_issues=0),
            ),
            patch(
                "app.services.mobile_control_service.SystemHealthService.health",
                new=AsyncMock(return_value={"status": "ok", "database": "ok", "uptime": 2}),
            ),
        ):
            resp = await MobileControlService.get_system(db)
        assert resp.system_status.backup.status == "unavailable"
        assert resp.capabilities.backup_status_live is False
        blob = resp.model_dump_json().lower()
        assert "/var/lib" not in blob
        assert "ssh" not in blob
        assert "cloudflare" not in blob

    asyncio.run(_run())


def test_default_urgent_limit_is_compact():
    assert DEFAULT_URGENT_LIMIT == 10
    assert DEFAULT_URGENT_LIMIT <= 25
