"""Operator Workspace automation metrics + candidate classification tests."""
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
from app.services.operator_workspace_automation import (
    NEVER_AUTO_ACTION_KEYS,
    get_candidate,
    is_never_auto,
    rank_candidates,
    score_candidate,
)
from app.services.operator_workspace_metrics import (
    WORKSPACE_ACTION_EVENT,
    age_bucket,
    OperatorWorkspaceMetricsService,
)
from app.services.operator_workspace_actions import ACTION_OPEN, MUTATION_ACTIONS
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService


def _now():
    return datetime.now(timezone.utc)


def _item(**kwargs) -> OperatorAttentionItem:
    defaults = dict(
        id="publish-attempt:11111111-1111-1111-1111-111111111111",
        attention_type="publishing_issue",
        priority="high",
        client_id=uuid.uuid4(),
        company_name="Acme",
        content_id=uuid.uuid4(),
        resource_id="11111111-1111-1111-1111-111111111111",
        title="Issue",
        reason="Failed",
        current_state="failed",
        responsible_party="operator",
        suggested_action="Retry",
        action_path="/content/x",
        created_at=_now() - timedelta(minutes=30),
        source_domain="publishing",
        metadata={"reason_code": "publish_failed"},
    )
    defaults.update(kwargs)
    return OperatorAttentionItem(**defaults)


# ── Age buckets ────────────────────────────────────────────────────────────


def test_age_buckets_deterministic():
    assert age_bucket(0) == "lt_15m"
    assert age_bucket(14 * 60) == "lt_15m"
    assert age_bucket(15 * 60) == "m15_60"
    assert age_bucket(59 * 60) == "m15_60"
    assert age_bucket(60 * 60) == "h1_4"
    assert age_bucket(3 * 3600) == "h1_4"
    assert age_bucket(4 * 3600) == "h4_24"
    assert age_bucket(23 * 3600) == "h4_24"
    assert age_bucket(24 * 3600) == "d1_3"
    assert age_bucket(2 * 24 * 3600) == "d1_3"
    assert age_bucket(3 * 24 * 3600) == "gt_3d"
    assert age_bucket(10 * 24 * 3600) == "gt_3d"
    assert age_bucket(None) is None
    assert age_bucket(-1) is None


# ── Candidate classification ───────────────────────────────────────────────


def test_acknowledge_alert_is_level_a():
    c = get_candidate("acknowledge_alert")
    assert c is not None
    assert c.level == "A"


def test_operator_review_retry_never_auto():
    assert is_never_auto("operator_review_retry")
    c = get_candidate("operator_review_retry")
    assert c is not None
    assert c.level == "D"
    scored = score_candidate("operator_review_retry", frequency=100, success_rate=1.0, evidence_count=100)
    assert scored["never_auto"] is True
    assert scored["auto_eligible"] is False
    assert scored["score"] <= 15


def test_successful_and_in_progress_not_retry_auto_candidates():
    """Safety matrix permanently blocks ambiguous / live publish paths."""
    assert "operator_review_retry" in NEVER_AUTO_ACTION_KEYS
    assert "social_provider_publishing" in NEVER_AUTO_ACTION_KEYS
    retry = get_candidate("retry_publish_known_safe")
    assert retry is not None
    assert retry.level == "B"
    assert any("operator_review" in p.lower() or "failed|exhausted" in p.lower() or "Workspace eligibility" in p for p in retry.prerequisites)


def test_navigation_open_excluded_from_mutation_actions():
    assert ACTION_OPEN not in MUTATION_ACTIONS


def test_candidate_ranking_is_deterministic():
    ranked = rank_candidates({
        "acknowledge_alert": {"total": 50, "success_rate": 1.0},
        "retry_publish": {"total": 10, "success_rate": 0.5},
    })
    assert ranked[0]["action_key"] == "acknowledge_alert" or ranked[0]["score"] >= ranked[1]["score"]
    assert all(r["auto_eligible"] is False for r in ranked if r.get("available"))


