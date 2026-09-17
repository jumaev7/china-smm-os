"""Phase E1 — stranded post-barrier detection (read-only).

Covers predicate, quiet-period classification, audit semantics, Auto-Ack
exclusion, import/reachability gates, and command-mutation negative proofs.
No provider I/O. No execution. No E2 terminalization.
"""
from __future__ import annotations

import ast
import inspect
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.config import settings
from app.services.operator_auto_ack.constants import (
    EXCLUDED_CONTEXT_MARKERS,
    PHASE_E_STRANDED_CONTEXT_MARKER,
    PHASE_E_STRANDED_FAILURE_CODES,
)
from app.services.operator_auto_ack.eligibility import evaluate_auto_ack_candidate
from app.services.publish_resilience import STATUS_RETRYING
from app.services.publish_retry_command_stranded_detector import (
    FORBIDDEN_CLASSIFICATIONS,
    PHASE_E_CONTEXT_MARKER,
    PROVIDER_CALL_STARTED_EVENT,
    PublishRetryCommandStrandedDetector,
    StrandedCommandObservation,
    _E1_FORBIDDEN_IMPORT_MODULES,
    classify_by_quiet_period,
    compute_quiet_period_model,
    compute_quiet_period_seconds,
    interpret_provider_call_started_audit,
    is_stranded_post_barrier_row,
    recommended_action_for,
    stranded_dedupe_key,
)

BACKEND = Path(__file__).resolve().parents[1]
DETECTOR_PATH = (
    BACKEND / "app" / "services" / "publish_retry_command_stranded_detector.py"
)
CANONICAL_SERVICE_FILES = [
    BACKEND / "app" / "services" / "publish_retry_command_claim_service.py",
    BACKEND / "app" / "services" / "publish_retry_command_preparation_service.py",
    BACKEND / "app" / "services" / "publish_retry_command_barrier_service.py",
    BACKEND / "app" / "services" / "publish_retry_command_executor.py",
    BACKEND / "app" / "services" / "publish_retry_command_finalization_service.py",
    BACKEND / "app" / "workers" / "publish_retry_command_worker.py",
]


def _now():
    return datetime(2026, 9, 13, 12, 0, 0, tzinfo=timezone.utc)


def _cmd(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        content_id=uuid.uuid4(),
        publishing_account_id=uuid.uuid4(),
        original_attempt_id=uuid.uuid4(),
        resulting_attempt_id=uuid.uuid4(),
        platform="telegram",
        status="provider_write_started",
        provider_write_started_at=_now() - timedelta(seconds=30),
        lease_owner="worker-a:1:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        lease_expires_at=None,
        claimed_at=_now() - timedelta(seconds=60),
        finished_at=None,
        provider_outcome=None,
        correlation_id="corr-e1-test",
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ── Quiet period / classification ───────────────────────────────────────────


def test_quiet_period_formula_and_defaults():
    model = compute_quiet_period_model()
    assert model.lease_seconds == settings.PUBLISH_RETRY_COMMAND_LEASE_SECONDS
    assert model.drain_seconds == int(settings.PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS)
    assert model.provider_slack_seconds == settings.PUBLISH_RETRY_STRANDED_PROVIDER_SLACK_SECONDS
    assert model.safety_buffer_seconds == settings.PUBLISH_RETRY_STRANDED_SAFETY_BUFFER_SECONDS
    expected = (
        max(model.lease_seconds, model.drain_seconds)
        + model.provider_slack_seconds
        + model.safety_buffer_seconds
    )
    assert model.quiet_period_seconds == expected
    assert compute_quiet_period_seconds() == expected
    assert "max(lease_seconds, drain_seconds)" in model.formula
    # Documented defaults: 180 + 300 + 120 = 600
    assert expected == 600


def test_recent_provider_write_started_still_in_progress():
    quiet = compute_quiet_period_seconds()
    classification, stance = classify_by_quiet_period(
        age_seconds=quiet - 1,
        quiet_period_seconds=quiet,
    )
    assert classification == "still_in_progress"
    assert stance is None
    assert recommended_action_for(classification) == "monitor_await_quiet_period"


def test_older_than_quiet_period_stranded_review_ambiguous():
    quiet = compute_quiet_period_seconds()
    classification, stance = classify_by_quiet_period(
        age_seconds=quiet,
        quiet_period_seconds=quiet,
    )
    assert classification == "stranded_review_candidate"
    assert stance == "provider_outcome_ambiguous"
    assert recommended_action_for(classification) == "operator_manual_review_no_replay"


def test_time_alone_never_produces_provider_not_called_proven():
    quiet = compute_quiet_period_seconds()
    for age in (0, quiet - 1, quiet, quiet * 10, quiet * 100):
        classification, stance = classify_by_quiet_period(
            age_seconds=age,
            quiet_period_seconds=quiet,
        )
        assert classification not in FORBIDDEN_CLASSIFICATIONS
        assert stance not in FORBIDDEN_CLASSIFICATIONS
        assert classification != "provider_not_called_proven"
        assert stance != "provider_not_called_proven"


# ── Predicate ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "status,ts,expected",
    [
        ("provider_write_started", _now(), True),
        ("claimed", None, False),
        ("claimed", _now(), False),
        ("pending", None, False),
        ("succeeded", _now(), False),
        ("failed", _now(), False),
        ("ambiguous", _now(), False),
        ("cancelled", _now(), False),
        ("superseded", _now(), False),
        ("provider_write_started", None, False),
    ],
)
def test_stranded_predicate_matrix(status, ts, expected):
    assert is_stranded_post_barrier_row(
        status=status,
        provider_write_started_at=ts,
    ) is expected


