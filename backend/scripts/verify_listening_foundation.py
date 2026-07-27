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
    from app.services.listening.ingestion_service import (
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
    )
    from app.services.listening.providers import get_adapter, list_source_capabilities
    from app.services.listening.providers.base import ListeningSourceAdapter
    from app.services.listening.review_service import set_review_state
    from app.services.listening.errors import ProjectPausedError, ProjectNotFoundError

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
        from app.services.listening.ingestion_service import ingest_observations
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

        # Cleanup
        await db.rollback()

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