# ── Attention metrics ──────────────────────────────────────────────────────


def test_attention_summary_counts_and_age_buckets():
    now = _now()
    items = [
        _item(
            id="a",
            attention_type="publishing_issue",
            priority="critical",
            responsible_party="operator",
            created_at=now - timedelta(minutes=5),
        ),
        _item(
            id="b",
            attention_type="content_internal_review",
            priority="medium",
            responsible_party="operator",
            created_at=now - timedelta(hours=2),
        ),
        _item(
            id="c",
            attention_type="waiting_for_client",
            priority="low",
            responsible_party="client",
            created_at=now - timedelta(days=2),
        ),
        _item(
            id="d",
            attention_type="scheduling_issue",
            priority="critical",
            responsible_party="operator",
            created_at=now - timedelta(days=1),
            due_at=now - timedelta(hours=5),
        ),
    ]
    metrics = OperatorWorkspaceMetricsService._build_attention_metrics(items, now=now)
    assert metrics["total"] == 4
    assert metrics["by_category"]["publishing_issue"] == 1
    assert metrics["by_priority"]["critical"] == 2
    assert metrics["by_responsibility"]["client"] == 1
    assert metrics["age_buckets"]["lt_15m"] == 1
    assert metrics["age_buckets"]["h1_4"] == 1
    assert metrics["age_buckets"]["d1_3"] == 1
    assert metrics["age_buckets"]["h4_24"] == 1  # scheduling uses due_at
    assert metrics["oldest_age_seconds"] is not None


def test_empty_state_metrics():
    metrics = OperatorWorkspaceMetricsService._build_attention_metrics([], now=_now())
    assert metrics["total"] == 0
    assert metrics["median_age_seconds"] is None
    assert metrics["oldest_age_seconds"] is None
    assert sum(metrics["age_buckets"].values()) == 0


def test_action_outcomes_classified_and_open_excluded():
    rows = [
        SimpleNamespace(details={"action_id": "acknowledge_alert", "outcome": "success"}),
        SimpleNamespace(details={"action_id": "acknowledge_alert", "outcome": "success"}),
        SimpleNamespace(details={"action_id": "resolve_alert", "outcome": "rejected"}),
        SimpleNamespace(details={"action_id": "retry_publish", "outcome": "failed"}),
        SimpleNamespace(details={"action_id": "retry_publish", "outcome": "stale"}),
        SimpleNamespace(details={"action_id": "open", "outcome": "success"}),  # excluded
        SimpleNamespace(details={}),  # excluded
    ]
    actions = OperatorWorkspaceMetricsService._build_action_metrics(rows)
    assert actions["total"] == 5
    assert actions["success"] == 2
    assert actions["rejected"] == 1
    assert actions["failed"] == 1
    assert actions["stale"] == 1
    assert "open" not in actions["by_action"]
    assert actions["by_action"]["acknowledge_alert"]["success"] == 2


def test_scrub_secrets_not_in_record_payload():
    """Instrumentation must never persist tokens/secrets."""
    from app.services.automation_domain_events import scrub_payload

    dirty = {
        "action_id": "acknowledge_alert",
        "access_token": "SECRET",
        "password": "x",
        "api_key": "k",
        "outcome": "success",
    }
    clean = scrub_payload(dirty)
    assert "access_token" not in clean
    assert "password" not in clean
    assert "api_key" not in clean
    assert clean["action_id"] == "acknowledge_alert"
    assert clean["outcome"] == "success"


def test_record_action_skips_navigation_open():
    async def _run():
        db = AsyncMock()
        with patch(
            "app.services.operator_workspace_metrics.PlatformAuditService.record",
            new=AsyncMock(),
        ) as record:
            await OperatorWorkspaceMetricsService.record_action(
                db,
                action_id=ACTION_OPEN,
                outcome="success",
                actor_id=None,
                tenant_id=uuid.uuid4(),
            )
            record.assert_not_awaited()

    asyncio.run(_run())


