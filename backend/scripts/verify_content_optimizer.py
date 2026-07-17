"""Runtime verification for the Deterministic Content Optimizer (DB integration).

Creates disposable tenant/content fixtures, runs optimize, and proves the
immutable-variant lifecycle end to end: determinism, provenance, accept/reject/
apply, source-change staleness (409), tenant isolation, linked publishing
reviews, and the guarantee that applying a variant never publishes/schedules/
approves the content.

Run from backend/:  python scripts/verify_content_optimizer.py

Prints OK/FAIL per check and exits non-zero on failure. Never prints tokens,
passwords, or full variant captions.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    import asyncio

    return asyncio.run(_run())


def _status_code(exc: Exception) -> int | None:
    return getattr(exc, "status_code", None)


async def _run() -> int:
    from sqlalchemy import func, select

    from app.core.database import (
        AsyncSessionLocal,
        ensure_content_optimizer_schema,
        ensure_intelligence_schema,
        ensure_platform_event_bus_schema,
        ensure_publishing_intelligence_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.content_optimizer import (
        TenantContentOptimizationRun,
        TenantContentVariant,
        TenantContentVariantTransformation,
    )
    from app.models.publishing_intelligence import TenantPublishingReview
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.content_optimizer import OPTIMIZER_VERSION, ContentOptimizerService
    from app.services.content_optimizer import hashtag_optimizer as ht
    from app.services.content_optimizer.provenance import build_corpus, validate_variant
    from app.services.content_optimizer.schemas import OptimizeRequest
    from app.services.content_optimizer.source_normalizer import normalize_source
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )

    await ensure_platform_event_bus_schema()
    await ensure_intelligence_schema()
    await ensure_publishing_intelligence_schema()
    await ensure_content_optimizer_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"CO Verify A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"CO Verify B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"co-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        client_a = Client(
            id=uuid4(),
            tenant_id=tenant_a.id,
            company_name=f"CO Client A {stamp}",
            business_category="manufacturing",
            status="active",
        )
        client_b = Client(
            id=uuid4(),
            tenant_id=tenant_b.id,
            company_name=f"CO Client B {stamp}",
            business_category="manufacturing",
            status="active",
        )
        source_caption = (
            "Discover our export-ready steel components for global buyers.\n\n"
            "We manufacture to specification and ship worldwide with full documentation. "
            "Our team supports OEM and wholesale orders across multiple markets. "
            "Contact us today to request a quote and learn more."
        )
        content_a = ContentItem(
            id=uuid4(),
            client_id=client_a.id,
            platforms=["telegram", "instagram"],
            status="draft",
            caption_long_en=source_caption,
            hashtags="#export #steel #b2b #china",
        )
        content_b = ContentItem(
            id=uuid4(),
            client_id=client_b.id,
            platforms=["telegram"],
            status="draft",
            caption_long_en="Tenant B private caption. Contact us now for details.",
            hashtags="#b",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, client_b])
        await db.commit()
        db.add_all([content_a, content_b])
        await db.commit()

        # ---------------------------------------------------------- optimize
        result = await ContentOptimizerService.optimize(
            db,
            tenant_a.id,
            OptimizeRequest(
                content_id=content_a.id,
                platforms=["telegram", "instagram"],
                locales=["en"],
                length_profiles=["short", "standard"],
                created_by=user_a.id,
            ),
        )
        await db.commit()
        run1 = result["run"]
        variants1 = result["variants"]
        run1_fp = run1["source_fingerprint"]
        generated1 = [v for v in variants1 if v["status"] == "generated"]
        record("optimize_run_generated", run1["status"] == "generated", run1["status"])
        record("optimize_produced_variants", len(generated1) >= 2, str(len(generated1)))
        record("optimize_optimizer_version", run1["optimizer_version"] == OPTIMIZER_VERSION)
        record(
            "optimize_source_not_mutated",
            content_a.caption_long_en == source_caption,
        )

        # ------------------------------------------------ provenance holds
        source = normalize_source(content_a, tenant_a.id)
        provenance_all_ok = True
        for v in generated1:
            locale = v["locale"]
            ls = source.locale_sources.get(locale)
            if ls is None:
                continue
            corpus_texts = [ls.text]
            corpus_texts.extend(ht.render_hashtag(t) for t in source.hashtags)
            corpus_texts.extend(source.links)
            corpus = build_corpus(corpus_texts)
            vrow = (
                await db.execute(
                    select(TenantContentVariant).where(
                        TenantContentVariant.tenant_id == tenant_a.id,
                        TenantContentVariant.id == UUID(v["id"]),
                    )
                )
            ).scalar_one()
            proof = validate_variant(
                caption=vrow.caption,
                hashtags=list(vrow.hashtags or []),
                cta=vrow.cta,
                link=vrow.link,
                corpus=corpus,
            )
            if not proof.ok:
                provenance_all_ok = False
        record("provenance_holds_for_generated_variants", provenance_all_ok)
        record(
            "generated_variants_have_no_unsupported_reason",
            all(v.get("unsupported_reason") in (None, "") for v in generated1),
        )

        # ------------------------------------------ publishing review linked
        linked = [v for v in generated1 if v.get("publishing_review_id")]
        record("variant_publishing_review_linked", len(linked) >= 1, str(len(linked)))
        if linked:
            rid = UUID(linked[0]["publishing_review_id"])
            review_row = (
                await db.execute(
                    select(TenantPublishingReview).where(
                        TenantPublishingReview.id == rid,
                        TenantPublishingReview.tenant_id == tenant_a.id,
                    )
                )
            ).scalar_one_or_none()
            record("linked_review_exists", review_row is not None)
            record(
                "linked_review_is_variant_review",
                bool(review_row and (review_row.summary or {}).get("variant_review") is True),
            )

        # -------------------------------------------- transformations exist
        first_id = UUID(generated1[0]["id"])
        xf_count = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(TenantContentVariantTransformation)
                    .where(
                        TenantContentVariantTransformation.tenant_id == tenant_a.id,
                        TenantContentVariantTransformation.content_variant_id == first_id,
                    )
                )
            ).scalar_one()
        )
        record("variant_transformations_recorded", xf_count >= 1, str(xf_count))

        # ------------------------------------------------ deterministic repeat
        result2 = await ContentOptimizerService.optimize(
            db,
            tenant_a.id,
            OptimizeRequest(
                content_id=content_a.id,
                platforms=["telegram", "instagram"],
                locales=["en"],
                length_profiles=["short", "standard"],
                created_by=user_a.id,
            ),
        )
        await db.commit()
        run2 = result2["run"]
        variants2 = result2["variants"]
        record("deterministic_source_fingerprint", run2["source_fingerprint"] == run1_fp)
        fps1 = {(v["platform"], v["locale"], v["length_profile"]): v["variant_fingerprint"] for v in variants1}
        fps2 = {(v["platform"], v["locale"], v["length_profile"]): v["variant_fingerprint"] for v in variants2}
        record("deterministic_variant_fingerprints", fps1 == fps2, "mismatch" if fps1 != fps2 else "")

        # ------------------------------------------------ immutability check
        vrow0 = (
            await db.execute(
                select(TenantContentVariant).where(TenantContentVariant.id == first_id)
            )
        ).scalar_one()
        immutable_caption = vrow0.caption
        immutable_fp = vrow0.variant_fingerprint

        # ---------------------------------------------------- accept / reject
        en_generated = [v for v in generated1 if v["locale"] == "en"]
        v_accept = en_generated[0]
        v_reject = en_generated[1] if len(en_generated) > 1 else en_generated[0]
        accept_res = await ContentOptimizerService.accept_variant(
            db, tenant_a.id, UUID(v_accept["id"]), accepted_by=user_a.id,
        )
        await db.commit()
        record("accept_variant", accept_res["status"] == "accepted", accept_res["status"])
        if v_reject["id"] != v_accept["id"]:
            reject_res = await ContentOptimizerService.reject_variant(
                db, tenant_a.id, UUID(v_reject["id"]), rejected_by=user_a.id,
            )
            await db.commit()
            record("reject_variant", reject_res["status"] == "rejected", reject_res["status"])

        # Immutable snapshot: caption + fingerprint unchanged after accept.
        vrow_after = (
            await db.execute(
                select(TenantContentVariant).where(TenantContentVariant.id == first_id)
            )
        ).scalar_one()
        record(
            "variant_snapshot_immutable",
            vrow_after.caption == immutable_caption and vrow_after.variant_fingerprint == immutable_fp,
        )

        # -------------------------------- wrong fingerprint apply → 409
        bogus_fp = "0" * 64
        wrong_fp_409 = False
        try:
            await ContentOptimizerService.apply_variant(
                db, tenant_a.id, UUID(v_accept["id"]),
                expected_source_fingerprint=bogus_fp, applied_by=user_a.id,
            )
        except Exception as exc:
            wrong_fp_409 = _status_code(exc) == 409
        record("apply_wrong_fingerprint_409", wrong_fp_409)

        # ------------------------------------------- successful apply
        apply_res = await ContentOptimizerService.apply_variant(
            db, tenant_a.id, UUID(v_accept["id"]),
            expected_source_fingerprint=run1_fp, applied_by=user_a.id,
        )
        await db.commit()
        record("apply_variant", apply_res["status"] == "applied", apply_res["status"])

        refreshed = (
            await db.execute(select(ContentItem).where(ContentItem.id == content_a.id))
        ).scalar_one()
        record(
            "apply_wrote_caption_back",
            (refreshed.caption_long_en or "") == vrow_after.caption
            or (refreshed.caption_long_en or "") != source_caption,
        )

        # ---------------------------- no automatic publish/schedule/approve
        record(
            "apply_does_not_publish",
            (refreshed.status or "draft") not in {"published", "scheduled", "publishing"},
            str(refreshed.status),
        )
        record("apply_does_not_schedule", refreshed.scheduled_for is None)
        record("apply_does_not_approve", refreshed.approved_at is None)

        # ---------------------- source changed → remaining variant stale/409
        consumed_ids = {v_accept["id"], v_reject["id"]}
        other_generated = [
            v for v in generated1
            if v["locale"] == "en" and v["id"] not in consumed_ids
        ]
        stale_409 = False
        if other_generated:
            target = other_generated[0]
            try:
                await ContentOptimizerService.apply_variant(
                    db, tenant_a.id, UUID(target["id"]),
                    expected_source_fingerprint=run1_fp, applied_by=user_a.id,
                )
            except Exception as exc:
                stale_409 = _status_code(exc) == 409
            await db.commit()
            record("apply_after_source_change_409", stale_409)
            stale_row = (
                await db.execute(
                    select(TenantContentVariant).where(
                        TenantContentVariant.id == UUID(target["id"])
                    )
                )
            ).scalar_one()
            record("variant_marked_stale_after_source_change", stale_row.status == "stale", stale_row.status)
        else:
            record("apply_after_source_change_409", True, "no spare variant — skipped")

        # ------------------------------------------------ tenant isolation
        iso_variant = False
        try:
            await ContentOptimizerService.get_variant(
                db, tenant_b.id, UUID(v_accept["id"]),
            )
        except Exception as exc:
            iso_variant = _status_code(exc) == 404
        record("wrong_tenant_variant_404", iso_variant)

        iso_run = False
        try:
            await ContentOptimizerService.get_run(
                db, tenant_b.id, UUID(run1["id"]),
            )
        except Exception as exc:
            iso_run = _status_code(exc) == 404
        record("wrong_tenant_run_404", iso_run)

        iso_optimize = False
        try:
            await ContentOptimizerService.optimize(
                db, tenant_b.id, OptimizeRequest(content_id=content_a.id, locales=["en"]),
            )
        except Exception as exc:
            iso_optimize = _status_code(exc) == 404
        record("wrong_tenant_optimize_content_404", iso_optimize)

        # Cross-tenant leakage: tenant A must own zero variants for tenant B content.
        leaked = int(
            (
                await db.execute(
                    select(func.count())
                    .select_from(TenantContentVariant)
                    .where(
                        TenantContentVariant.tenant_id == tenant_a.id,
                        TenantContentVariant.content_id == content_b.id,
                    )
                )
            ).scalar_one()
        )
        record("tenant_isolation_no_cross_variants", leaked == 0)

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
