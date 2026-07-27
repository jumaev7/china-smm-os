"""Offline contract tests for Social Listening Phase 3 live Meta adapters.

No live Graph HTTP. Uses fixtures under providers/fixtures/meta/ and mocks
graph_get. Also asserts ordinary mention/analytics/review/Executive Copilot
read paths make zero Graph API calls.

Run from backend/:  python scripts/test_listening_live_sources.py
"""
from __future__ import annotations

import asyncio
import inspect
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

FIXTURES = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "listening"
    / "providers"
    / "fixtures"
    / "meta"
)


def _load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    return asyncio.run(_run(record, failures))


async def _two_session_lock_tests(record) -> None:
    """Prove exclusive committed lease semantics across two AsyncSessions."""
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4

    from sqlalchemy import delete, select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from app.core.database import engine, ensure_listening_schema
    from app.models.listening import TenantListeningProject, TenantListeningSource
    from app.models.tenant import Tenant
    from app.services.listening.live_sync_service import (
        release_source_lock,
        try_acquire_source_lock,
    )

    await ensure_listening_schema()
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tenant_id = uuid4()
    project_id = uuid4()
    source_id = uuid4()
    now = datetime.now(timezone.utc)

    async with Session() as setup:
        setup.add(
            Tenant(
                id=tenant_id,
                company_name=f"lock-test-{tenant_id.hex[:8]}",
            )
        )
        await setup.flush()
        setup.add(
            TenantListeningProject(
                id=project_id,
                tenant_id=tenant_id,
                name="lock-test-project",
                status="active",
            )
        )
        await setup.flush()
        setup.add(
            TenantListeningSource(
                id=source_id,
                tenant_id=tenant_id,
                project_id=project_id,
                source_type="facebook_page_comments",
                source_key="lock-test",
                display_name="lock-test",
                is_enabled=True,
                capability_status="live",
                freshness_status="unavailable",
                health_status="unknown",
            )
        )
        await setup.commit()

    try:
        async with Session() as s1, Session() as s2:
            src1 = (
                await s1.execute(
                    select(TenantListeningSource).where(TenantListeningSource.id == source_id)
                )
            ).scalar_one()
            src2 = (
                await s2.execute(
                    select(TenantListeningSource).where(TenantListeningSource.id == source_id)
                )
            ).scalar_one()

            ok1 = await try_acquire_source_lock(
                s1, src1, owner="worker-a", now=now, commit=True,
            )
            ok2 = await try_acquire_source_lock(
                s2, src2, owner="worker-b", now=now, commit=True,
            )
            record(
                "two_session_exactly_one_acquires",
                ok1 is True and ok2 is False,
                f"a={ok1} b={ok2}",
            )
            record(
                "two_session_second_already_running",
                ok1 and not ok2,
                "second worker must fail acquire → already_running path",
            )

            # Stale / expired lock recovery
            async with Session() as s_stale:
                stale_src = (
                    await s_stale.execute(
                        select(TenantListeningSource).where(
                            TenantListeningSource.id == source_id
                        )
                    )
                ).scalar_one()
                stale_src.lock_owner = "crashed-worker"
                stale_src.lock_expires_at = now - timedelta(seconds=30)
                await s_stale.commit()

            async with Session() as s_rec:
                rec_src = (
                    await s_rec.execute(
                        select(TenantListeningSource).where(
                            TenantListeningSource.id == source_id
                        )
                    )
                ).scalar_one()
                recovered = await try_acquire_source_lock(
                    s_rec,
                    rec_src,
                    owner="worker-recover",
                    now=now,
                    commit=True,
                )
                record("two_session_stale_lock_recoverable", recovered is True)

            # One run cannot release another run's lock (lease still held by recover).
            async with Session() as s_check:
                held = (
                    await s_check.execute(
                        select(TenantListeningSource).where(
                            TenantListeningSource.id == source_id
                        )
                    )
                ).scalar_one()
                record(
                    "two_session_lease_persisted_after_acquire",
                    held.lock_owner == "worker-recover" and held.lock_expires_at is not None,
                    f"owner={held.lock_owner}",
                )

            async with Session() as s_other, Session() as s_owner:
                other = (
                    await s_other.execute(
                        select(TenantListeningSource).where(
                            TenantListeningSource.id == source_id
                        )
                    )
                ).scalar_one()
                owner_row = (
                    await s_owner.execute(
                        select(TenantListeningSource).where(
                            TenantListeningSource.id == source_id
                        )
                    )
                ).scalar_one()
                foreign_release = await release_source_lock(
                    s_other, other, owner="owner-other", commit=True,
                )
                await s_owner.refresh(owner_row)
                record(
                    "two_session_cannot_release_foreign_lock",
                    foreign_release is False and owner_row.lock_owner == "worker-recover",
                    f"released={foreign_release} owner={owner_row.lock_owner}",
                )
                own_release = await release_source_lock(
                    s_owner, owner_row, owner="worker-recover", commit=True,
                )
                record("two_session_owner_can_release", own_release is True)
    finally:
        async with Session() as cleanup:
            await cleanup.execute(
                delete(TenantListeningSource).where(TenantListeningSource.id == source_id)
            )
            await cleanup.execute(
                delete(TenantListeningProject).where(TenantListeningProject.id == project_id)
            )
            await cleanup.execute(delete(Tenant).where(Tenant.id == tenant_id))
            await cleanup.commit()