def test_classic_stale_attempt_in_progress_excluded_from_predicate():
    """PublishAttempt.in_progress is not a stranded retry command."""
    assert is_stranded_post_barrier_row(
        status="in_progress",
        provider_write_started_at=None,
    ) is False


# ── Audit evidence ──────────────────────────────────────────────────────────


def test_audit_present_is_intent_evidence_only():
    info = interpret_provider_call_started_audit(True)
    assert info["presence"] == "present"
    assert info["interpretation"] == "intent_evidence"
    assert info["authorizes_replay"] is False
    assert "provider_success" in info["not_proof_of"]
    assert "provider_failure" in info["not_proof_of"]
    assert "network_call_completed" in info["not_proof_of"]


def test_audit_absent_is_unknown_not_no_effect_proof():
    info = interpret_provider_call_started_audit(False)
    assert info["presence"] == "absent"
    assert info["interpretation"] == "unknown"
    assert info["authorizes_replay"] is False
    assert "provider_not_called_proven" in info["not_proof_of"]
    assert "zero_effect" in info["not_proof_of"]


def test_observe_payload_labels_lease_and_audit():
    quiet = 600
    cmd = _cmd(provider_write_started_at=_now() - timedelta(seconds=30))
    obs = PublishRetryCommandStrandedDetector._observe_command(
        cmd,
        now=_now(),
        quiet_period_seconds=quiet,
        attempt=SimpleNamespace(external_post_id="ext-1"),
        audit_present=True,
    )
    payload = obs.to_payload()
    assert payload["lease_owner"]["label"] == "historical_only"
    assert payload["lease_owner"]["not_current_liveness_proof"] is True
    assert payload["provider_call_started_audit"]["interpretation"] == "intent_evidence"
    assert payload["classification"] == "still_in_progress"
    assert payload["outcome_stance"] is None
    assert payload["external_post_id"] == "ext-1"
    assert payload["authorizes_provider_write"] is False
    assert payload["authorizes_replay"] is False
    assert "provider_not_called_proven" in payload["does_not_prove"]


def test_observe_past_quiet_period_ambiguous_stance():
    quiet = 600
    cmd = _cmd(provider_write_started_at=_now() - timedelta(seconds=quiet + 5))
    obs = PublishRetryCommandStrandedDetector._observe_command(
        cmd,
        now=_now(),
        quiet_period_seconds=quiet,
        attempt=None,
        audit_present=False,
    )
    payload = obs.to_payload()
    assert payload["classification"] == "stranded_review_candidate"
    assert payload["outcome_stance"] == "provider_outcome_ambiguous"
    assert payload["quiet_period_elapsed"] is True
    assert payload["provider_call_started_audit"]["interpretation"] == "unknown"
    assert payload["recommended_action"] == "operator_manual_review_no_replay"


