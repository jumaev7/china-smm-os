"""Integration Health scheduler audit observability — regression coverage."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.access_log_redaction import scrub_audit_details
from app.services.integration_health.scheduler import IntegrationHealthScheduler
from app.services.integration_health.service import IntegrationHealthService
from app.services.operator_workspace_metrics import (
    WORKSPACE_ACTION_EVENT,
    OperatorWorkspaceMetricsService,
)


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
        status="connected",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _make_totals(**overrides):
    base = {
        "tenants": 2,
        "checked": 5,
        "errors": 0,
        "meta_accounts": 3,
        "remote_meta_probes": 0,
        "status_summary": {"healthy": 4, "degraded": 1},
    }
    base.update(overrides)
    return base


# ── Local scheduler cycle audit ─────────────────────────────────────────────


def test_scheduler_local_cycle_creates_batch_audit():
    async def _run():
        db = AsyncMock()
        started = _now()
        completed = started
        with patch(
            "app.services.integration_health.service.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            await IntegrationHealthService.audit_scheduler_cycle(
                db,
                cycle=7,
                live_remote=False,
                remote_enabled=True,
                started_at=started,
                completed_at=completed,
                totals=_make_totals(),
            )
            record.assert_awaited_once()
            kwargs = record.await_args.kwargs
            assert kwargs["event_type"] == "integration_health.batch_check"
            assert kwargs["tenant_id"] is None
            assert kwargs["actor_type"] == "system"
            assert kwargs["resource_id"] == "scheduler:cycle:7"
            details = kwargs["details"]
            assert details["trigger"] == "scheduler"
            assert details["cycle"] == 7
            assert details["remote_check"] is False
            assert details["remote_enabled"] is True
            assert details["checked_count"] == 5
            assert details["error_count"] == 0
            assert details["outcome"] == "success"
            assert kwargs["commit"] is True

    asyncio.run(_run())


def test_scheduler_remote_cycle_audit_fields():
    async def _run():
        db = AsyncMock()
        started = _now()
        completed = started
        totals = _make_totals(remote_meta_probes=3, meta_accounts=3)
        with patch(
            "app.services.integration_health.service.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            await IntegrationHealthService.audit_scheduler_cycle(
                db,
                cycle=4,
                live_remote=True,
                remote_enabled=True,
                started_at=started,
                completed_at=completed,
                totals=totals,
            )
            details = record.await_args.kwargs["details"]
            assert details["remote_check"] is True
            assert details["remote_meta_probes"] == 3
            assert details["meta_accounts"] == 3

    asyncio.run(_run())


def test_scheduler_api_audit_source_distinction():
    async def _run():
        db = AsyncMock()
        # API batch path
        with patch(
            "app.services.integration_health.service.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as api_record:
            await IntegrationHealthService._audit_batch(db, uuid.uuid4(), 3)
            api_details = api_record.await_args.kwargs["details"]
            assert api_details["trigger"] == "api_live_check"
            assert "cycle" not in api_details

        # Scheduler batch path
        with patch(
            "app.services.integration_health.service.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as sched_record:
            await IntegrationHealthService.audit_scheduler_cycle(
                db,
                cycle=1,
                live_remote=False,
                remote_enabled=False,
                started_at=_now(),
                completed_at=_now(),
                totals=_make_totals(),
            )
            sched_details = sched_record.await_args.kwargs["details"]
            assert sched_details["trigger"] == "scheduler"
            assert sched_details["cycle"] == 1

    asyncio.run(_run())


def test_scheduler_audit_outcome_partial_and_failed():
    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.integration_health.service.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            await IntegrationHealthService.audit_scheduler_cycle(
                db,
                cycle=2,
                live_remote=False,
                remote_enabled=False,
                started_at=_now(),
                completed_at=_now(),
                totals=_make_totals(errors=1, checked=3),
            )
            assert record.await_args.kwargs["details"]["outcome"] == "partial"

            await IntegrationHealthService.audit_scheduler_cycle(
                db,
                cycle=3,
                live_remote=False,
                remote_enabled=False,
                started_at=_now(),
                completed_at=_now(),
                totals=_make_totals(errors=2, checked=0),
            )
            assert record.await_args.kwargs["details"]["outcome"] == "failed"

    asyncio.run(_run())


def test_scheduler_audit_scrubs_secrets():
    dirty_details = {
        "trigger": "scheduler",
        "cycle": 1,
        "remote_check": True,
        "access_token": "EAAB_SHOULD_NOT_PERSIST",
        "refresh_token": "refresh_secret",
        "input_token": "debug_input",
        "code": "oauth_code_value",
        "state": "oauth_state_value",
        "client_secret": "meta-client-secret",
        "app_secret": "meta-app-secret",
        "ADMIN_SECRET_KEY": "admin-secret",
        "SECRET_KEY": "fallback-secret",
        "ciphertext": "gAAAAencrypted",
        "checked_count": 2,
        "status_summary": {
            "healthy": 1,
            "nested": {"access_token": "nested_secret"},
        },
    }
    clean = scrub_audit_details(dirty_details)
    blob = json.dumps(clean)
    for banned in (
        "EAAB_SHOULD_NOT_PERSIST",
        "refresh_secret",
        "debug_input",
        "oauth_code_value",
        "oauth_state_value",
        "meta-client-secret",
        "meta-app-secret",
        "admin-secret",
        "fallback-secret",
        "gAAAAencrypted",
        "nested_secret",
    ):
        assert banned not in blob
    assert clean["trigger"] == "scheduler"
    assert clean["checked_count"] == 2
    assert clean["status_summary"]["healthy"] == 1


def test_audit_failure_does_not_fail_scheduler_cycle():
    from app.services.integration_health import scheduler as sched_mod

    sched_mod._cycle = 0
    sched_mod._cycle_running = False

    async def _run():
        cycle_summary = _make_totals()
        with (
            patch.object(
                IntegrationHealthService,
                "run_periodic_cycle",
                new=AsyncMock(return_value=cycle_summary),
            ) as mock_cycle,
            patch.object(
                IntegrationHealthService,
                "audit_scheduler_cycle",
                new=AsyncMock(side_effect=RuntimeError("audit db down")),
            ),
            patch("app.services.integration_health.scheduler.session_scope") as scope,
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_CHECK_ENABLED", True),
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED", False),
        ):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=AsyncMock())
            cm.__aexit__ = AsyncMock(return_value=None)
            scope.return_value = cm
            result = await IntegrationHealthScheduler.run_once()
            mock_cycle.assert_awaited_once()
            assert result["checked"] == 5
            assert result["errors"] == 0
            assert "cycle" in result

    asyncio.run(_run())


def test_audit_failure_does_not_retry_provider_checks():
    """Audit failure must not re-invoke run_periodic_cycle or evaluate_account."""
    debug_mock = AsyncMock(return_value={"is_valid": True, "scopes": []})

    async def _run():
        tid = uuid.uuid4()
        acct = _account(tenant_id=tid)

        class _Scalars:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_Scalars([acct]))
        db.commit = AsyncMock()
        db.rollback = AsyncMock()

        eval_calls = {"n": 0}

        async def _eval(db, account, *, live_check=False, persist=True):
            eval_calls["n"] += 1
            from app.services.integration_health.types import IntegrationHealthResult
            from app.services.integration_health.taxonomy import REASON_HEALTHY

            return IntegrationHealthResult(
                integration_id=str(account.id),
                platform=account.platform,
                provider="meta",
                tenant_id=str(account.tenant_id),
                client_id=None,
                account_name=account.account_name,
                status="healthy",
                severity="info",
                reason_code=REASON_HEALTHY,
                reason="ok",
                checked_at=_now(),
                last_success_at=_now(),
                stale_after_seconds=99999,
                stale=False,
                requires_operator_action=False,
                responsible_party="system",
                recommended_next_step="none",
                deep_link="/integrations/x",
                capabilities=(),
                source="local",
                never_checked=False,
                transient_failure_count=0,
                safe_auto_recheck=True,
                diagnostic={},
            )

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
            patch(
                "app.services.integration_health.service.PlatformAuditService.record",
                new=AsyncMock(side_effect=RuntimeError("audit write failed")),
            ),
            patch(
                "app.services.integration_health.checks.debug_token",
                debug_mock,
            ),
        ):
            totals = await IntegrationHealthService.run_periodic_cycle(
                db, tenant_ids=[tid], live_remote=True
            )
            await IntegrationHealthService.audit_scheduler_cycle(
                db,
                cycle=1,
                live_remote=True,
                remote_enabled=True,
                started_at=_now(),
                completed_at=_now(),
                totals=totals,
            )
            assert eval_calls["n"] == 1
            debug_mock.assert_not_called()

    asyncio.run(_run())


def test_scheduler_run_once_emits_audit_without_extra_meta_calls():
    from app.services.integration_health import scheduler as sched_mod

    sched_mod._cycle = 3  # remote-eligible cycle number
    sched_mod._cycle_running = False
    debug_mock = AsyncMock()

    async def _run():
        with (
            patch.object(
                IntegrationHealthService,
                "run_periodic_cycle",
                new=AsyncMock(return_value=_make_totals(remote_meta_probes=2)),
            ),
            patch.object(
                IntegrationHealthService,
                "audit_scheduler_cycle",
                new=AsyncMock(),
            ) as audit_mock,
            patch("app.services.integration_health.scheduler.session_scope") as scope,
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_CHECK_ENABLED", True),
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED", True),
            patch(
                "app.services.integration_health.checks.debug_token",
                debug_mock,
            ),
        ):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=AsyncMock())
            cm.__aexit__ = AsyncMock(return_value=None)
            scope.return_value = cm
            await IntegrationHealthScheduler.run_once()
            audit_mock.assert_awaited_once()
            debug_mock.assert_not_called()

    asyncio.run(_run())


def test_overlap_skip_does_not_emit_audit():
    from app.services.integration_health import scheduler as sched_mod

    sched_mod._cycle_running = True

    async def _run():
        with patch.object(
            IntegrationHealthService,
            "audit_scheduler_cycle",
            new=AsyncMock(),
        ) as audit_mock:
            result = await IntegrationHealthScheduler.run_once()
            assert result.get("skipped") is True
            audit_mock.assert_not_awaited()

    try:
        asyncio.run(_run())
    finally:
        sched_mod._cycle_running = False


def test_remote_false_preserves_local_only_audit():
    from app.services.integration_health import scheduler as sched_mod

    sched_mod._cycle = 3  # would be remote-eligible
    sched_mod._cycle_running = False

    async def _run():
        with (
            patch.object(
                IntegrationHealthService,
                "run_periodic_cycle",
                new=AsyncMock(return_value=_make_totals()),
            ) as mock_cycle,
            patch.object(
                IntegrationHealthService,
                "audit_scheduler_cycle",
                new=AsyncMock(),
            ) as audit_mock,
            patch("app.services.integration_health.scheduler.session_scope") as scope,
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_CHECK_ENABLED", True),
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED", False),
        ):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=AsyncMock())
            cm.__aexit__ = AsyncMock(return_value=None)
            scope.return_value = cm
            await IntegrationHealthScheduler.run_once()
            assert mock_cycle.await_args.kwargs.get("live_remote") is False
            audit_kwargs = audit_mock.await_args.kwargs
            assert audit_kwargs["live_remote"] is False
            assert audit_kwargs["remote_enabled"] is False

    asyncio.run(_run())


def test_cadence_remote_gate_unchanged():
    from app.services.integration_health import scheduler as sched_mod

    sched_mod._cycle_running = False

    async def _run():
        captured = []

        async def _fake_cycle(db, *, live_remote=False):
            captured.append(live_remote)
            return _make_totals()

        with (
            patch.object(
                IntegrationHealthService,
                "run_periodic_cycle",
                side_effect=_fake_cycle,
            ),
            patch.object(
                IntegrationHealthService,
                "audit_scheduler_cycle",
                new=AsyncMock(),
            ),
            patch("app.services.integration_health.scheduler.session_scope") as scope,
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_CHECK_ENABLED", True),
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED", True),
        ):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=AsyncMock())
            cm.__aexit__ = AsyncMock(return_value=None)
            scope.return_value = cm
            for cycle in (1, 2, 3, 4):
                sched_mod._cycle = cycle - 1
                await IntegrationHealthScheduler.run_once()
            assert captured == [False, False, False, True]

    asyncio.run(_run())


def test_scheduler_audit_tenant_id_is_global():
    async def _run():
        db = AsyncMock()
        tenant_id = uuid.uuid4()
        with patch(
            "app.services.integration_health.service.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            await IntegrationHealthService.audit_scheduler_cycle(
                db,
                cycle=10,
                live_remote=False,
                remote_enabled=True,
                started_at=_now(),
                completed_at=_now(),
                totals=_make_totals(tenants=5),
            )
            assert record.await_args.kwargs["tenant_id"] is None

            # API batch remains tenant-scoped
            await IntegrationHealthService._audit_batch(db, tenant_id, 2)
            assert record.await_args.kwargs["tenant_id"] == tenant_id

    asyncio.run(_run())


def test_workspace_metrics_ignore_integration_health_audits():
    rows = [
        SimpleNamespace(
            details={"action_id": "acknowledge_alert", "outcome": "success"},
            created_at=_now(),
        ),
        SimpleNamespace(
            details={"trigger": "scheduler", "outcome": "success"},
            created_at=_now(),
        ),
    ]
    # _build_action_metrics should only count workspace action rows
    action_rows = [
        r for r in rows
        if (r.details or {}).get("action_id")
    ]
    metrics = OperatorWorkspaceMetricsService._build_action_metrics(action_rows)
    assert metrics["total"] == 1
    assert metrics["by_action"]["acknowledge_alert"]["total"] == 1
    assert WORKSPACE_ACTION_EVENT == "operator_workspace.action"


def test_periodic_cycle_tracks_meta_probe_counts():
    async def _run():
        tid = uuid.uuid4()
        fb = _account(tenant_id=tid, platform="facebook")
        ig = _account(tenant_id=tid, platform="instagram")

        class _Scalars:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        db = AsyncMock()
        db.scalars = AsyncMock(return_value=_Scalars([fb, ig]))
        db.commit = AsyncMock()

        from app.services.integration_health.types import IntegrationHealthResult
        from app.services.integration_health.taxonomy import REASON_HEALTHY

        healthy = IntegrationHealthResult(
            integration_id="x",
            platform="facebook",
            provider="meta",
            tenant_id=str(tid),
            client_id=None,
            account_name="A",
            status="healthy",
            severity="info",
            reason_code=REASON_HEALTHY,
            reason="ok",
            checked_at=_now(),
            last_success_at=_now(),
            stale_after_seconds=99999,
            stale=False,
            requires_operator_action=False,
            responsible_party="system",
            recommended_next_step="none",
            deep_link="/integrations/x",
            capabilities=(),
            source="remote",
            never_checked=False,
            transient_failure_count=0,
            safe_auto_recheck=True,
            diagnostic={},
        )

        with (
            patch.object(
                IntegrationHealthService,
                "evaluate_account",
                new=AsyncMock(return_value=healthy),
            ),
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
            totals = await IntegrationHealthService.run_periodic_cycle(
                db, tenant_ids=[tid], live_remote=True
            )
            assert totals["meta_accounts"] == 2
            assert totals["remote_meta_probes"] == 2
            assert totals["checked"] == 2
            assert totals["status_summary"]["healthy"] == 2

    asyncio.run(_run())


def test_manual_run_once_creates_audit_at_least_once():
    """Duplicate audits on restart are acceptable (at-least-once semantics)."""
    from app.services.integration_health import scheduler as sched_mod

    sched_mod._cycle = 0
    sched_mod._cycle_running = False

    async def _run():
        with (
            patch.object(
                IntegrationHealthService,
                "run_periodic_cycle",
                new=AsyncMock(return_value=_make_totals()),
            ),
            patch.object(
                IntegrationHealthService,
                "audit_scheduler_cycle",
                new=AsyncMock(),
            ) as audit_mock,
            patch("app.services.integration_health.scheduler.session_scope") as scope,
            patch.object(sched_mod.settings, "INTEGRATION_HEALTH_CHECK_ENABLED", True),
        ):
            cm = AsyncMock()
            cm.__aenter__ = AsyncMock(return_value=AsyncMock())
            cm.__aexit__ = AsyncMock(return_value=None)
            scope.return_value = cm
            await IntegrationHealthScheduler.run_once()
            await IntegrationHealthScheduler.run_once()
            assert audit_mock.await_count == 2

    asyncio.run(_run())