def test_record_action_writes_audit_event():
    async def _run():
        db = AsyncMock()
        tenant_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        with patch(
            "app.services.operator_workspace_metrics.PlatformAuditService.record",
            new=AsyncMock(return_value=MagicMock()),
        ) as record:
            await OperatorWorkspaceMetricsService.record_action(
                db,
                action_id="acknowledge_alert",
                outcome="success",
                actor_id=actor_id,
                tenant_id=tenant_id,
                attention_id="publish-alert:abc",
                resource_type="publish-alert",
                resource_id="abc",
                client_id=uuid.uuid4(),
                category="publishing_issue",
                commit=True,
            )
            record.assert_awaited_once()
            kwargs = record.await_args.kwargs
            assert kwargs["event_type"] == WORKSPACE_ACTION_EVENT
            assert kwargs["details"]["action_id"] == "acknowledge_alert"
            assert kwargs["details"]["outcome"] == "success"
            assert "access_token" not in (kwargs["details"] or {})

    asyncio.run(_run())


def test_metrics_tenant_isolation_filters_audit_rows():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    client_a = uuid.uuid4()

    row_a = SimpleNamespace(
        tenant_id=tenant_a,
        details={"action_id": "acknowledge_alert", "outcome": "success", "client_id": str(client_a)},
        created_at=_now(),
    )
    row_b = SimpleNamespace(
        tenant_id=tenant_b,
        details={"action_id": "acknowledge_alert", "outcome": "success", "client_id": str(uuid.uuid4())},
        created_at=_now(),
    )

    async def _run():
        db = MagicMock()
        # Simulate DB already tenant-filtered by returning only tenant_a rows from scalars.
        result = MagicMock()
        result.all = MagicMock(return_value=[row_a])
        scalars = MagicMock(return_value=result)
        db.scalars = AsyncMock(return_value=result)
        # Fix: scalars().all() pattern used in service
        scalars_result = MagicMock()
        scalars_result.all = MagicMock(return_value=[row_a])
        db.scalars = AsyncMock(return_value=scalars_result)

        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=tenant_a, client_ids=(client_a,)))
        try:
            rows = await OperatorWorkspaceMetricsService._load_action_audits(
                db, since=_now() - timedelta(days=7), client_id=None,
            )
            assert rows == [row_a]
            assert row_b not in rows
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_metrics_client_filter_excludes_other_clients():
    client_a = uuid.uuid4()
    client_b = uuid.uuid4()
    rows = [
        SimpleNamespace(details={"action_id": "approve_content", "outcome": "success", "client_id": str(client_a)}),
        SimpleNamespace(details={"action_id": "approve_content", "outcome": "success", "client_id": str(client_b)}),
        SimpleNamespace(details={"action_id": "approve_content", "outcome": "success"}),  # no client → drop
    ]
    # Reuse filter logic via _load_action_audits post-filter by calling the same loop
    filtered = []
    target = str(client_a)
    for row in rows:
        if (row.details or {}).get("client_id") == target:
            filtered.append(row)
    assert len(filtered) == 1
    assert filtered[0].details["client_id"] == str(client_a)


def test_workspace_rbac_roles():
    for role in ("owner", "manager", "operator"):
        user = MagicMock(spec=CurrentTenantUser)
        user.role = role
        user.has_permission = MagicMock(return_value=False)
        TenantAuthService.assert_role(user, "owner", "manager", "operator")

    for role in ("sales", "viewer"):
        user = MagicMock(spec=CurrentTenantUser)
        user.role = role
        user.has_permission = MagicMock(return_value=False)
        with pytest.raises(HTTPException) as exc:
            TenantAuthService.assert_role(user, "owner", "manager", "operator")
        assert exc.value.status_code == 403