# ── Auto-Ack exclusion ──────────────────────────────────────────────────────


def _alert(**kwargs):
    defaults = dict(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        content_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        attempt_id=uuid.uuid4(),
        state="open",
        alert_type="operator_review",
        severity="critical",
        platform="telegram",
        failure_code="stranded_post_barrier",
        attempt_status="provider_write_started",
        occurrence_count=1,
        latest_occurred_at=_now(),
        first_occurred_at=_now() - timedelta(hours=1),
        context={
            "phase_e": PHASE_E_STRANDED_CONTEXT_MARKER,
            "requires_operator_action": True,
            "safe_auto_recheck": False,
            "auto_ack_eligible": False,
        },
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
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_phase_e_stranded_alert_auto_ack_excluded_by_context():
    decision = evaluate_auto_ack_candidate(_alert(), attempt=_attempt())
    assert decision.eligible is False
    assert decision.reason_code == "phase_e_stranded_excluded"
    assert decision.shadow_action == "skip"


def test_phase_e_stranded_excluded_even_if_disguised_as_stale_warning():
    """Future-proof: context marker wins even if type/severity look allowlisted."""
    alert = _alert(
        alert_type="stale_in_progress",
        severity="warning",
        failure_code="stale_in_progress",
        context={"phase_e": PHASE_E_STRANDED_CONTEXT_MARKER},
    )
    decision = evaluate_auto_ack_candidate(alert, attempt=_attempt())
    assert decision.eligible is False
    assert decision.reason_code == "phase_e_stranded_excluded"


def test_phase_e_failure_code_excluded_when_on_allowlist_type():
    alert = _alert(
        alert_type="stale_in_progress",
        severity="warning",
        failure_code="stranded_post_barrier",
        context={},
    )
    decision = evaluate_auto_ack_candidate(alert, attempt=_attempt())
    assert decision.eligible is False
    assert decision.reason_code == "phase_e_stranded_excluded"


def test_phase_e_constants_future_proof():
    assert PHASE_E_STRANDED_CONTEXT_MARKER in EXCLUDED_CONTEXT_MARKERS
    assert "stranded_post_barrier" in PHASE_E_STRANDED_FAILURE_CODES


# ── Import / reachability / provider I/O gates ───────────────────────────────


def test_detector_source_has_no_forbidden_execution_imports():
    src = DETECTOR_PATH.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported.add(node.module)
    for forbidden in _E1_FORBIDDEN_IMPORT_MODULES:
        assert forbidden not in imported, f"E1 must not import {forbidden}"
    assert "httpx" not in imported
    assert "app.services.providers" not in imported
    for token in (
        "PublishRetryCommandClaimService",
        "PublishRetryCommandPreparationService",
        "PublishRetryCommandBarrierService",
        "PublishRetryCommandExecutor",
        "PublishRetryCommandFinalizationService",
        "PublishRetryCommandWorker",
    ):
        assert token not in src


def test_canonical_execution_services_do_not_import_stranded_detector():
    for path in CANONICAL_SERVICE_FILES:
        text = path.read_text(encoding="utf-8")
        assert "publish_retry_command_stranded_detector" not in text
        assert "PublishRetryCommandStrandedDetector" not in text
        assert "mark_ambiguous_stranded" not in text
        assert "PhaseE" not in text
        assert "phase_e_recovery" not in text


def test_detector_list_stranded_does_not_assign_command_fields():
    """Static: list_stranded body must not mutate command execution fields."""
    src = inspect.getsource(PublishRetryCommandStrandedDetector.list_stranded)
    for field in (
        "status =",
        "lease_owner =",
        "lease_expires_at =",
        "provider_write_started_at =",
        "provider_outcome =",
        "finished_at =",
        "resulting_attempt_id =",
        "original_attempt_id =",
    ):
        assert field not in src


def test_config_flags_default_disabled():
    assert (
        type(settings).model_fields[
            "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED"
        ].default
        is False
    )
    assert settings.PUBLISH_RETRY_STRANDED_LIST_API_ENABLED is False
    assert settings.PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED is False
    assert settings.PUBLISH_RETRY_STRANDED_SCANNER_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMANDS_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED is False
    assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND == "none"


def test_stranded_dedupe_key_stable():
    cid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    assert stranded_dedupe_key(cid) == "phase_e:stranded_retry:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


# ── Detector DB orchestration (mocked) ───────────────────────────────────────


def test_list_stranded_tenant_filter_and_no_command_mutation():
    import asyncio

    tenant_id = uuid.uuid4()
    other_tenant = uuid.uuid4()
    cmd = _cmd(
        tenant_id=tenant_id,
        provider_write_started_at=_now() - timedelta(seconds=10),
    )
    before = {
        "status": cmd.status,
        "lease_owner": cmd.lease_owner,
        "lease_expires_at": cmd.lease_expires_at,
        "provider_write_started_at": cmd.provider_write_started_at,
        "provider_outcome": cmd.provider_outcome,
        "finished_at": cmd.finished_at,
        "resulting_attempt_id": cmd.resulting_attempt_id,
        "original_attempt_id": cmd.original_attempt_id,
    }

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [cmd]
    empty_attempts = MagicMock()
    empty_attempts.scalars.return_value.all.return_value = []
    empty_audits = MagicMock()
    empty_audits.scalars.return_value.all.return_value = []

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[count_result, rows_result, empty_attempts, empty_audits],
    )

    async def _run():
        return await PublishRetryCommandStrandedDetector.list_stranded(
            db,
            tenant_id=tenant_id,
            page=1,
            page_size=20,
            now=_now(),
            create_alerts=False,
        )

    result = asyncio.run(_run())
    assert result["total"] == 1
    assert result["items"][0]["tenant_id"] == tenant_id
    assert result["items"][0]["tenant_id"] != other_tenant
    assert result["items"][0]["classification"] == "still_in_progress"
    assert result["alert_surfacing_enabled"] is False
    assert result["alerts_created"] == 0
    assert result["phase_e"] == PHASE_E_CONTEXT_MARKER

    for key, value in before.items():
        assert getattr(cmd, key) == value


