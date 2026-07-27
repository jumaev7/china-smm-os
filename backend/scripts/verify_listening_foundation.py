"""Domain verification for Social Listening Phase 1 observed-mentions foundation.

Covers dedupe, matching, pause behavior, review audit, tenant isolation,
malformed-item tolerance, and no-provider-write guarantees.

Run from backend/:  python scripts/verify_listening_foundation.py
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


failures: list[str] = []


def record(check_id: str, ok: bool, detail: str = "") -> None:
    print(("OK" if ok else "FAIL") + f" {check_id}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(f"{check_id}: {detail}")


async def _run() -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal, ensure_listening_schema
    from app.models.listening import (
        TenantMentionMatch,
        TenantMentionReview,
        TenantObservedMention,
    )
    from app.models.tenant import Tenant, TenantUser
    from app.services.listening.dedupe import build_content_fingerprint, build_dedupe_key
    from app.core.config import settings
    from app.services.listening.dedupe import canonicalize_url
    from app.services.listening.errors import (
        FixtureUnavailableError,
        ProjectNotFoundError,
        ProjectPausedError,
        SubjectNotFoundError,
    )
    from app.services.listening.ingestion_service import (
        fixture_ingest_allowed,
        ingest_observations,
        projects_eligible_for_scheduled_ingestion,
        run_fixture_ingest,
        run_manual_import,
    )
    from app.services.listening.matching import find_boundary_match, match_mention_against_queries
    from app.services.listening.project_service import (
        create_project,
        create_query,
        create_subject,
        update_project,
        update_query,
    )
    from app.services.listening.providers import get_adapter, list_source_capabilities
    from app.services.listening.providers.base import ListeningSourceAdapter
    from app.services.listening.review_service import set_review_state

    await ensure_listening_schema()

    # --- pure functions ---
    fp1 = build_content_fingerprint(
        source_type="manual_import",
        provider_account_ref="manual",
        author_display="alice",
        content_text="Hello World",
        published_at=None,
        canonical_url="https://Example.com/a?utm_source=x",
    )
    fp2 = build_content_fingerprint(
        source_type="manual_import",
        provider_account_ref="manual",
        author_display="alice",
        content_text="Hello   World",
        published_at=None,
        canonical_url="https://example.com/a",
    )
    record("fingerprint_deterministic", fp1 == fp2, fp1[:16])

    key_ext = build_dedupe_key(
        source_type="manual_import",
        provider_account_ref="acct",
        provider_external_id="ext-1",
        canonical_url="https://example.com/x",
        content_fingerprint=fp1,
    )
    record("dedupe_prefers_external_id", key_ext.startswith("ext:"), key_ext)

    hit = find_boundary_match("I like Acme products", "Acme")
    record("boundary_match_positive", hit is not None)

    false_pos = find_boundary_match("I like Pacemaker devices", "Acme")
    record("boundary_match_rejects_substring", false_pos is None)

    class _Q:
        def __init__(self):
            self.id = uuid4()
            self.is_enabled = True
            self.include_terms_json = ["Acme"]
            self.exclude_terms_json = ["spam"]
            self.source_filters_json = None
            self.language_filters_json = None
            self.subject_id = None

    evidence = match_mention_against_queries(
        content_text="Great Acme launch today",
        canonical_url=None,
        author_display=None,
        language="en",
        source_type="manual_import",
        queries=[_Q()],
        subjects_by_id={},
    )
    record("matching_retains_evidence", len(evidence) == 1 and evidence[0].evidence_excerpt is not None)

    excluded = match_mention_against_queries(
        content_text="Acme spam offer",
        canonical_url=None,
        author_display=None,
        language="en",
        source_type="manual_import",
        queries=[_Q()],
        subjects_by_id={},
    )
    record("excluded_terms_suppress_match", excluded == [])

    record("paused_not_scheduled", projects_eligible_for_scheduled_ingestion("paused") is False)
    record("active_scheduled", projects_eligible_for_scheduled_ingestion("active") is True)

    record(
        "canonicalize_rejects_javascript",
        canonicalize_url("javascript:alert(1)") is None,
    )
    record(
        "canonicalize_rejects_data",
        canonicalize_url("data:text/html;base64,xx") is None,
    )
    record(
        "canonicalize_accepts_https",
        canonicalize_url("https://Example.com/a?utm_source=x") == "https://example.com/a",
    )
    record(
        "fixture_gate_matches_env",
        fixture_ingest_allowed() == ((settings.APP_ENV or "").strip().lower() not in {"production", "prod"}),
    )

    # Adapter surface must not expose mutation methods.
    adapter = get_adapter("manual_import")
    mutation_names = [
        name for name, _ in inspect.getmembers(adapter, predicate=inspect.ismethod)
        if name.startswith(("publish", "reply", "comment", "like", "follow", "block", "send", "delete", "mutate"))
    ]
    record("adapter_no_mutation_methods", mutation_names == [], str(mutation_names))
    record("adapter_is_listening_source", isinstance(adapter, ListeningSourceAdapter))

    caps = list_source_capabilities()
    record(
        "capabilities_honest",
        any(c.source_type == "manual_import" and c.capability_status == "import_only" for c in caps)
        and any(c.capability_status == "unsupported" for c in caps),
    )

    # --- DB-backed flows ---
    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"Listening A {uuid4().hex[:8]}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Listening B {uuid4().hex[:8]}", status="active", plan="trial")
        db.add_all([tenant_a, tenant_b])
        await db.flush()

        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"owner-a-{uuid4().hex[:8]}@example.com",
            password_hash="x",
            role="owner",
            status="active",
        )
        db.add(user_a)
        await db.flush()

        project = await create_project(
            db, tenant_id=tenant_a.id, name="Brand Watch", created_by_user_id=user_a.id,
        )
        subject = await create_subject(
            db,
            tenant_id=tenant_a.id,
            project_id=project.id,
            subject_type="own_brand",
            canonical_name="Acme",
            aliases=["Acme Co"],
        )
        await create_query(
            db,
            tenant_id=tenant_a.id,
            project_id=project.id,
            name="Acme watch",
            include_terms=["Acme"],
            exclude_terms=["spam"],
            subject_id=subject.id,
            created_by_user_id=user_a.id,
        )

        items = [
            {
                "provider_external_id": "ext-same",
                "content_text": "Acme opened a new store",
                "author_display": "watcher",
                "language": "en",
                "canonical_url": "https://example.com/posts/1",
                "published_at": "2026-07-01T10:00:00+00:00",
            },
            {
                "provider_external_id": "ext-same",
                "content_text": "Acme opened a new store",
                "author_display": "watcher",
                "language": "en",
                "canonical_url": "https://example.com/posts/1",
                "published_at": "2026-07-01T10:00:00+00:00",
            },
            {
                # malformed — missing identity fields
                "author_display": "nobody",
            },
            {
                "provider_external_id": "ext-edit",
                "content_text": "Acme Co shipping update",
                "author_display": "editor",
                "language": "en",
            },
        ]
        run1 = await run_manual_import(
            db, tenant_id=tenant_a.id, project_id=project.id, items=items, created_by_user_id=user_a.id,
        )
        record("ingest_partial_or_success", run1.status in {"succeeded", "partial"}, run1.status)
        record(
            "ingest_dedupes_same_external_id",
            run1.created_count == 2 and run1.duplicate_count >= 1,
            f"created={run1.created_count} dup={run1.duplicate_count} rej={run1.rejected_count} err={run1.error_count}",
        )
        record("malformed_rejected_not_fatal", run1.rejected_count >= 1 and run1.status != "failed",
               f"rejected={run1.rejected_count}")

        mention_count = (
            await db.execute(
                select(func.count()).select_from(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_a.id,
                )
            )
        ).scalar_one()
        record("mentions_created", int(mention_count) == 2, str(mention_count))

        # Re-ingest identical external id → preserve first_observed_at, advance last_observed_at
        first = (
            await db.execute(
                select(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_a.id,
                    TenantObservedMention.provider_external_id == "ext-same",
                )
            )
        ).scalar_one()
        first_observed = first.first_observed_at
        await asyncio.sleep(0.01)
        run2 = await run_manual_import(
            db,
            tenant_id=tenant_a.id,
            project_id=project.id,
            items=[items[0]],
            created_by_user_id=user_a.id,
        )
        await db.refresh(first)
        record("reingest_idempotent", run2.created_count == 0, f"created={run2.created_count}")
        record("first_observed_preserved", first.first_observed_at == first_observed)
        record("last_observed_advanced", first.last_observed_at >= first_observed)

        # Edited content updates fingerprint fields
        await run_manual_import(
            db,
            tenant_id=tenant_a.id,
            project_id=project.id,
            items=[{
                "provider_external_id": "ext-edit",
                "content_text": "Acme Co shipping update — revised",
                "author_display": "editor",
                "language": "en",
            }],
            created_by_user_id=user_a.id,
        )
        edited = (
            await db.execute(
                select(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_a.id,
                    TenantObservedMention.provider_external_id == "ext-edit",
                )
            )
        ).scalar_one()
        record("edited_content_updated", "revised" in (edited.content_text or ""))

        # Unknown published_at stays None
        await run_manual_import(
            db,
            tenant_id=tenant_a.id,
            project_id=project.id,
            items=[{
                "provider_external_id": "ext-unknown-time",
                "content_text": "Acme without published_at",
                "language": "en",
            }],
            created_by_user_id=user_a.id,
        )
        unk = (
            await db.execute(
                select(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_a.id,
                    TenantObservedMention.provider_external_id == "ext-unknown-time",
                )
            )
        ).scalar_one()
        record("unknown_published_at_explicit", unk.published_at is None)

        # Alias matching + match uniqueness
        match_count = (
            await db.execute(
                select(func.count()).select_from(TenantMentionMatch).where(
                    TenantMentionMatch.tenant_id == tenant_a.id,
                    TenantMentionMatch.mention_id == edited.id,
                )
            )
        ).scalar_one()
        record("matches_created", int(match_count) >= 1, str(match_count))
        await run_manual_import(
            db,
            tenant_id=tenant_a.id,
            project_id=project.id,
            items=[{
                "provider_external_id": "ext-edit",
                "content_text": "Acme Co shipping update — revised",
                "author_display": "editor",
                "language": "en",
            }],
            created_by_user_id=user_a.id,
        )
        match_count_2 = (
            await db.execute(
                select(func.count()).select_from(TenantMentionMatch).where(
                    TenantMentionMatch.tenant_id == tenant_a.id,
                    TenantMentionMatch.mention_id == edited.id,
                )
            )
        ).scalar_one()
        record("no_duplicate_matches", int(match_count_2) == int(match_count), f"{match_count}->{match_count_2}")

        # Review audit
        _, review = await set_review_state(
            db,
            tenant_id=tenant_a.id,
            mention_id=first.id,
            new_state="relevant",
            actor_user_id=user_a.id,
            note="looks real",
        )
        await db.refresh(first)
        record("review_state_updated", first.review_state == "relevant")
        record("review_audited", review.previous_state == "unreviewed" and review.new_state == "relevant")
        review_rows = (
            await db.execute(
                select(func.count()).select_from(TenantMentionReview).where(
                    TenantMentionReview.tenant_id == tenant_a.id,
                    TenantMentionReview.mention_id == first.id,
                )
            )
        ).scalar_one()
        record("review_persisted", int(review_rows) >= 1)

        # Pause: scheduled ingestion blocked; historical mentions remain
        await update_project(db, tenant_a.id, project.id, status="paused")
        paused_ok = False
        try:
            await run_fixture_ingest(db, tenant_id=tenant_a.id, project_id=project.id)
        except ProjectPausedError:
            # fixture uses allow_paused=True — so pause check is for scheduled path.
            paused_ok = False
        # Explicit scheduled-style call:
        try:
            await ingest_observations(
                db,
                tenant_id=tenant_a.id,
                project_id=project.id,
                source_type="fixture",
                trigger_type="scheduled",
                allow_paused=False,
            )
        except ProjectPausedError:
            paused_ok = True
        record("paused_blocks_scheduled_ingest", paused_ok)

        hist = (
            await db.execute(
                select(func.count()).select_from(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_a.id,
                    TenantObservedMention.project_id == project.id,
                )
            )
        ).scalar_one()
        record("history_visible_after_pause", int(hist) >= 2, str(hist))

        # Tenant isolation
        other = await create_project(db, tenant_id=tenant_b.id, name="Other")
        cross = False
        try:
            await run_manual_import(
                db,
                tenant_id=tenant_b.id,
                project_id=project.id,  # tenant A project
                items=[{"provider_external_id": "x", "content_text": "Acme"}],
            )
        except ProjectNotFoundError:
            cross = True
        record("cross_tenant_project_rejected", cross)

        # Nested subject attach must not cross projects (same tenant).
        project2 = await create_project(db, tenant_id=tenant_a.id, name="Brand Watch 2")
        subject2 = await create_subject(
            db,
            tenant_id=tenant_a.id,
            project_id=project2.id,
            subject_type="competitor",
            canonical_name="OtherCo",
        )
        q_rows = await create_query(
            db,
            tenant_id=tenant_a.id,
            project_id=project.id,
            name="Attach guard",
            include_terms=["Acme"],
            created_by_user_id=user_a.id,
        )
        cross_project_attach = False
        try:
            await update_query(
                db,
                tenant_a.id,
                q_rows.id,
                subject_id=subject2.id,
            )
        except SubjectNotFoundError:
            cross_project_attach = True
        record("cross_project_subject_attach_rejected", cross_project_attach)

        # Cross-tenant subject attach also 404s (same safe not-found).
        other_subject = await create_subject(
            db,
            tenant_id=tenant_b.id,
            project_id=other.id,
            subject_type="topic",
            canonical_name="Isolated",
        )
        cross_tenant_attach = False
        try:
            await update_query(
                db,
                tenant_a.id,
                q_rows.id,
                subject_id=other_subject.id,
            )
        except SubjectNotFoundError:
            cross_tenant_attach = True
        record("cross_tenant_subject_attach_rejected", cross_tenant_attach)

        # Mentions for tenant B must not see tenant A
        b_count = (
            await db.execute(
                select(func.count()).select_from(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_b.id,
                )
            )
        ).scalar_one()
        record("tenant_b_isolated_mentions", int(b_count) == 0, str(b_count))

        # Fixture ingest on active project after unpause
        await update_project(db, tenant_a.id, project.id, status="active")
        fix = await run_fixture_ingest(db, tenant_id=tenant_a.id, project_id=project.id)
        record("fixture_ingest_runs", fix.status in {"succeeded", "partial"}, fix.status)
        record(
            "fixture_origin_not_live",
            True,  # asserted via provenance in rows below
        )
        fixture_rows = list(
            (
                await db.execute(
                    select(TenantObservedMention).where(
                        TenantObservedMention.tenant_id == tenant_a.id,
                        TenantObservedMention.source_type == "fixture",
                    )
                )
            ).scalars().all()
        )
        record(
            "fixture_labeled_honestly",
            all(m.observation_origin == "fixture" for m in fixture_rows) and len(fixture_rows) >= 1,
            str(len(fixture_rows)),
        )
        record(
            "no_live_origin_in_phase1",
            all(m.observation_origin != "live_provider" for m in fixture_rows),
        )

        # Fatal failure must not advance checkpoint (cursor_after stays cursor_before).
        class _BoomAdapter:
            source_type = "manual_import"

            def capabilities(self):
                from app.services.listening.schemas import SourceCapabilities
                return SourceCapabilities(
                    source_type="manual_import",
                    capability_status="import_only",
                    supports_keyword_search=False,
                    supports_account_feed=False,
                    supports_historical_window=True,
                    notes="boom",
                )

            async def validate_configuration(self, config):
                return []

            async def fetch_observations(self, **kwargs):
                raise RuntimeError("provider_fetch_boom")

        import app.services.listening.ingestion_service as ingest_mod
        from app.services.listening.providers import get_adapter as _real_get

        original_get = ingest_mod.get_adapter
        ingest_mod.get_adapter = lambda _st: _BoomAdapter()  # type: ignore[assignment]
        try:
            fatal_run = await ingest_observations(
                db,
                tenant_id=tenant_a.id,
                project_id=project.id,
                source_type="manual_import",
                trigger_type="manual",
                cursor="cursor-keep",
                allow_paused=True,
            )
        finally:
            ingest_mod.get_adapter = original_get
        record("fatal_status_failed", fatal_run.status == "failed", fatal_run.status)
        record(
            "fatal_does_not_advance_checkpoint",
            fatal_run.cursor_after == fatal_run.cursor_before == "cursor-keep"
            and (fatal_run.checkpoint_json or {}).get("advanced") is False,
            str(fatal_run.checkpoint_json),
        )

        # Empty successful import is not a failure (zero mentions != error).
        empty_run = await run_manual_import(
            db, tenant_id=tenant_a.id, project_id=project.id, items=[], created_by_user_id=user_a.id,
        )
        record(
            "zero_mentions_not_failure",
            empty_run.status == "succeeded" and empty_run.error_count == 0,
            empty_run.status,
        )

        # Cleanup primary session work before concurrent sessions.
        await db.rollback()

    # Concurrent dual-session ingest must not create duplicate provider identities.
    concurrent_ext = f"ext-concurrent-{uuid4().hex[:10]}"
    async with AsyncSessionLocal() as setup_db:
        tenant_c = Tenant(id=uuid4(), company_name=f"Listening C {uuid4().hex[:8]}", status="active", plan="trial")
        setup_db.add(tenant_c)
        await setup_db.flush()
        project_c = await create_project(setup_db, tenant_id=tenant_c.id, name="Concurrent")
        await setup_db.commit()
        tenant_c_id = tenant_c.id
        project_c_id = project_c.id

    item = {
        "provider_external_id": concurrent_ext,
        "content_text": "Acme concurrent race",
        "author_display": "racer",
        "language": "en",
        "canonical_url": f"https://example.com/race/{concurrent_ext}",
    }

    async def _race_import() -> None:
        async with AsyncSessionLocal() as race_db:
            await run_manual_import(
                race_db,
                tenant_id=tenant_c_id,
                project_id=project_c_id,
                items=[item],
            )
            await race_db.commit()

    results = await asyncio.gather(_race_import(), _race_import(), return_exceptions=True)
    race_errors = [r for r in results if isinstance(r, BaseException)]
    record("concurrent_import_no_exception", race_errors == [], str(race_errors))

    async with AsyncSessionLocal() as check_db:
        race_count = (
            await check_db.execute(
                select(func.count()).select_from(TenantObservedMention).where(
                    TenantObservedMention.tenant_id == tenant_c_id,
                    TenantObservedMention.provider_external_id == concurrent_ext,
                )
            )
        ).scalar_one()
        record("concurrent_import_single_row", int(race_count) == 1, str(race_count))
        await check_db.rollback()

    # Production fixture gate (behavioral).
    previous_env = settings.APP_ENV
    settings.APP_ENV = "production"
    try:
        gated = False
        async with AsyncSessionLocal() as gate_db:
            try:
                await run_fixture_ingest(gate_db, tenant_id=tenant_c_id, project_id=project_c_id)
            except FixtureUnavailableError:
                gated = True
        record("fixture_blocked_in_production", gated)
    finally:
        settings.APP_ENV = previous_env

    # Behavioral: review + import must not invoke provider mutation capabilities.
    mutation_calls: list[str] = []

    class _SpyAdapter:
        source_type = "manual_import"

        def capabilities(self):
            from app.services.listening.schemas import SourceCapabilities
            return SourceCapabilities(
                source_type="manual_import",
                capability_status="import_only",
                supports_keyword_search=False,
                supports_account_feed=False,
                supports_historical_window=True,
                notes="spy",
            )

        async def validate_configuration(self, config):
            return []

        async def fetch_observations(self, **kwargs):
            from app.services.listening.schemas import ObservationPage, RawObservation
            return ObservationPage(
                items=[
                    RawObservation(
                        provider_external_id=f"spy-{uuid4().hex[:8]}",
                        content_text="Acme spy observe",
                        language="en",
                    )
                ],
                fetched_count=1,
            )

        async def publish(self, *args, **kwargs):
            mutation_calls.append("publish")

        async def reply(self, *args, **kwargs):
            mutation_calls.append("reply")

        async def comment(self, *args, **kwargs):
            mutation_calls.append("comment")

        async def react(self, *args, **kwargs):
            mutation_calls.append("react")

        async def message(self, *args, **kwargs):
            mutation_calls.append("message")

        async def follow(self, *args, **kwargs):
            mutation_calls.append("follow")

        async def delete_content(self, *args, **kwargs):
            mutation_calls.append("delete_content")

    import app.services.listening.ingestion_service as ingest_mod2
    original_get2 = ingest_mod2.get_adapter
    ingest_mod2.get_adapter = lambda _st: _SpyAdapter()  # type: ignore[assignment]
    try:
        async with AsyncSessionLocal() as spy_db:
            await run_manual_import(
                spy_db,
                tenant_id=tenant_c_id,
                project_id=project_c_id,
                items=[{
                    "provider_external_id": f"spy-import-{uuid4().hex[:8]}",
                    "content_text": "Acme via import path",
                    "language": "en",
                }],
            )
            mention_for_review = (
                await spy_db.execute(
                    select(TenantObservedMention).where(
                        TenantObservedMention.tenant_id == tenant_c_id,
                    ).limit(1)
                )
            ).scalar_one()
            await set_review_state(
                spy_db,
                tenant_id=tenant_c_id,
                mention_id=mention_for_review.id,
                new_state="relevant",
                actor_user_id=None,
            )
            await spy_db.rollback()
    finally:
        ingest_mod2.get_adapter = original_get2
    record("review_import_no_provider_mutation", mutation_calls == [], str(mutation_calls))

    # Static guarantee: listening package has no publish/reply symbols in ingestion
    from pathlib import Path as P
    listening_root = P(__file__).resolve().parents[1] / "app" / "services" / "listening"
    bad = []
    for path in listening_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in ("publish_post", "send_reply", "create_comment", "provider.write", "mutate_provider"):
            if needle in text:
                bad.append(f"{path.name}:{needle}")
    record("no_provider_write_symbols", bad == [], str(bad))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