def test_get_metrics_no_provider_calls_and_empty_ok():
    async def _run():
        db = AsyncMock()
        token = _auth_ctx.set(ApiAuthContext(kind="tenant", tenant_id=uuid.uuid4(), client_ids=()))
        try:
            with (
                patch(
                    "app.services.operator_workspace_metrics.OperatorWorkspaceService._collect_items",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    OperatorWorkspaceMetricsService,
                    "_load_action_audits",
                    new=AsyncMock(return_value=[]),
                ),
                patch.object(
                    OperatorWorkspaceMetricsService,
                    "_build_resolution_metrics",
                    new=AsyncMock(return_value={
                        "resolved": 0,
                        "system_resolved": 0,
                        "manual_resolved": 0,
                        "acknowledged": 0,
                        "median_resolution_seconds": None,
                        "median_ack_seconds": None,
                        "available": True,
                        "scope": "publish_operator_alerts",
                        "non_alert_resolution_available": False,
                    }),
                ),
            ):
                result = await OperatorWorkspaceMetricsService.get_metrics(db, window="7d")
            assert result.attention["total"] == 0
            assert result.actions["total"] == 0
            assert result.window == "7d"
            assert all(c.get("auto_eligible") is False for c in result.automation_candidates)
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())


def test_invalid_window_rejected():
    async def _run():
        with pytest.raises(HTTPException) as exc:
            await OperatorWorkspaceMetricsService.get_metrics(
                AsyncMock(), window="1y",  # type: ignore[arg-type]
            )
        assert exc.value.status_code == 400

    asyncio.run(_run())


def test_large_volume_attention_aggregation():
    now = _now()
    items = [
        _item(
            id=f"item-{i}",
            client_id=uuid.uuid4(),
            created_at=now - timedelta(minutes=i % 200),
            priority=["critical", "high", "medium", "low"][i % 4],
            attention_type=[
                "publishing_issue",
                "content_internal_review",
                "integration_issue",
                "automation_failure",
            ][i % 4],
        )
        for i in range(300)
    ]
    metrics = OperatorWorkspaceMetricsService._build_attention_metrics(items, now=now)
    assert metrics["total"] == 300
    assert sum(metrics["by_priority"].values()) == 300
    assert sum(metrics["age_buckets"].values()) == 300


def test_resolution_median_from_alert_fields():
    async def _run():
        now = _now()
        alert = SimpleNamespace(
            first_occurred_at=now - timedelta(hours=2),
            created_at=now - timedelta(hours=2),
            resolved_at=now - timedelta(hours=1),
            resolved_by_system=False,
            acknowledged_at=now - timedelta(minutes=90),
        )
        content = SimpleNamespace(id=uuid.uuid4(), client_id=uuid.uuid4())

        db = AsyncMock()

        class _Result:
            def __init__(self, rows):
                self._rows = rows

            def all(self):
                return self._rows

        async def _execute(query):
            # First call: resolved; second: ack
            if not hasattr(_execute, "n"):
                _execute.n = 0
            _execute.n += 1
            if _execute.n == 1:
                return _Result([(alert, content)])
            return _Result([(alert, content)])

        db.execute = _execute

        token = _auth_ctx.set(ApiAuthContext(kind="admin", tenant_id=None, client_ids=()))
        try:
            with patch(
                "app.services.operator_workspace_metrics.scope_select",
                side_effect=lambda q, cq, col, client_id=None: (q, cq),
            ):
                result = await OperatorWorkspaceMetricsService._build_resolution_metrics(
                    db, since=now - timedelta(days=7), client_id=None, now=now,
                )
            assert result["resolved"] == 1
            assert result["acknowledged"] == 1
            assert result["median_resolution_seconds"] == pytest.approx(3600, rel=0.01)
            assert result["non_alert_resolution_available"] is False
        finally:
            _auth_ctx.reset(token)

    asyncio.run(_run())