def test_list_stranded_alert_surfacing_only_for_review_candidates():
    import asyncio

    tenant_id = uuid.uuid4()
    quiet = compute_quiet_period_seconds()
    cmd = _cmd(
        tenant_id=tenant_id,
        provider_write_started_at=_now() - timedelta(seconds=quiet + 10),
    )
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [cmd]
    empty_attempts = MagicMock()
    empty_attempts.scalars.return_value.all.return_value = []
    empty_audits = MagicMock()
    empty_audits.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[count_result, rows_result, empty_attempts, empty_audits],
    )

    async def _run():
        with patch.object(
            PublishRetryCommandStrandedDetector,
            "_surface_alert",
            AsyncMock(return_value=True),
        ) as surface:
            result = await PublishRetryCommandStrandedDetector.list_stranded(
                db,
                tenant_id=tenant_id,
                now=_now(),
                create_alerts=True,
            )
            surface.assert_awaited_once()
            return result

    result = asyncio.run(_run())
    assert result["items"][0]["classification"] == "stranded_review_candidate"
    assert result["alerts_created"] == 1


def test_alert_upsert_dedupes_on_stable_key():
    import asyncio

    from app.services.publish_operator_alert_service import PublishOperatorAlertService

    obs = StrandedCommandObservation(
        command_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        platform="telegram",
        publishing_account_id=uuid.uuid4(),
        content_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        original_attempt_id=uuid.uuid4(),
        resulting_attempt_id=uuid.uuid4(),
        status="provider_write_started",
        provider_write_started_at=_now() - timedelta(seconds=900),
        lease_owner_historical="hist",
        claimed_at=_now() - timedelta(seconds=1000),
        age_seconds=900,
        quiet_period_seconds=600,
        quiet_period_elapsed=True,
        last_known_local_step="barrier_crossed_provider_write_started",
        provider_call_started_audit=interpret_provider_call_started_audit(False),
        external_post_id=None,
        correlation_id="c1",
        classification="stranded_review_candidate",
        outcome_stance="provider_outcome_ambiguous",
        recommended_action="operator_manual_review_no_replay",
    )
    payload = obs.to_payload()
    alert = SimpleNamespace(id=uuid.uuid4(), occurrence_count=1)

    async def _run():
        with (
            patch.object(
                PublishOperatorAlertService,
                "_upsert",
                AsyncMock(side_effect=[(alert, True), (alert, False)]),
            ) as upsert,
            patch.object(
                PublishOperatorAlertService,
                "_emit_and_deliver",
                AsyncMock(),
            ),
        ):
            first = await PublishOperatorAlertService.upsert_stranded_post_barrier_alert(
                AsyncMock(),
                observation=payload,
            )
            second = await PublishOperatorAlertService.upsert_stranded_post_barrier_alert(
                AsyncMock(),
                observation=payload,
            )
            assert upsert.await_count == 2
            dedupe = upsert.await_args_list[0].kwargs["dedupe_key"]
            assert dedupe == stranded_dedupe_key(obs.command_id)
            assert upsert.await_args_list[0].kwargs["alert_type"] == "operator_review"
            assert upsert.await_args_list[0].kwargs["severity"] == "critical"
            ctx = upsert.await_args_list[0].kwargs["context"]
            assert ctx["phase_e"] == PHASE_E_CONTEXT_MARKER
            assert ctx["requires_operator_action"] is True
            assert ctx["safe_auto_recheck"] is False
            assert ctx["auto_ack_eligible"] is False
            return first, second

    first, second = asyncio.run(_run())
    assert first is True
    assert second is False


