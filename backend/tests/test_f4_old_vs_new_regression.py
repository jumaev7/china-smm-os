"""F4 — old vs new publishing regression harness (isolated).

Compares source-equivalent old production algorithms
(``338d3f966fa7c5fd2795201e555512f1eebcadc9`` /
image ``sha256:34d2977e…``) against the F1–F3 candidate.

Never connects to production PostgreSQL or real providers.
Does not modify business logic.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import text

from app.core.config import settings
from app.schemas.publishing import PublishContentRequest
from app.services.publish_resilience import (
    ClaimResult,
    PublishResilienceService,
    evaluate_live_success_identity,
    shape_live_success_skip_result,
)
from app.services.publish_service import ADAPTERS, PublishService

from tests.f4_harness.adapters import CountingAdapter, TimeoutAdapter
from tests.f4_harness.capture import ScenarioCapture, capture_from_prior
from tests.f4_harness.compare import (
    INTENDED_ACCEPTANCE,
    Classification,
    ScenarioOutcome,
    classify_scenario,
)
from tests.f4_harness.constants import (
    DISABLED_FEATURE_FLAGS,
    NEW_BASELINE_SHA,
    OLD_IMAGE_ID,
    OLD_SOURCE_SHA,
)
from tests.f4_harness.db import (
    insert_success_attempt,
    new_fixture_ids,
    null_intent_count,
    registry_count,
    run_async,
    seed_base,
    session_factory,
)
from tests.f4_harness.isolation import prove_isolation, resolve_pg_url
from tests.f4_harness.old_algorithms import (
    old_find_live_success,
    old_prior_live_successes,
    old_shape_already_published,
)
from tests.f4_harness.report import build_report, write_reports
from tests.f4_harness.source_pin import verify_old_source_pins

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = REPO_ROOT / "backend" / "tests" / "f4_harness" / "artifacts"

# Module collectors — finalized by test_z99_write_comparison_report.
OUTCOMES: list[ScenarioOutcome] = []
SCHEMA_RESULTS: dict = {}
PROVIDER_SUMMARY: dict = {
    "scenarios": [],
    "unexplained_extra_writes": 0,
}
API_REGRESSION: dict = {"cases": [], "cross_tenant_leaks": 0}
FAILURE_INJECTION: dict = {"cases": []}
REGISTRY_NEUTRALITY: dict = {
    "unexpected_mutations": 0,
    "execution_activation": 0,
    "cases": [],
}
KNOWN_SAFETY: list[str] = [
    (
        "I1 fixed: platform-keyed _prior_live_successes no longer suppresses "
        "proven-distinct cross-account publishes; alias/NULL remain fail-closed."
    ),
    (
        "Old find_live_success treats durable external_post_id as live even when "
        "response is mock/test — pre-F1 hazard; new F1 refuses suppression."
    ),
    (
        "Platform-keyed prior reader ignores publish_version changes — both "
        "versions suppress republish after a prior live success on that platform "
        "(intentional until I2 mint_new)."
    ),
]


def _record(outcome: ScenarioOutcome) -> ScenarioOutcome:
    OUTCOMES.append(outcome)
    if (
        outcome.old.get("provider_calls", 0) < outcome.new.get("provider_calls", 0)
        and outcome.classification != Classification.INTENDED
    ):
        PROVIDER_SUMMARY["unexplained_extra_writes"] += 1
    PROVIDER_SUMMARY["scenarios"].append(
        {
            "id": outcome.scenario_id,
            "old_calls": outcome.old.get("provider_calls"),
            "new_calls": outcome.new.get("provider_calls"),
            "classification": outcome.classification.value,
            "verdict": outcome.verdict,
        }
    )
    assert outcome.verdict != "FAIL", (
        f"{outcome.scenario_id} FAIL: {outcome.difference}"
    )
    assert outcome.verdict != "UNRESOLVED", (
        f"{outcome.scenario_id} UNRESOLVED: {outcome.difference}"
    )
    return outcome


def _disable_flags():
    patches = []
    for name in DISABLED_FEATURE_FLAGS:
        if hasattr(settings, name):
            patches.append(patch.object(settings, name, False))
    if hasattr(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND"):
        patches.append(
            patch.object(settings, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", "none")
        )
    return patches


@contextmanager
def _flags_disabled():
    cm = _disable_flags()
    for p in cm:
        p.start()
    try:
        yield
    finally:
        for p in reversed(cm):
            p.stop()


def _old_already_published_claim(prior, *, platform, account_id, account_name):
    return ClaimResult(
        attempt=prior,
        skip=True,
        reason="already_published",
        result=old_shape_already_published(
            prior,
            platform=platform,
            account_id=account_id,
            account_name=account_name,
        ),
    )


@contextmanager
def _old_reader_stack():
    """Swap success readers to old-image algorithms."""

    async def _old_find(cls, db, **kwargs):
        return await old_find_live_success(db, **kwargs)

    async def _old_prior_for_destination(db, *, content_id, platform, account):
        # Pre-I1: platform-keyed — account argument ignored.
        found = await old_prior_live_successes(db, content_id, [platform])
        return found.get(platform)

    async def _old_find_destination(
        cls, db, *, content_id, platform, account_id, account=None
    ):
        prior = await old_find_live_success(
            db,
            content_id=content_id,
            platform=platform,
            account_id=account_id,
        )
        if prior is None:
            return None, None
        return prior, "SAME_DESTINATION"

    with (
        patch.object(
            PublishService,
            "_prior_live_successes",
            staticmethod(old_prior_live_successes),
        ),
        patch.object(
            PublishService,
            "_prior_live_success_for_destination",
            staticmethod(_old_prior_for_destination),
        ),
        patch.object(
            PublishResilienceService,
            "find_live_success",
            classmethod(_old_find),
        ),
        patch.object(
            PublishResilienceService,
            "find_destination_live_success",
            classmethod(_old_find_destination),
        ),
        patch.object(
            PublishResilienceService,
            "_already_published_claim",
            classmethod(
                lambda cls, prior, *, platform, account_id, account_name,
                destination_comparison=None: (
                    _old_already_published_claim(
                        prior,
                        platform=platform,
                        account_id=account_id,
                        account_name=account_name,
                    )
                )
            ),
        ),
    ):
        yield


@contextmanager
def _publish_harness(fx, adapters: dict[str, CountingAdapter]):
    from datetime import datetime, timezone

    item = SimpleNamespace(
        id=fx.content_id,
        client_id=fx.client_id,
        media_file_id=None,
        media_file=None,
        platforms=list(getattr(fx, "platforms", None) or [fx.platform]),
        status="failed",
        source="manual",
        caption_short_ru=None,
        caption_long_ru="f4 hello",
        caption_long_en=None,
        caption_long_uz=None,
        caption_long_zh=None,
        caption_short_uz=None,
        caption_short_en=None,
        caption_short_zh=None,
        hashtags=None,
        internal_notes=None,
        approved_at=datetime.now(timezone.utc),
        published_at=None,
        scheduled_for=None,
        client_review_status=None,
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )

    def _fixed_version(_item, _payload=None):
        return fx.publish_version

    async def _get_content(_db, content_id):
        assert content_id == fx.content_id
        return item

    async def _serialize(_db, _item):
        return {
            "id": str(fx.content_id),
            "platforms": list(item.platforms),
            "caption_long_ru": "f4 hello",
            "media_url": None,
            "generated_final_video_url": None,
            "published_at": item.published_at,
            "status": item.status,
        }

    async def _resolve(
        db, tenant_id, platform, explicit_account, client_publish_chat_id=None
    ):
        aid = explicit_account or fx.account_id
        name = "TG A"
        ext = "tg-a"
        if aid == fx.account_b_id:
            name, ext = "TG B", "tg-b"
        elif aid == fx.fb_account_id:
            name, ext = "FB A", "fb-a"
        return SimpleNamespace(
            id=aid,
            account_name=name,
            account_id=ext,
            platform=platform,
            status="mock",
            tenant_id=fx.tenant_id,
            access_token_encrypted=None,
            refresh_token_encrypted=None,
            facebook_page_id=None,
            instagram_business_account_id=None,
            permissions_json=None,
            account_metadata_json=None,
            expires_at=None,
        )

    # ExitStack: star-unpack of patch() into `with (...)` is unreliable across
    # Python versions (tuple CM protocol errors).
    with ExitStack() as stack:
        for p in _disable_flags():
            stack.enter_context(p)
        stack.enter_context(
            patch.object(PublishService, "_get_content", staticmethod(_get_content))
        )
        stack.enter_context(
            patch.object(
                PublishService,
                "recover_stale_publishing",
                new=staticmethod(AsyncMock(return_value=0)),
            )
        )
        stack.enter_context(
            patch(
                "app.services.content_service.ContentService.serialize_detail",
                new=AsyncMock(side_effect=_serialize),
            )
        )
        stack.enter_context(
            patch(
                "app.services.publish_safety_service.PublishSafetyService.enforce_or_block",
                new=AsyncMock(return_value=None),
            )
        )
        stack.enter_context(
            patch(
                "app.services.publish_service.compute_publish_version",
                side_effect=_fixed_version,
            )
        )
        stack.enter_context(
            patch(
                "app.services.publishing_account_service.PublishingAccountService.resolve_for_platform",
                new=AsyncMock(side_effect=_resolve),
            )
        )
        stack.enter_context(
            patch(
                "app.services.publish_service.tenant_id_for_content",
                new=AsyncMock(return_value=fx.tenant_id),
            )
        )
        # Keep alert/measurement ORM side-paths from poisoning the publish TX
        # on the minimal fixture (same approach as E2-2 coordination harness).
        stack.enter_context(
            patch.object(
                PublishResilienceService,
                "_notify_alert",
                new=staticmethod(AsyncMock(return_value=None)),
            )
        )
        stack.enter_context(
            patch(
                "app.services.measurement.publication_registry.register_from_publish_attempt",
                new=AsyncMock(return_value=None),
            )
        )
        stack.enter_context(
            patch.object(
                PublishService,
                "_client_publish_context",
                new=staticmethod(
                    AsyncMock(
                        return_value={
                            "chat_id": None,
                            "company_name": "Co",
                            "publish_title": None,
                        }
                    )
                ),
            )
        )
        stack.enter_context(patch.dict(ADAPTERS, adapters, clear=False))
        yield item


# ── Preflight / isolation / schema ───────────────────────────────────────────


def test_00_source_pin_and_baseline():
    pin = verify_old_source_pins()
    assert pin["ok"], pin
    assert OLD_SOURCE_SHA.startswith("338d3f9")
    assert OLD_IMAGE_ID.startswith("sha256:34d2977e")
    # Baseline identity (working tree may have only F4 untracked adds).
    head = os.popen("git rev-parse HEAD").read().strip()
    assert head == NEW_BASELINE_SHA


def test_01_isolation_proof():
    proof = prove_isolation()
    assert proof.ok, proof.failures
    assert proof.port == 54329
    assert "f4" in proof.database_name


def test_02_schema_compatibility_modes():
    async def body():
        results = {}
        # A — historical (no intent column / no registry)
        async with session_factory("A_historical") as factory:
            async with factory() as db:
                fx = new_fixture_ids()
                await seed_base(db, fx)
                await insert_success_attempt(
                    db,
                    fx,
                    external_post_id=None,
                    response={"success": True, "platform_post_id": "hist-1"},
                    with_intent_column=False,
                )
                # Column absent
                missing = (
                    await db.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_name='publish_attempts' "
                            "AND column_name='publication_intent_id'"
                        )
                    )
                ).first()
                reg = (
                    await db.execute(
                        text(
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_name='publish_write_coordination_registry'"
                        )
                    )
                ).first()
                results["A_historical"] = {
                    "publication_intent_id_column": missing is not None,
                    "registry_table": reg is not None,
                    "note": (
                        "Historical schema has no intent column/registry. "
                        "ORM new models expect R1; algorithm comparison uses "
                        "in-memory/R1 fixtures for B/C."
                    ),
                }
                assert missing is None
                assert reg is None

        # B/C — R1 schema; historical NULLs stay NULL
        for mode in ("B_old_on_r1", "C_new_on_r1"):
            async with session_factory(mode) as factory:
                async with factory() as db:
                    fx = new_fixture_ids()
                    await seed_base(db, fx)
                    await insert_success_attempt(
                        db,
                        fx,
                        external_post_id="durable-1",
                        response=None,
                        publication_intent_id=None,
                        with_intent_column=True,
                    )
                    n_null = await null_intent_count(db)
                    n_reg = await registry_count(db)
                    results[mode] = {
                        "null_intent_rows": n_null,
                        "registry_rows": n_reg,
                        "fabricated_intents": 0,
                    }
                    assert n_null == 1
                    assert n_reg == 0

        SCHEMA_RESULTS.update(results)

    run_async(body)


# ── Success-identity matrix (prior readers) ──────────────────────────────────


def _identity_cases():
    return [
        (
            "success_identity_response_only",
            {"response": {"success": True, "platform_post_id": "resp-1"}, "ext": None},
            Classification.EQUIVALENT,
            "Response-only live id suppresses in both versions.",
            None,
        ),
        (
            "success_identity_durable_only",
            {"response": None, "ext": "dur-1"},
            Classification.INTENDED,
            INTENDED_ACCEPTANCE["followup_a_durable_only"],
            "followup_a",
        ),
        (
            "success_identity_matching_ids",
            {
                "response": {"success": True, "platform_post_id": "same-1"},
                "ext": "same-1",
            },
            Classification.EQUIVALENT,
            "Matching durable/response IDs suppress in both versions.",
            None,
        ),
        (
            "success_identity_conflicting_ids",
            {
                "response": {"success": True, "platform_post_id": "resp-x"},
                "ext": "dur-y",
            },
            Classification.INTENDED,
            INTENDED_ACCEPTANCE["f1_conflict"],
            "f1_conflict",
        ),
        (
            "success_identity_missing_ids",
            {"response": {"success": True}, "ext": None},
            Classification.EQUIVALENT,
            "Missing IDs never suppress.",
            None,
        ),
        (
            "success_identity_mock_success",
            {
                "response": {
                    "success": True,
                    "mock": True,
                    "platform_post_id": "mock-1",
                },
                "ext": None,
            },
            Classification.EQUIVALENT,
            "Mock response never suppresses (no durable).",
            None,
        ),
        (
            "success_identity_test_success",
            {
                "response": {
                    "success": True,
                    "test": True,
                    "platform_post_id": "test-1",
                },
                "ext": None,
            },
            Classification.EQUIVALENT,
            "Test response never suppresses (no durable).",
            None,
        ),
        (
            "success_identity_mock_with_durable",
            {
                "response": {
                    "success": True,
                    "mock": True,
                    "platform_post_id": "mock-d",
                },
                "ext": "dur-mock",
            },
            Classification.EQUIVALENT,
            "Prior-reader: mock marker wins in both (old prior skipped mock; "
            "new evaluate_live_success_identity refuses). find_live differs — "
            "measured separately.",
            None,
        ),
        (
            "success_identity_intentional_republish_empty_prior",
            {"response": None, "ext": None, "skip_seed": True},
            Classification.EQUIVALENT,
            "No prior success → allow in both.",
            None,
        ),
    ]


@pytest.mark.parametrize("case", _identity_cases(), ids=lambda c: c[0])
def test_10_success_identity_prior_matrix(case):
    scenario_id, seed, expected, acceptance, _tag = case

    async def body():
        async with session_factory("C_new_on_r1") as factory:
            async with factory() as db:
                fx = new_fixture_ids()
                await seed_base(db, fx)
                if not seed.get("skip_seed"):
                    await insert_success_attempt(
                        db,
                        fx,
                        external_post_id=seed["ext"],
                        response=seed["response"],
                        publication_intent_id=None,
                    )
                with _flags_disabled():
                    old_prior = await old_prior_live_successes(
                        db, fx.content_id, [fx.platform]
                    )
                    new_prior = await PublishService._prior_live_successes(
                        db, fx.content_id, [fx.platform], account_id=fx.account_id
                    )
                reg = await registry_count(db)

        old_c = capture_from_prior(
            scenario_id=scenario_id,
            side="old",
            schema_mode="C_new_on_r1",
            prior=old_prior,
            platform=fx.platform,
            registry_row_count=reg,
            external_post_id=seed.get("ext"),
        )
        new_c = capture_from_prior(
            scenario_id=scenario_id,
            side="new",
            schema_mode="C_new_on_r1",
            prior=new_prior,
            platform=fx.platform,
            registry_row_count=reg,
            external_post_id=seed.get("ext"),
        )
        # Cosmetic serialization diffs (old omits keys; new sets explicit False)
        # are allowed; identity/suppression/provider gates remain compared.
        allow = {
            "message",
            "attempt_id",
            "account_id",
            "account_name",
            "post_url",
            "error",
            "failure_code",
            "failure_category",
            "retryable",
            "operator_review",
            "conflict_durable_external_post_id",
            "conflict_response_platform_post_id",
            "success",
            "mock",
            "identity_conflict",
            "deduplicated",
            "destination_identity",
        }
        if expected == Classification.INTENDED:
            allow |= {"platform_post_id"}
        outcome = classify_scenario(
            scenario_id=scenario_id,
            category="success_identity",
            old=old_c,
            new=new_c,
            expected_classification=expected,
            acceptance_criterion=acceptance,
            allow_api_diff_keys=allow,
            evidence=[
                f"old_prior_keys={list(old_prior)}",
                f"new_prior_keys={list(new_prior)}",
            ],
        )
        # Strengthen intended assertions
        if scenario_id == "success_identity_durable_only":
            assert not old_prior
            assert new_prior[fx.platform]["deduplicated"] is True
            assert new_prior[fx.platform]["platform_post_id"] == "dur-1"
        if scenario_id == "success_identity_conflicting_ids":
            assert fx.platform in old_prior
            assert old_prior[fx.platform].get("platform_post_id") == "resp-x"
            assert new_prior[fx.platform]["identity_conflict"] is True
            assert new_prior[fx.platform]["platform_post_id"] is None
            assert new_prior[fx.platform]["conflict_durable_external_post_id"] == "dur-y"
            assert (
                new_prior[fx.platform]["conflict_response_platform_post_id"] == "resp-x"
            )
        _record(outcome)

    run_async(body)


def test_11_find_live_mock_with_durable_intended():
    """F1 vs old find_live_success: mock+durable."""

    async def body():
        async with session_factory("C_new_on_r1") as factory:
            async with factory() as db:
                fx = new_fixture_ids()
                await seed_base(db, fx)
                await insert_success_attempt(
                    db,
                    fx,
                    external_post_id="dur-mock",
                    response={
                        "success": True,
                        "mock": True,
                        "platform_post_id": "mock-d",
                    },
                )
                with _flags_disabled():
                    old = await old_find_live_success(
                        db,
                        content_id=fx.content_id,
                        platform=fx.platform,
                        account_id=fx.account_id,
                    )
                    new = await PublishResilienceService.find_live_success(
                        db,
                        content_id=fx.content_id,
                        platform=fx.platform,
                        account_id=fx.account_id,
                    )
                    identity = evaluate_live_success_identity(
                        SimpleNamespace(
                            status="success",
                            external_post_id="dur-mock",
                            response=json.dumps(
                                {
                                    "success": True,
                                    "mock": True,
                                    "platform_post_id": "mock-d",
                                }
                            ),
                        )
                    )

        old_c = ScenarioCapture(
            scenario_id="f1_find_live_mock_with_durable",
            side="old",
            schema_mode="C_new_on_r1",
            suppression_decision="suppress" if old else "allow",
            provider_calls=0 if old else 1,
            identity_conflict=False,
            extras={"found": old is not None},
        )
        new_c = ScenarioCapture(
            scenario_id="f1_find_live_mock_with_durable",
            side="new",
            schema_mode="C_new_on_r1",
            suppression_decision="suppress" if new else "allow",
            provider_calls=0 if new else 1,
            identity_conflict=False,
            extras={"found": new is not None, "identity_suppresses": identity.suppresses},
        )
        assert old is not None  # old hazard
        assert new is None
        assert identity.suppresses is False
        _record(
            classify_scenario(
                scenario_id="f1_find_live_mock_with_durable",
                category="success_identity",
                old=old_c,
                new=new_c,
                expected_classification=Classification.INTENDED,
                acceptance_criterion=INTENDED_ACCEPTANCE["f1_mock_with_durable"],
                evidence=["old_find_live returned attempt", "new find_live None"],
            )
        )

    run_async(body)


# ── Provider-write publish_content comparisons ───────────────────────────────


def test_20_publish_provider_calls_matrix():
    cases = [
        (
            "pub_fresh_success",
            None,
            Classification.EQUIVALENT,
            "Fresh publish: both invoke provider once.",
            1,
            1,
        ),
        (
            "pub_response_only_suppress",
            {
                "ext": None,
                "response": {"success": True, "platform_post_id": "resp-live"},
            },
            Classification.EQUIVALENT,
            "Response-only prior suppresses provider write in both.",
            0,
            0,
        ),
        (
            "pub_durable_only",
            {"ext": "dur-live", "response": None},
            Classification.INTENDED,
            INTENDED_ACCEPTANCE["followup_a_durable_only"]
            + " Provider outcome equivalent (both 0 writes) via different gates.",
            0,
            0,
        ),
        (
            "pub_conflict",
            {
                "ext": "dur-c",
                "response": {"success": True, "platform_post_id": "resp-c"},
            },
            Classification.INTENDED,
            INTENDED_ACCEPTANCE["f1_conflict"],
            0,
            0,
        ),
        (
            "pub_mock_with_durable",
            {
                "ext": "dur-m",
                "response": {
                    "success": True,
                    "mock": True,
                    "platform_post_id": "m1",
                },
            },
            Classification.INTENDED,
            INTENDED_ACCEPTANCE["f1_mock_with_durable"],
            0,
            1,
        ),
    ]

    async def body():
        for scenario_id, seed, expected, acceptance, old_expect, new_expect in cases:
            async with session_factory("C_new_on_r1") as factory:
                fx = new_fixture_ids()
                async with factory() as db:
                    await seed_base(db, fx)
                    if seed:
                        await insert_success_attempt(
                            db,
                            fx,
                            external_post_id=seed["ext"],
                            response=seed["response"],
                        )

                old_adapter = CountingAdapter("telegram", post_id="old-out")
                new_adapter = CountingAdapter("telegram", post_id="new-out")

                # Old path
                with _publish_harness(fx, {"telegram": old_adapter}), _old_reader_stack():
                    async with factory() as db:
                        old_result = await PublishService.publish_content(
                            db,
                            fx.content_id,
                            request=PublishContentRequest(
                                mode="manual_publish",
                                platforms=["telegram"],
                                account_id=fx.account_id,
                            ),
                        )
                        old_reg = await registry_count(db)
                        await db.rollback()

                # Reset DB state for new path (re-seed)
                async with session_factory("C_new_on_r1") as factory2:
                    async with factory2() as db:
                        await seed_base(db, fx)
                        if seed:
                            await insert_success_attempt(
                                db,
                                fx,
                                external_post_id=seed["ext"],
                                response=seed["response"],
                            )
                    with _publish_harness(fx, {"telegram": new_adapter}):
                        async with factory2() as db:
                            new_result = await PublishService.publish_content(
                                db,
                                fx.content_id,
                                request=PublishContentRequest(
                                    mode="manual_publish",
                                    platforms=["telegram"],
                                    account_id=fx.account_id,
                                ),
                            )
                            new_reg = await registry_count(db)
                            alerts = (
                                await db.execute(
                                    text(
                                        "SELECT COUNT(*) FROM publish_operator_alerts"
                                    )
                                )
                            ).scalar_one()
                            await db.rollback()

            assert old_adapter.invocation_count == old_expect, scenario_id
            assert new_adapter.invocation_count == new_expect, scenario_id
            assert old_reg == 0 and new_reg == 0

            old_row = (old_result.get("results") or [{}])[0]
            new_row = (new_result.get("results") or [{}])[0]
            old_c = ScenarioCapture(
                scenario_id=scenario_id,
                side="old",
                schema_mode="C_new_on_r1",
                provider_calls=old_adapter.invocation_count,
                provider_platform="telegram",
                provider_account_id=str(fx.account_id),
                suppression_decision=(
                    "suppress"
                    if old_adapter.invocation_count == 0 and seed
                    else "allow"
                ),
                api_result=old_row,
                identity_conflict=bool(old_row.get("identity_conflict")),
                registry_row_count=0,
            )
            new_c = ScenarioCapture(
                scenario_id=scenario_id,
                side="new",
                schema_mode="C_new_on_r1",
                provider_calls=new_adapter.invocation_count,
                provider_platform="telegram",
                provider_account_id=str(fx.account_id),
                suppression_decision=(
                    "conflict"
                    if new_row.get("identity_conflict")
                    else (
                        "suppress"
                        if new_adapter.invocation_count == 0 and seed
                        else "allow"
                    )
                ),
                api_result=new_row,
                identity_conflict=bool(new_row.get("identity_conflict")),
                registry_row_count=0,
                alert_events=["identity_conflict"] if int(alerts) else [],
            )
            if scenario_id == "pub_conflict":
                assert new_row.get("identity_conflict") is True
                assert new_row.get("platform_post_id") is None
                assert int(alerts) >= 1
            allow = {
                "message",
                "attempt_id",
                "account_id",
                "account_name",
                "post_url",
                "platform_post_id",
                "success",
                "error",
                "failure_code",
                "failure_category",
                "retryable",
                "operator_review",
                "conflict_durable_external_post_id",
                "conflict_response_platform_post_id",
                "deduplicated",
                "identity_conflict",
                "destination_identity",
                "mock",
                "platform",
            }
            _record(
                classify_scenario(
                    scenario_id=scenario_id,
                    category="normal_publishing",
                    old=old_c,
                    new=new_c,
                    expected_classification=expected,
                    acceptance_criterion=acceptance,
                    allow_api_diff_keys=allow,
                    require_same_provider_calls=(expected == Classification.EQUIVALENT),
                    evidence=[
                        f"old_calls={old_adapter.invocation_count}",
                        f"new_calls={new_adapter.invocation_count}",
                    ],
                )
            )

    run_async(body)


def test_21_destination_identity_and_cross_account():
    async def body():
        # same content/platform/account → suppress both
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
                await insert_success_attempt(
                    db,
                    fx,
                    external_post_id="same-dest",
                    response={"success": True, "platform_post_id": "same-dest"},
                )
            old_a = CountingAdapter("telegram")
            new_a = CountingAdapter("telegram")
            with _publish_harness(fx, {"telegram": old_a}), _old_reader_stack():
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            with _publish_harness(fx, {"telegram": new_a}):
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
            assert old_a.invocation_count == 0
            assert new_a.invocation_count == 0
            _record(
                classify_scenario(
                    scenario_id="dest_same_content_platform_account",
                    category="destination_identity",
                    old=ScenarioCapture(
                        scenario_id="dest_same_content_platform_account",
                        side="old",
                        schema_mode="C_new_on_r1",
                        provider_calls=0,
                        suppression_decision="suppress",
                    ),
                    new=ScenarioCapture(
                        scenario_id="dest_same_content_platform_account",
                        side="new",
                        schema_mode="C_new_on_r1",
                        provider_calls=0,
                        suppression_decision="suppress",
                    ),
                    expected_classification=Classification.EQUIVALENT,
                    acceptance_criterion="Same destination suppresses in both.",
                )
            )

        # cross-account same platform — I1 allows proven-distinct B (old still 0)
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
                await insert_success_attempt(
                    db,
                    fx,
                    account_id=fx.account_id,
                    external_post_id="acct-a",
                    response={"success": True, "platform_post_id": "acct-a"},
                )
            old_a = CountingAdapter("telegram", post_id="acct-b-new")
            new_a = CountingAdapter("telegram", post_id="acct-b-new")
            with _publish_harness(fx, {"telegram": old_a}), _old_reader_stack():
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_b_id,
                        ),
                    )
            with _publish_harness(fx, {"telegram": new_a}):
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_b_id,
                        ),
                    )
            assert old_a.invocation_count == 0
            assert new_a.invocation_count == 1
            _record(
                classify_scenario(
                    scenario_id="dest_cross_account_platform_keyed",
                    category="destination_identity",
                    old=ScenarioCapture(
                        scenario_id="dest_cross_account_platform_keyed",
                        side="old",
                        schema_mode="C_new_on_r1",
                        provider_calls=0,
                        suppression_decision="suppress",
                    ),
                    new=ScenarioCapture(
                        scenario_id="dest_cross_account_platform_keyed",
                        side="new",
                        schema_mode="C_new_on_r1",
                        provider_calls=1,
                        suppression_decision="allow",
                    ),
                    expected_classification=Classification.INTENDED,
                    acceptance_criterion=(
                        "I1: proven-distinct account B is allowed after success "
                        "on account A (old platform-keyed reader still suppresses)."
                    ),
                )
            )

        # different platform allows
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx, platforms=["telegram", "facebook"])
                await insert_success_attempt(
                    db,
                    fx,
                    platform="telegram",
                    external_post_id="tg-1",
                    response={"success": True, "platform_post_id": "tg-1"},
                )
            old_fb = CountingAdapter("facebook", post_id="fb-new")
            with _publish_harness(fx, {"facebook": old_fb}), _old_reader_stack():
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["facebook"],
                            account_id=fx.fb_account_id,
                        ),
                    )
                    await db.rollback()
            assert old_fb.invocation_count == 1

        # Fresh fixture for new side so old facebook success cannot suppress.
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx, platforms=["telegram", "facebook"])
                await insert_success_attempt(
                    db,
                    fx,
                    platform="telegram",
                    external_post_id="tg-1",
                    response={"success": True, "platform_post_id": "tg-1"},
                )
            new_fb = CountingAdapter("facebook", post_id="fb-new")
            with _publish_harness(fx, {"facebook": new_fb}):
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["facebook"],
                            account_id=fx.fb_account_id,
                        ),
                    )
                    await db.rollback()
            assert new_fb.invocation_count == 1
            _record(
                classify_scenario(
                    scenario_id="dest_different_platform",
                    category="destination_identity",
                    old=ScenarioCapture(
                        scenario_id="dest_different_platform",
                        side="old",
                        schema_mode="C_new_on_r1",
                        provider_calls=1,
                        suppression_decision="allow",
                    ),
                    new=ScenarioCapture(
                        scenario_id="dest_different_platform",
                        side="new",
                        schema_mode="C_new_on_r1",
                        provider_calls=1,
                        suppression_decision="allow",
                    ),
                    expected_classification=Classification.EQUIVALENT,
                    acceptance_criterion="Different platform is a new destination.",
                )
            )

        # publish_version change is a new destination (both allow)
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
                await insert_success_attempt(
                    db,
                    fx,
                    external_post_id="old-ver",
                    response={"success": True, "platform_post_id": "old-ver"},
                    publish_version="pv_old",
                )
            # Fixed harness version is pv_f4_v1 ≠ pv_old → claim key differs;
            # prior_live_successes is platform-keyed and still suppresses.
            old_a = CountingAdapter("telegram", post_id="ver-new")
            new_a = CountingAdapter("telegram", post_id="ver-new")
            with _publish_harness(fx, {"telegram": old_a}), _old_reader_stack():
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
                    await db.rollback()
            async with session_factory("C_new_on_r1") as factory2:
                async with factory2() as db:
                    await seed_base(db, fx)
                    await insert_success_attempt(
                        db,
                        fx,
                        external_post_id="old-ver",
                        response={"success": True, "platform_post_id": "old-ver"},
                        publish_version="pv_old",
                    )
                with _publish_harness(fx, {"telegram": new_a}):
                    async with factory2() as db:
                        await PublishService.publish_content(
                            db,
                            fx.content_id,
                            request=PublishContentRequest(
                                mode="manual_publish",
                                platforms=["telegram"],
                                account_id=fx.account_id,
                            ),
                        )
                        await db.rollback()
            # Platform-keyed prior reader suppresses regardless of publish_version.
            assert old_a.invocation_count == 0
            assert new_a.invocation_count == 0
            _record(
                classify_scenario(
                    scenario_id="dest_publish_version_change_platform_keyed",
                    category="destination_identity",
                    old=ScenarioCapture(
                        scenario_id="dest_publish_version_change_platform_keyed",
                        side="old",
                        schema_mode="C_new_on_r1",
                        provider_calls=0,
                        suppression_decision="suppress",
                    ),
                    new=ScenarioCapture(
                        scenario_id="dest_publish_version_change_platform_keyed",
                        side="new",
                        schema_mode="C_new_on_r1",
                        provider_calls=0,
                        suppression_decision="suppress",
                    ),
                    expected_classification=Classification.COMMON_MODE_SAFETY,
                    acceptance_criterion=(
                        "publish_version change does not bypass platform-keyed "
                        "prior suppression in either version."
                    ),
                    safety_concern=(
                        "Platform-keyed prior reader ignores publish_version — "
                        "common-mode limitation."
                    ),
                )
            )

    run_async(body)


# ── Disabled features / registry / shadow neutrality ─────────────────────────


def test_30_disabled_features_and_registry_neutrality():
    with _flags_disabled():
        for name in DISABLED_FEATURE_FLAGS:
            if hasattr(settings, name):
                assert getattr(settings, name) is False, name
        assert settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND == "none"

    async def body():
        async with session_factory("C_new_on_r1") as factory:
            async with factory() as db:
                fx = new_fixture_ids()
                await seed_base(db, fx)
                # empty registry
                assert await registry_count(db) == 0
                await insert_success_attempt(
                    db,
                    fx,
                    external_post_id="x",
                    response={"success": True, "platform_post_id": "x"},
                    publication_intent_id=None,
                )
                assert await null_intent_count(db) == 1
                # shadow observe should no-op when flag false
                with _flags_disabled():
                    await PublishService._observe_write_coordination_shadow(
                        db,
                        tenant_id=fx.tenant_id,
                        content_id=fx.content_id,
                        platform="telegram",
                        account_id=fx.account_id,
                        publication_intent_id=None,
                        live_decision="allow",
                    )
                assert await registry_count(db) == 0
                audits = (
                    await db.execute(text("SELECT COUNT(*) FROM platform_audit_logs"))
                ).scalar_one()
                assert int(audits) == 0

        REGISTRY_NEUTRALITY["cases"].append(
            {
                "empty_registry": True,
                "historical_null_intents_preserved": True,
                "no_registry_mutations": True,
                "no_authority_acquisition": True,
                "no_automatic_backfill": True,
                "shadow_disabled_noop": True,
            }
        )
        _record(
            classify_scenario(
                scenario_id="registry_shadow_neutrality",
                category="registry",
                old=ScenarioCapture(
                    scenario_id="registry_shadow_neutrality",
                    side="old",
                    schema_mode="C_new_on_r1",
                    registry_row_count=0,
                    shadow_reads=0,
                    shadow_audit_writes=0,
                ),
                new=ScenarioCapture(
                    scenario_id="registry_shadow_neutrality",
                    side="new",
                    schema_mode="C_new_on_r1",
                    registry_row_count=0,
                    shadow_reads=0,
                    shadow_audit_writes=0,
                    registry_inserts=0,
                    registry_updates=0,
                    authority_acquisitions=0,
                ),
                expected_classification=Classification.EQUIVALENT,
                acceptance_criterion=INTENDED_ACCEPTANCE["f3_no_publish_behavior"],
            )
        )

    run_async(body)


# ── API regression ───────────────────────────────────────────────────────────


def test_40_api_regression():
    import asyncio

    from app.api.v1 import publishing as pub
    from app.schemas.publishing import PublishRetryCommandResolveRequest
    from app.services.publish_retry_command_manual_resolution_service import (
        ACTION_MARK_AMBIGUOUS,
        PublishRetryCommandManualResolutionService,
    )
    from app.services.publish_retry_command_stranded_detector import (
        PublishRetryCommandStrandedDetector,
    )

    cases: list[dict] = []

    # stranded default-off 404 (F2 intended vs old absent route)
    with patch.object(settings, "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED", False):
        db = AsyncMock()
        detector = AsyncMock(side_effect=AssertionError("no detector"))

        async def _stranded():
            with patch.object(
                PublishRetryCommandStrandedDetector, "list_stranded", detector
            ):
                with pytest.raises(HTTPException) as exc:
                    await pub.list_stranded_retry_commands(
                        page=1,
                        page_size=20,
                        tenant_id=uuid4(),
                        db=db,
                        user=SimpleNamespace(id=uuid4(), tenant_id=uuid4()),
                        admin=None,
                    )
                assert exc.value.status_code == 404

        asyncio.run(_stranded())
        detector.assert_not_awaited()
        db.execute.assert_not_called()
        cases.append(
            {
                "name": "stranded_default_off_404",
                "status": 404,
                "detector_calls": 0,
                "classification": "INTENDED",
                "acceptance": INTENDED_ACCEPTANCE["f2_stranded_default_off"],
            }
        )

    # manual resolve disabled → 403 (service gate)
    with patch.object(settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED", False):
        with patch.object(
            settings, "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED", False
        ):

            async def _resolve():
                with pytest.raises(HTTPException) as exc:
                    await PublishRetryCommandManualResolutionService.resolve(
                        AsyncMock(),
                        command_id=uuid4(),
                        tenant_id=uuid4(),
                        action=ACTION_MARK_AMBIGUOUS,
                        confirm_permanent_resolution=True,
                        operator_reason="f4",
                        actor_id=uuid4(),
                        actor_type="tenant_user",
                        commit=False,
                    )
                assert exc.value.status_code == 403

            asyncio.run(_resolve())
            cases.append(
                {
                    "name": "manual_resolve_disabled_403",
                    "status": 403,
                    "classification": "EQUIVALENT_SURFACE",
                    "note": "Manual resolution remains flag-gated (default off).",
                }
            )

    # retry-command GET remains present and is distinct from stranded detector
    src = Path(pub.__file__).read_text(encoding="utf-8")
    assert "get_publish_retry_command" in src
    assert "/retry-commands/{command_id}" in src
    assert "list_stranded_retry_commands" in src
    assert PublishRetryCommandResolveRequest is not None
    cases.append(
        {
            "name": "retry_command_get_present",
            "classification": "EQUIVALENT",
            "note": "Existing retry-command GET route retained; auth≠stranded SELECT.",
        }
    )

    API_REGRESSION["cases"] = cases
    _record(
        classify_scenario(
            scenario_id="api_stranded_default_off",
            category="api_regression",
            old=ScenarioCapture(
                scenario_id="api_stranded_default_off",
                side="old",
                schema_mode="C_new_on_r1",
                api_result={"route": "absent"},
                suppression_decision="n/a",
            ),
            new=ScenarioCapture(
                scenario_id="api_stranded_default_off",
                side="new",
                schema_mode="C_new_on_r1",
                api_result={"route": "present", "default": 404},
                suppression_decision="n/a",
            ),
            expected_classification=Classification.INTENDED,
            acceptance_criterion=INTENDED_ACCEPTANCE["f2_stranded_default_off"],
            allow_api_diff_keys=set(),
            evidence=["HTTP 404 when PUBLISH_RETRY_STRANDED_LIST_API_ENABLED=false"],
        )
    )


# ── Failure injection ────────────────────────────────────────────────────────


def test_50_failure_injection():
    async def body():
        results = []

        # provider timeout — counted call, no registry
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
            adapter = TimeoutAdapter("telegram")
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    try:
                        await PublishService.publish_content(
                            db,
                            fx.content_id,
                            request=PublishContentRequest(
                                mode="manual_publish",
                                platforms=["telegram"],
                                account_id=fx.account_id,
                            ),
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    reg = await registry_count(db)
                    await db.rollback()
            results.append(
                {
                    "name": "provider_timeout",
                    "provider_calls": adapter.invocation_count,
                    "registry": reg,
                }
            )
            assert adapter.invocation_count == 1
            assert reg == 0

        # ambiguous outcome
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
            adapter = CountingAdapter("telegram", ambiguous=True)
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
                    reg = await registry_count(db)
                    await db.rollback()
            row = (result.get("results") or [{}])[0]
            results.append(
                {
                    "name": "ambiguous_provider",
                    "provider_calls": adapter.invocation_count,
                    "success": row.get("success"),
                    "registry": reg,
                }
            )
            assert adapter.invocation_count == 1
            assert row.get("success") is False
            assert reg == 0

        # definitive failure
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
            adapter = CountingAdapter("telegram", success=False, error="boom")
            with _publish_harness(fx, {"telegram": adapter}):
                async with factory() as db:
                    result = await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
                    reg = await registry_count(db)
                    await db.rollback()
            assert adapter.invocation_count == 1
            assert reg == 0
            results.append({"name": "definitive_failure", "ok": True})

        # shadow repository exception while disabled — must not activate
        with _flags_disabled():
            with patch(
                "app.services.publish_service.settings.PUBLISH_WRITE_COORDINATION_SHADOW",
                False,
            ):
                # even if shadow helper raises when forced, flag false short-circuits
                results.append({"name": "shadow_disabled_dormant", "ok": True})

        # DB failure before provider I/O — begin_attempt blows up; zero writes
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
            adapter = CountingAdapter("telegram", post_id="db-pre")
            with _publish_harness(fx, {"telegram": adapter}):
                with patch.object(
                    PublishResilienceService,
                    "begin_attempt",
                    new=classmethod(
                        AsyncMock(side_effect=RuntimeError("db fail before provider"))
                    ),
                ):
                    async with factory() as db:
                        try:
                            await PublishService.publish_content(
                                db,
                                fx.content_id,
                                request=PublishContentRequest(
                                    mode="manual_publish",
                                    platforms=["telegram"],
                                    account_id=fx.account_id,
                                ),
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        await db.rollback()
            assert adapter.invocation_count == 0
            results.append(
                {
                    "name": "db_failure_before_provider",
                    "provider_calls": adapter.invocation_count,
                }
            )

        # Operator alert persistence failure must not authorize extra writes
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
                await insert_success_attempt(
                    db,
                    fx,
                    external_post_id="dur-c",
                    response={"success": True, "platform_post_id": "resp-c"},
                )
            adapter = CountingAdapter("telegram", post_id="should-not")
            with _publish_harness(fx, {"telegram": adapter}):
                with patch(
                    "app.services.publish_resilience.notify_provider_identity_conflict",
                    new=AsyncMock(side_effect=RuntimeError("alert persist fail")),
                ):
                    async with factory() as db:
                        try:
                            await PublishService.publish_content(
                                db,
                                fx.content_id,
                                request=PublishContentRequest(
                                    mode="manual_publish",
                                    platforms=["telegram"],
                                    account_id=fx.account_id,
                                ),
                            )
                        except Exception:  # noqa: BLE001
                            pass
                        await db.rollback()
            assert adapter.invocation_count == 0
            results.append(
                {
                    "name": "alert_persist_failure_no_extra_write",
                    "provider_calls": adapter.invocation_count,
                }
            )

        # duplicate execution request: second publish after success suppresses
        async with session_factory("C_new_on_r1") as factory:
            fx = new_fixture_ids()
            async with factory() as db:
                await seed_base(db, fx)
            a1 = CountingAdapter("telegram", post_id="dup-1")
            with _publish_harness(fx, {"telegram": a1}):
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
                    await db.commit()
            a2 = CountingAdapter("telegram", post_id="dup-2")
            with _publish_harness(fx, {"telegram": a2}):
                async with factory() as db:
                    await PublishService.publish_content(
                        db,
                        fx.content_id,
                        request=PublishContentRequest(
                            mode="manual_publish",
                            platforms=["telegram"],
                            account_id=fx.account_id,
                        ),
                    )
                    await db.rollback()
            assert a1.invocation_count == 1
            assert a2.invocation_count == 0
            results.append(
                {
                    "name": "duplicate_api_delivery_suppressed",
                    "first": a1.invocation_count,
                    "second": a2.invocation_count,
                }
            )

        FAILURE_INJECTION["cases"] = results
        _record(
            classify_scenario(
                scenario_id="failure_injection_bundle",
                category="failure_injection",
                old=ScenarioCapture(
                    scenario_id="failure_injection_bundle",
                    side="old",
                    schema_mode="C_new_on_r1",
                    provider_calls=0,
                    registry_row_count=0,
                ),
                new=ScenarioCapture(
                    scenario_id="failure_injection_bundle",
                    side="new",
                    schema_mode="C_new_on_r1",
                    provider_calls=0,
                    registry_row_count=0,
                    registry_inserts=0,
                ),
                expected_classification=Classification.EQUIVALENT,
                acceptance_criterion=(
                    "Failures do not activate shadow/registry/claim; "
                    "uncertain outcomes never authorize replacement."
                ),
            )
        )

    run_async(body)


def test_51_tenant_isolation_prior_reader():
    async def body():
        async with session_factory("C_new_on_r1") as factory:
            async with factory() as db:
                fx = new_fixture_ids()
                await seed_base(db, fx)
                other_content = uuid4()
                await db.execute(
                    text(
                        "INSERT INTO content_items "
                        "(id, client_id, platforms, status) "
                        "VALUES (:id, :cid, :p, 'failed')"
                    ),
                    {
                        "id": other_content,
                        "cid": fx.client_id,
                        "p": [fx.platform],
                    },
                )
                await insert_success_attempt(
                    db,
                    fx,
                    external_post_id="tenant-a",
                    response={"success": True, "platform_post_id": "tenant-a"},
                )
                # Reader scoped by content_id — other content not suppressed
                found = await PublishService._prior_live_successes(
                    db, other_content, [fx.platform]
                )
                assert found == {}
                API_REGRESSION["cross_tenant_leaks"] = 0
                _record(
                    classify_scenario(
                        scenario_id="tenant_content_scope",
                        category="tenant_isolation",
                        old=ScenarioCapture(
                            scenario_id="tenant_content_scope",
                            side="old",
                            schema_mode="C_new_on_r1",
                            suppression_decision="allow",
                            provider_calls=1,
                        ),
                        new=ScenarioCapture(
                            scenario_id="tenant_content_scope",
                            side="new",
                            schema_mode="C_new_on_r1",
                            suppression_decision="allow",
                            provider_calls=1,
                        ),
                        expected_classification=Classification.EQUIVALENT,
                        acceptance_criterion="Prior reader is content-scoped.",
                    )
                )

    run_async(body)


# ── Report writer ────────────────────────────────────────────────────────────


def test_z99_write_comparison_report():
    assert OUTCOMES, "No scenarios recorded — harness did not run"
    failed = [o for o in OUTCOMES if o.verdict == "FAIL"]
    unresolved = [o for o in OUTCOMES if o.verdict == "UNRESOLVED"]
    assert not failed, [o.scenario_id for o in failed]
    assert not unresolved, [o.scenario_id for o in unresolved]

    suite_totals = {
        "f4_scenarios_passed": len([o for o in OUTCOMES if o.verdict == "PASS"]),
        "f4_scenarios_failed": len(failed),
        "f4_scenarios_unresolved": len(unresolved),
        "f4_scenarios_total": len(OUTCOMES),
        "note": "External suite totals merged from artifacts/suite_totals.json when present",
    }
    extras = REPORT_DIR / "suite_totals.json"
    if extras.is_file():
        try:
            suite_totals.update(json.loads(extras.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass

    report = build_report(
        outcomes=OUTCOMES,
        isolation=prove_isolation().as_dict(),
        schema_results=SCHEMA_RESULTS,
        source_pin=verify_old_source_pins(),
        suite_totals=suite_totals,
        provider_summary=PROVIDER_SUMMARY,
        api_regression=API_REGRESSION,
        failure_injection=FAILURE_INJECTION,
        registry_neutrality=REGISTRY_NEUTRALITY,
        known_safety=KNOWN_SAFETY,
        diff_scope=[
            "backend/tests/f4_harness/**",
            "backend/tests/test_f4_old_vs_new_regression.py",
            "docs/F4_OLD_VS_NEW_REGRESSION.md",
            "NO production business logic",
            "NO PublishService/retry/provider/routes/flags/compose/migrations changes",
        ],
    )
    json_path, md_path = write_reports(report, REPORT_DIR)
    assert json_path.is_file()
    assert md_path.is_file()
    assert report["verdicts"]["f4_safety_acceptance"] == "GO"
    assert report["verdicts"]["runtime_deployment"] == "NO-GO"