async def _run(record, failures: list[str]) -> int:
    from app.services.listening.live_sync_service import scrub_config
    from app.services.listening.providers import get_adapter, list_source_capabilities
    from app.services.listening.providers.facebook_page_comments import (
        FacebookPageCommentsAdapter,
        _comment_to_observation,
    )
    from app.services.listening.providers.facebook_page_mentions import (
        FacebookPageMentionsAdapter,
        _tagged_to_observation,
    )
    from app.services.listening.providers.meta_capability_matrix import (
        ACCESS_LAYER_NOTES,
        CAPABILITY_MATRIX,
        SANITIZED_HEALTH_CODES,
    )
    from app.services.listening.providers.meta_errors import (
        classify_meta_error,
        public_failure_summary,
        sanitize_error_text,
    )
    from app.services.listening.providers import meta_graph_read as mgr

    # --- Capabilities stay separate ---
    comments_caps = FacebookPageCommentsAdapter().capabilities()
    mentions_caps = FacebookPageMentionsAdapter().capabilities()
    record(
        "capabilities_not_grouped",
        comments_caps.owned_content_comments
        and not comments_caps.direct_account_mentions
        and mentions_caps.direct_account_mentions
        and not mentions_caps.owned_content_comments,
    )
    record(
        "matrix_both_shipped_independently",
        CAPABILITY_MATRIX["owned_content_comments"]["shipped"]
        and CAPABILITY_MATRIX["direct_account_mentions"]["shipped"]
        and CAPABILITY_MATRIX["owned_content_comments"]["endpoint_path"]
        != CAPABILITY_MATRIX["direct_account_mentions"]["endpoint_path"],
    )
    record(
        "access_layers_documented",
        set(ACCESS_LAYER_NOTES)
        == {
            "permission_granted_to_token",
            "advanced_access_or_app_review",
            "page_task_authorization",
            "development_mode_availability",
            "production_availability",
        },
    )
    record(
        "production_requires_app_review",
        all(
            CAPABILITY_MATRIX[k]["production_requires_app_review"]
            and CAPABILITY_MATRIX[k]["production_requires_advanced_access"]
            for k in ("owned_content_comments", "direct_account_mentions")
        ),
    )

    # --- Fixture presence ---
    required_fixtures = [
        "multiple_pages.json",
        "multi_page_comment_pagination.json",
        "replies_unsupported.json",
        "edited_comment.json",
        "missing_published_timestamp.json",
        "deleted_unavailable_content.json",
        "empty_successful_response.json",
        "duplicate_pagination_item.json",
        "rate_limit.json",
        "expired_token.json",
        "missing_permission.json",
        "partial_page_failure.json",
        "checkpoint_retry.json",
        "insufficient_app_access.json",
        "page_not_authorized.json",
    ]
    for name in required_fixtures:
        record(f"fixture_{name}", (FIXTURES / name).is_file())

    multi = _load("multiple_pages.json")
    record("fixture_multiple_pages", len(multi.get("pages") or []) >= 2)

    replies = _load("replies_unsupported.json")
    record(
        "replies_capability_false",
        replies.get("replies_supported") is False and comments_caps.replies is False,
    )

    # --- Error classification (sanitized, no payload leak) ---
    for fname in (
        "rate_limit.json",
        "expired_token.json",
        "missing_permission.json",
        "insufficient_app_access.json",
        "page_not_authorized.json",
    ):
        fx = _load(fname)
        err = classify_meta_error(
            http_status=fx["http_status"],
            payload=fx["payload"],
        )
        record(
            f"classify_{fx['expected_code']}",
            err.code == fx["expected_code"],
            f"got={err.code}",
        )
        record(
            f"no_raw_payload_{fx['expected_code']}",
            "OAuthException" not in str(err)
            and "GraphMethodException" not in str(err)
            and "(#" not in str(err)
            and "EAA" not in str(err)
            and err.code == fx["expected_code"],
            str(err),
        )

    leaked = sanitize_error_text(
        "access_token=EAABsupersecrettokenvalue1234567890abcdefghijklmnop&foo=1"
    )
    record("sanitize_redacts_token", "EAABsuper" not in leaked and "REDACTED" in leaked)
    record(
        "public_summary_stable",
        "rate limit" in public_failure_summary("rate_limited").lower(),
    )

    # --- Observation mapping edge cases ---
    edited = _load("edited_comment.json")
    obs1 = _comment_to_observation(edited["first_fetch"], page_id="111", post_id="p1")
    obs2 = _comment_to_observation(edited["second_fetch"], page_id="111", post_id="p1")
    record(
        "edited_comment_same_id",
        obs1.provider_external_id == obs2.provider_external_id == "comment_edit_1",
    )
    record("edited_comment_text_changes", obs1.content_text != obs2.content_text)

    missing_ts = _load("missing_published_timestamp.json")
    obs_ts = _comment_to_observation(missing_ts["comment"], page_id="111", post_id="p1")
    record("missing_published_timestamp_null", obs_ts.published_at is None)

    deleted = _load("deleted_unavailable_content.json")
    record(
        "deletion_policy_non_destructive",
        deleted.get("explicit_deletion_signal") is None
        and comments_caps.deletion_signals_available is False
        and comments_caps.deletion_events is False,
    )

    empty = _load("empty_successful_response.json")
    record("empty_success_fixture", empty["comments"]["data"] == [])

    dup = _load("duplicate_pagination_item.json")
    ids = [c["id"] for c in dup["comments"]["data"]]
    record("duplicate_pagination_item_fixture", ids == ["comment_dup", "comment_dup"])

    # --- Adapter fetch with mocked Graph (empty success) ---
    adapter = FacebookPageCommentsAdapter()
    runtime = {
        "publishing_account_id": "00000000-0000-0000-0000-000000000001",
        "provider_resource_ref": "111111111111111",
        "granted_permissions": sorted(
            [
                "pages_show_list",
                "pages_read_engagement",
                "pages_read_user_content",
            ]
        ),
        "_runtime_page_access_token": "test-token-not-persisted",
    }

    async def _empty_graph(path: str, **kwargs):
        if path.endswith("/posts"):
            return {"data": []}
        if "/comments" in path:
            return {"data": []}
        if path.endswith("/tagged"):
            return {"data": []}
        return {"id": "111111111111111", "name": "Test"}

    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_empty_graph)):
        page = await adapter.fetch_observations(config=runtime, limit=10)
    record(
        "empty_successful_response",
        page.error_summary is None and page.fetched_count == 0 and page.items == [],
    )

    # Mentions empty success
    mentions = FacebookPageMentionsAdapter()
    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_empty_graph)):
        mpage = await mentions.fetch_observations(config=runtime, limit=10)
    record(
        "mentions_empty_successful_response",
        mpage.error_summary is None and mpage.fetched_count == 0,
    )

    # Duplicate items in one page → both returned; ingestion dedupe owns collapse
    call_state = {"n": 0}

    async def _dup_graph(path: str, **kwargs):
        if path.endswith("/posts"):
            return {
                "data": [{"id": "111_post_a", "message": "x", "created_time": "2026-07-01T10:00:00+0000"}]
            }
        if "/comments" in path:
            return dup["comments"]
        return {"id": "111", "name": "T"}

    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_dup_graph)):
        dpage = await adapter.fetch_observations(config=runtime, limit=10)
    record(
        "duplicate_pagination_items_fetched",
        dpage.fetched_count == 2
        and [i.provider_external_id for i in dpage.items] == ["comment_dup", "comment_dup"],
    )

    # Partial page failure
    partial = _load("partial_page_failure.json")

    async def _partial_graph(path: str, **kwargs):
        if path.endswith("/posts"):
            return partial["posts"]
        if "111_post_ok/comments" in path or path.startswith("111_post_ok"):
            return partial["comments_ok"]
        if "111_post_fail" in path:
            raise classify_meta_error(
                http_status=500,
                payload=partial["comments_fail"]["payload"],
            )
        return {"id": "111", "name": "T"}

    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_partial_graph)):
        # fetch_post_comments uses path f"{post_id}/comments"
        async def _partial_get(path: str, **kwargs):
            if path.endswith("/posts") or path == "111111111111111/posts":
                return partial["posts"]
            if path.startswith("111_post_ok"):
                return partial["comments_ok"]
            if path.startswith("111_post_fail"):
                raise classify_meta_error(
                    http_status=500,
                    payload=partial["comments_fail"]["payload"],
                )
            return {"id": "111", "name": "T"}

        with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_partial_get)):
            ppage = await adapter.fetch_observations(config=runtime, limit=10)
    record(
        "partial_page_failure_keeps_prior",
        ppage.fetched_count >= 1
        and ppage.error_summary == "provider_unavailable"
        and any(i.provider_external_id == "c_ok" for i in ppage.items),
        f"fetched={ppage.fetched_count} err={ppage.error_summary} cursor={ppage.next_cursor}",
    )
    checkpoint = _load("checkpoint_retry.json")
    record(
        "checkpoint_retry_fixture",
        checkpoint["resume_policy"] == "do_not_advance_checkpoint_on_hard_fail",
    )
    if ppage.next_cursor:
        import json as _json
        state = _json.loads(ppage.next_cursor)
        record(
            "checkpoint_points_at_failed_post",
            state.get("post_id") == "111_post_fail",
            str(state),
        )
    else:
        record("checkpoint_points_at_failed_post", False, "missing next_cursor")

    # Rate limit / expired / missing permission surface as error_summary codes
    async def _rate(path: str, **kwargs):
        raise classify_meta_error(
            http_status=429,
            payload=_load("rate_limit.json")["payload"],
        )

    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_rate)):
        rpage = await adapter.fetch_observations(config=runtime, limit=5)
    record("rate_limited_fetch", rpage.error_summary == "rate_limited" and rpage.fetched_count == 0)

    async def _expired(path: str, **kwargs):
        raise classify_meta_error(
            http_status=401,
            payload=_load("expired_token.json")["payload"],
        )

    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_expired)):
        epage = await adapter.fetch_observations(config=runtime, limit=5)
    record(
        "expired_token_fetch",
        epage.error_summary == "token_expired_or_revoked",
    )

    async def _missing(path: str, **kwargs):
        raise classify_meta_error(
            http_status=403,
            payload=_load("missing_permission.json")["payload"],
        )

    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_missing)):
        mpage2 = await adapter.fetch_observations(config=runtime, limit=5)
    record("missing_permission_fetch", mpage2.error_summary == "missing_scope")

    # --- Token scrubbing ---
    dirty = {
        **runtime,
        "access_token": "should-not-persist",
        "page_access_token": "nope",
    }
    clean = scrub_config(dirty)
    record(
        "scrub_config_strips_tokens",
        "_runtime_page_access_token" not in clean
        and "access_token" not in clean
        and "page_access_token" not in clean
        and clean.get("provider_resource_ref") == "111111111111111",
    )

    # --- ensure_listening_schema create-only ---
    from app.core import database as db_mod

    ensure_src = inspect.getsource(db_mod._ensure_listening_tables)
    record("ensure_create_only_no_alter", "ALTER TABLE" not in ensure_src.upper())
    record(
        "ensure_fresh_cursors_1000",
        "cursor_before VARCHAR(1000)" in ensure_src
        and "cursor_after VARCHAR(1000)" in ensure_src,
    )
    record(
        "ensure_includes_live_source_columns",
        "integration_id" in ensure_src
        and "lock_owner" in ensure_src
        and "last_checkpoint" in ensure_src,
    )

    # Migration retains ALTER for upgrades (must not be removed merely for helper tests)
    mig = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260916_listening_live_sources.py"
    )
    mig_text = mig.read_text(encoding="utf-8") if mig.is_file() else ""
    record(
        "migration_retains_alter_for_upgrades",
        mig.is_file() and "op.add_column" in mig_text and "op.alter_column" in mig_text,
    )

    # --- Atomic lock uses SQL UPDATE (not in-memory) ---
    from app.services.listening import live_sync_service as lss

    lock_src = inspect.getsource(lss.try_acquire_source_lock)
    release_src = inspect.getsource(lss.release_source_lock)
    sync_src = inspect.getsource(lss.sync_live_source)
    record(
        "source_lock_database_backed",
        "UPDATE tenant_listening_sources" in lock_src
        and "asyncio.Lock" not in lock_src
        and "threading" not in lock_src,
    )
    record(
        "source_lock_commits_before_work",
        "commit=True" in sync_src
        and "already_running" in sync_src
        and "SourceAlreadyRunningError" in sync_src,
    )
    record(
        "source_lock_release_owner_matched",
        "lock_owner = :owner" in release_src and "AND lock_owner = :owner" in release_src,
    )
    record(
        "source_lock_lifecycle_documented",
        "Transaction boundaries" in (lock_src or "")
        and "Stale-lock recovery" in (lock_src or ""),
    )

    # --- Credential ownership / token hygiene ---
    from app.services.listening.live_credentials import LiveCredentialBundle
    from app.services.listening import live_credentials as lc_mod
    from uuid import uuid4

    cred_src = inspect.getsource(lc_mod.resolve_facebook_page_credentials)
    record(
        "credentials_tenant_filtered",
        "PublishingAccount.tenant_id == tenant_id" in cred_src,
    )
    record(
        "credentials_page_binding_checked",
        "expected_page_id" in cred_src and "does not match" in cred_src,
    )
    record(
        "credentials_missing_vs_revoked",
        '"missing_credentials"' in cred_src
        and '"token_expired_or_revoked"' in cred_src
        and "access_token_encrypted" in cred_src,
    )
    bundle = LiveCredentialBundle(
        publishing_account_id=uuid4(),
        platform="facebook",
        status="connected",
        page_id="111",
        page_name="Test",
        granted_permissions=["pages_show_list"],
        page_access_token="SUPER_SECRET_PAGE_TOKEN_VALUE_SHOULD_NOT_LEAK",
    )
    record(
        "credential_repr_redacts_token",
        "SUPER_SECRET" not in repr(bundle) and "***" in repr(bundle),
    )
    overlay = bundle.public_config_overlay()
    record(
        "credential_overlay_has_no_token",
        "token" not in str(overlay).lower()
        and "SUPER_SECRET" not in str(overlay),
    )
    analytics_mod = __import__(
        "app.services.listening.analytics.intelligence_service",
        fromlist=["ListeningIntelligenceService"],
    )
    analytics_src = inspect.getsource(analytics_mod)
    record(
        "analytics_no_publishing_coupling",
        "publishing_account" not in analytics_src.lower()
        and "live_credentials" not in analytics_src
        and "decrypt_token" not in analytics_src,
    )

    # --- Capability probe contracts ---
    probe_src = inspect.getsource(mgr.probe_capability)
    record(
        "probe_bounded_timeout",
        "timeout" in probe_src and "15.0" in probe_src,
    )
    record(
        "probe_endpoint_access_limitation_explicit",
        "endpoint access" in probe_src.lower()
        and "not general market coverage" in probe_src.lower(),
    )
    record(
        "probe_get_only_no_mutation",
        "graph_get" in inspect.getsource(mgr)
        and "client.post" not in inspect.getsource(mgr)
        and "client.delete" not in inspect.getsource(mgr)
        and "client.put" not in inspect.getsource(mgr),
    )
    # health_check is the probe entry; validate_configuration is offline scope checks
    comments_hc = inspect.getsource(FacebookPageCommentsAdapter.health_check)
    comments_val = inspect.getsource(FacebookPageCommentsAdapter.validate_configuration)
    record(
        "probe_only_on_health_not_validate",
        "probe_capability" in comments_hc and "probe_capability" not in comments_val,
    )

    # --- Two-session atomic lock lifecycle (real Postgres) ---
    await _two_session_lock_tests(record)

    # --- Zero Graph calls for ordinary read paths ---
    graph_calls = {"n": 0}

    async def _forbid_graph(*args, **kwargs):
        graph_calls["n"] += 1
        raise AssertionError("Graph API must not be called from ordinary read paths")

    read_modules = [
        "app.services.listening.read_service",
        "app.services.listening.review_service",
        "app.services.listening.executive_read",
        "app.services.listening.analytics.intelligence_service",
    ]
    # Static import graph: these modules must not import meta_graph_read / live_sync for reads
    for mod_name in read_modules:
        mod = __import__(mod_name, fromlist=["*"])
        src = inspect.getsource(mod)
        record(
            f"zero_graph_import_{mod_name.rsplit('.', 1)[-1]}",
            "meta_graph_read" not in src
            and "live_sync_service" not in src
            and "graph_get" not in src
            and "httpx" not in src,
        )

    with patch.object(mgr, "graph_get", new=AsyncMock(side_effect=_forbid_graph)):
        # Capability listing must be static — no Graph.
        caps_list = list_source_capabilities()
        record("capabilities_list_no_graph", graph_calls["n"] == 0 and len(caps_list) >= 4)

        # Tagged observation mapping without Graph
        tagged = _tagged_to_observation(
            {
                "id": "tagged_1",
                "message": "tagged post",
                "created_time": "2026-07-01T10:00:00+0000",
                "from": {"id": "u", "name": "X"},
            },
            page_id="111",
        )
        record(
            "tagged_mapping_offline",
            tagged.provider_external_id == "tagged_1" and graph_calls["n"] == 0,
        )

    # Pagination fixture sanity
    pag = _load("multi_page_comment_pagination.json")
    record(
        "multi_page_comment_pagination_fixture",
        "POSTS_CURSOR_2" in str(pag["posts_page_1"])
        and len(pag["comments_post_a_page_1"]["data"]) == 1
        and len(pag["comments_post_a_page_2"]["data"]) == 1,
    )

    # Official docs present for shipped capabilities
    for key in ("owned_content_comments", "direct_account_mentions"):
        docs = CAPABILITY_MATRIX[key]["official_docs"]
        record(
            f"official_docs_{key}",
            isinstance(docs, tuple)
            and len(docs) >= 2
            and all(str(u).startswith("https://developers.facebook.com/") for u in docs),
        )

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