def test_provider_call_started_event_name_stable():
    assert PROVIDER_CALL_STARTED_EVENT == "publishing.retry_command_provider_call_started"
    assert len(PROVIDER_CALL_STARTED_EVENT) <= 50


def test_api_route_stranded_registered_before_command_id():
    from app.api.v1 import publishing as pub

    src = Path(pub.__file__).read_text(encoding="utf-8")
    stranded_idx = src.index('/retry-commands/stranded"')
    by_id_idx = src.index('/retry-commands/{command_id}"')
    assert stranded_idx < by_id_idx


def _stranded_list_payload(*, enabled: bool, created: int = 0, updated: int = 0):
    return {
        "items": [],
        "total": 0,
        "page": 1,
        "page_size": 20,
        "quiet_period": {
            "lease_seconds": 180,
            "drain_seconds": 60,
            "provider_slack_seconds": 300,
            "safety_buffer_seconds": 120,
            "quiet_period_seconds": 600,
            "formula": "x",
            "heuristic_only": True,
            "authorizes_provider_write": False,
        },
        "alert_surfacing_enabled": enabled,
        "alerts_created": created,
        "alerts_updated": updated,
        "phase_e": PHASE_E_CONTEXT_MARKER,
        "read_only_commands": True,
    }


def test_api_list_stranded_commits_only_when_alert_writes_occurred():
    """A–D: commit only when surfacing on and alert created/updated."""
    import asyncio

    from app.api.v1 import publishing as pub

    src = inspect.getsource(pub.list_stranded_retry_commands)
    assert "await db.commit()" in src
    assert 'result.get("alert_surfacing_enabled")' in src
    assert 'result.get("alerts_created")' in src
    assert 'result.get("alerts_updated")' in src

    async def _run(*, enabled: bool, created: int, updated: int):
        db = AsyncMock()
        db.commit = AsyncMock()
        with (
            patch.object(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True),
            patch.object(pub, "_resolve_scope", return_value=uuid.uuid4()),
            patch.object(
                PublishRetryCommandStrandedDetector,
                "list_stranded",
                AsyncMock(
                    return_value=_stranded_list_payload(
                        enabled=enabled, created=created, updated=updated,
                    ),
                ),
            ),
        ):
            await pub.list_stranded_retry_commands(
                page=1,
                page_size=20,
                tenant_id=None,
                db=db,
                user=None,
                admin=MagicMock(),
            )
        return db.commit

    # A. surfacing=false → commit count 0
    commit = asyncio.run(_run(enabled=False, created=0, updated=0))
    commit.assert_not_awaited()
    # D. surfacing=true + no created/updated → commit count 0
    commit = asyncio.run(_run(enabled=True, created=0, updated=0))
    commit.assert_not_awaited()
    # B. surfacing=true + alert created → commit count 1
    commit = asyncio.run(_run(enabled=True, created=1, updated=0))
    commit.assert_awaited_once()
    # C. surfacing=true + alert updated → commit count 1
    commit = asyncio.run(_run(enabled=True, created=0, updated=1))
    commit.assert_awaited_once()


def test_default_off_zero_write_across_multiple_gets():
    """surfacing=false: multiple GETs never add/flush/commit; command unchanged."""
    import asyncio

    tenant_id = uuid.uuid4()
    quiet = compute_quiet_period_seconds()
    cmd = _cmd(
        tenant_id=tenant_id,
        provider_write_started_at=_now() - timedelta(seconds=quiet + 30),
    )
    attempt = SimpleNamespace(
        id=cmd.resulting_attempt_id,
        external_post_id="ext-1",
        status="in_progress",
        provider_outcome=None,
        finished_at=None,
    )
    before_cmd = {
        "status": cmd.status,
        "lease_owner": cmd.lease_owner,
        "lease_expires_at": cmd.lease_expires_at,
        "provider_write_started_at": cmd.provider_write_started_at,
        "provider_outcome": cmd.provider_outcome,
        "finished_at": cmd.finished_at,
        "resulting_attempt_id": cmd.resulting_attempt_id,
        "original_attempt_id": cmd.original_attempt_id,
    }
    before_attempt = {
        "status": attempt.status,
        "provider_outcome": attempt.provider_outcome,
        "finished_at": attempt.finished_at,
        "external_post_id": attempt.external_post_id,
    }

    def _fresh_db():
        count_result = MagicMock()
        count_result.scalar_one.return_value = 1
        rows_result = MagicMock()
        rows_result.scalars.return_value.all.return_value = [cmd]
        attempts_result = MagicMock()
        attempts_result.scalars.return_value.all.return_value = [attempt]
        empty_audits = MagicMock()
        empty_audits.scalars.return_value.all.return_value = []
        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[count_result, rows_result, attempts_result, empty_audits],
        )
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.commit = AsyncMock()
        return db

    async def _run_once():
        db = _fresh_db()
        with patch.object(
            PublishRetryCommandStrandedDetector,
            "_surface_alert",
            AsyncMock(side_effect=AssertionError("alert must not surface when off")),
        ):
            result = await PublishRetryCommandStrandedDetector.list_stranded(
                db,
                tenant_id=tenant_id,
                now=_now(),
                create_alerts=False,
            )
        return db, result

    for _ in range(3):
        db, result = asyncio.run(_run_once())
        assert result["alert_surfacing_enabled"] is False
        assert result["alerts_created"] == 0
        assert result["alerts_updated"] == 0
        db.add.assert_not_called()
        db.flush.assert_not_awaited()
        db.commit.assert_not_awaited()

    for key, value in before_cmd.items():
        assert getattr(cmd, key) == value
    for key, value in before_attempt.items():
        assert getattr(attempt, key) == value


def test_alert_on_command_immutability_and_no_retry_creation():
    """surfacing=true + alert write: only alert path; command/attempt snapshot stable."""
    import asyncio

    from app.api.v1 import publishing as pub

    tenant_id = uuid.uuid4()
    quiet = compute_quiet_period_seconds()
    cmd = _cmd(
        tenant_id=tenant_id,
        provider_write_started_at=_now() - timedelta(seconds=quiet + 30),
    )
    before = {
        "status": cmd.status,
        "lease_owner": cmd.lease_owner,
        "lease_expires_at": cmd.lease_expires_at,
        "provider_write_started_at": cmd.provider_write_started_at,
        "provider_outcome": cmd.provider_outcome,
        "finished_at": cmd.finished_at,
        "resulting_attempt_id": cmd.resulting_attempt_id,
        "original_attempt_id": cmd.original_attempt_id,
        "claimed_at": cmd.claimed_at,
    }

    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    rows_result = MagicMock()
    rows_result.scalars.return_value.all.return_value = [cmd]
    empty_attempts = MagicMock()
    empty_attempts.scalars.return_value.all.return_value = []
    empty_audits = MagicMock()
    empty_audits.scalars.return_value.all.return_value = []
    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[count_result, rows_result, empty_attempts, empty_audits],
    )

    async def _detector():
        with patch.object(
            PublishRetryCommandStrandedDetector,
            "_surface_alert",
            AsyncMock(return_value=True),
        ) as surface:
            result = await PublishRetryCommandStrandedDetector.list_stranded(
                db,
                tenant_id=tenant_id,
                now=_now(),
                create_alerts=True,
            )
            surface.assert_awaited_once()
            return result

    result = asyncio.run(_detector())
    assert result["alerts_created"] == 1
    for key, value in before.items():
        assert getattr(cmd, key) == value

    # Route commit after create does not invent replacement commands / mutations.
    route_db = AsyncMock()
    route_db.commit = AsyncMock()
    async def _route():
        with (
            patch.object(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", True),
            patch.object(pub, "_resolve_scope", return_value=tenant_id),
            patch.object(
                PublishRetryCommandStrandedDetector,
                "list_stranded",
                AsyncMock(return_value=_stranded_list_payload(enabled=True, created=1)),
            ),
        ):
            await pub.list_stranded_retry_commands(
                page=1,
                page_size=20,
                tenant_id=tenant_id,
                db=route_db,
                user=None,
                admin=MagicMock(),
            )

    asyncio.run(_route())
    route_db.commit.assert_awaited_once()
    for key, value in before.items():
        assert getattr(cmd, key) == value


def test_stranded_route_auth_and_tenant_scope_resolution():
    """Stranded GET uses shared publishing scope; no mutation endpoint added."""
    from fastapi import HTTPException

    from app.api.v1 import publishing as pub
    from app.services.publishing_tenant_scope import resolve_publishing_tenant_id

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    user = SimpleNamespace(tenant_id=tenant_a, id=uuid.uuid4(), role="owner")
    admin = SimpleNamespace(id=uuid.uuid4(), role="platform_admin")

    assert resolve_publishing_tenant_id(user, None, None) == tenant_a
    assert resolve_publishing_tenant_id(user, None, tenant_a) == tenant_a
    with pytest.raises(HTTPException) as cross:
        resolve_publishing_tenant_id(user, None, tenant_b)
    assert cross.value.status_code == 403

    assert resolve_publishing_tenant_id(None, admin, tenant_b) == tenant_b
    with pytest.raises(HTTPException) as missing:
        resolve_publishing_tenant_id(None, admin, None)
    assert missing.value.status_code == 400

    with pytest.raises(HTTPException) as unauth:
        resolve_publishing_tenant_id(None, None, tenant_a)
    assert unauth.value.status_code == 401

    src = inspect.getsource(pub)
    assert '@router.get(\n    "/retry-commands/stranded"' in src or (
        '"/retry-commands/stranded"' in src
        and "list_stranded_retry_commands" in src
    )
    assert "@router.post" not in inspect.getsource(pub.list_stranded_retry_commands)
    assert "@router.patch" not in inspect.getsource(pub.list_stranded_retry_commands)
    assert "@router.delete" not in inspect.getsource(pub.list_stranded_retry_commands)
    # No E2 mutation handlers for stranded recovery.
    assert "mark_ambiguous_stranded" not in src
    assert "stranded_recover" not in src
    assert "stranded_replay" not in src
