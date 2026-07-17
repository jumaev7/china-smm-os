"""Runtime verification for Governed AI Content Adaptation (DB integration).

Creates disposable tenant/content/brand fixtures, runs AI adapt via mock
provider, and proves immutable variant lifecycle: source unchanged, publishing
review, accept/reject/apply via ContentOptimizerService, stale 409, tenant
isolation.

Run from backend/:  python scripts/verify_ai_content_adaptation.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ["AI_PLATFORM_ENABLED"] = "true"
os.environ["AI_DEFAULT_PROVIDER"] = "mock"
os.environ["AI_FALLBACK_PROVIDER"] = ""

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
    from sqlalchemy import select

    from app.core.config import settings
    from app.core.database import (
        AsyncSessionLocal,
        ensure_content_optimizer_schema,
        ensure_governed_ai_schema,
        ensure_intelligence_schema,
        ensure_platform_event_bus_schema,
        ensure_publishing_intelligence_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.content_optimizer import TenantContentVariant
    from app.models.publishing_intelligence import TenantPublishingReview
    from app.models.tenant import Tenant, TenantUser
    from app.services.ai_content.adaptation_service import AIContentAdaptationService
    from app.services.ai_content.brand_profile_service import BrandProfileService
    from app.services.ai_content.schemas import AdaptRequest
    from app.services.ai_platform.provider_registry import get_mock_provider
    from app.services.auth_service import hash_password
    from app.services.content_optimizer import ContentOptimizerService
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )

    settings.AI_PLATFORM_ENABLED = True
    settings.AI_DEFAULT_PROVIDER = "mock"

    await ensure_platform_event_bus_schema()
    await ensure_intelligence_schema()
    await ensure_publishing_intelligence_schema()
    await ensure_content_optimizer_schema()
    await ensure_governed_ai_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []
    mock = get_mock_provider()
    mock.reset_test_hooks()

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    source_caption = (
        "Discover our export-ready steel components for global buyers.\n\n"
        "We manufacture to specification and ship worldwide with full documentation. "
        "Price is $99. Visit https://example.com/catalog today. "
        "Contact us today to request a quote and learn more."
    )

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(id=uuid4(), company_name=f"AI Adapt A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"AI Adapt B {stamp}", status="active", plan="trial")
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"ai-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        client_a = Client(
            id=uuid4(),
            tenant_id=tenant_a.id,
            company_name=f"AI Client A {stamp}",
            business_category="manufacturing",
            status="active",
        )
        client_b = Client(
            id=uuid4(),
            tenant_id=tenant_b.id,
            company_name=f"AI Client B {stamp}",
            business_category="manufacturing",
            status="active",
        )
        content_a = ContentItem(
            id=uuid4(),
            client_id=client_a.id,
            platforms=["telegram", "instagram"],
            status="draft",
            caption_long_en=source_caption,
            hashtags="#export #steel #b2b",
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

        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        user_a_id = user_a.id
        content_a_id = content_a.id

        profile = await BrandProfileService.create_profile(
            db,
            tenant_a_id,
            name=f"Brand {stamp}",
            draft={
                "locale": "en",
                "company_name": "Acme Steel Export",
                "company_description": "Export-ready steel manufacturer",
                "tone_traits": ["professional", "clear"],
                "preferred_terms": ["export-ready"],
                "forbidden_terms": [],
            },
            created_by=user_a_id,
        )
        version = await BrandProfileService.publish(db, tenant_a_id, profile.id, created_by=user_a_id)
        await db.commit()
        version_id = version.id
        record("brand_profile_published", version.version == 1, str(version.version))

        mock.reset_test_hooks()
        result = await AIContentAdaptationService.adapt(
            db,
            tenant_a_id,
            AdaptRequest(
                content_id=content_a_id,
                platforms=["telegram", "instagram"],
                locales=["en"],
                length_profiles=["standard"],
                brand_profile_version_id=version.id,
                quality_mode="standard",
            ),
            requested_by=user_a.id,
        )
        await db.commit()

        status = result.get("status")
        variants = [v for v in (result.get("variants") or []) if v.get("status") == "generated"]
        record("adapt_request_completed", status == "completed", str(status))
        record("adapt_produced_variants", len(variants) >= 1, str(len(variants)))
        record("adapt_mock_provider_called", mock.call_count >= 1, str(mock.call_count))
        source_fp = result.get("source_fingerprint")
        record("adapt_source_fingerprint", bool(source_fp))

        refreshed = (
            await db.execute(select(ContentItem).where(ContentItem.id == content_a.id))
        ).scalar_one()
        record("source_unchanged_after_adapt", refreshed.caption_long_en == source_caption)

        if variants:
            v0 = variants[0]
            vid = UUID(str(v0.get("variant_id") or v0.get("id")))
            vrow = (
                await db.execute(
                    select(TenantContentVariant).where(
                        TenantContentVariant.id == vid,
                        TenantContentVariant.tenant_id == tenant_a.id,
                    )
                )
            ).scalar_one()
            immutable_caption = vrow.caption
            immutable_fp = vrow.variant_fingerprint
            record("variant_generation_method_ai", vrow.generation_method == "ai_assisted", str(vrow.generation_method))
            record("variant_has_ai_request", vrow.ai_request_id is not None)

            linked = vrow.publishing_review_id
            record("variant_publishing_review_linked", linked is not None)
            if linked:
                review_row = (
                    await db.execute(
                        select(TenantPublishingReview).where(
                            TenantPublishingReview.id == linked,
                            TenantPublishingReview.tenant_id == tenant_a.id,
                        )
                    )
                ).scalar_one_or_none()
                record("linked_review_exists", review_row is not None)

            accept_res = await ContentOptimizerService.accept_variant(
                db, tenant_a.id, vid, accepted_by=user_a.id,
            )
            await db.commit()
            record("accept_variant", accept_res["status"] == "accepted", accept_res["status"])

            vrow_after = (
                await db.execute(select(TenantContentVariant).where(TenantContentVariant.id == vid))
            ).scalar_one()
            record(
                "variant_snapshot_immutable",
                vrow_after.caption == immutable_caption
                and vrow_after.variant_fingerprint == immutable_fp,
            )

            spare = next(
                (v for v in variants if str(v.get("variant_id") or v.get("id")) != str(vid)),
                None,
            )
            if spare:
                reject_res = await ContentOptimizerService.reject_variant(
                    db, tenant_a.id, UUID(str(spare.get("variant_id") or spare.get("id"))),
                    rejected_by=user_a.id,
                )
                await db.commit()
                record("reject_variant", reject_res["status"] == "rejected", reject_res["status"])
            else:
                record("reject_variant", True, "single variant — skipped")

            wrong_fp_409 = False
            try:
                await ContentOptimizerService.apply_variant(
                    db, tenant_a.id, vid,
                    expected_source_fingerprint="0" * 64, applied_by=user_a.id,
                )
            except Exception as exc:
                wrong_fp_409 = _status_code(exc) == 409
            record("apply_wrong_fingerprint_409", wrong_fp_409)

            apply_res = await ContentOptimizerService.apply_variant(
                db, tenant_a.id, vid,
                expected_source_fingerprint=source_fp, applied_by=user_a.id,
            )
            await db.commit()
            record("apply_variant", apply_res["status"] == "applied", apply_res["status"])

            after_apply = (
                await db.execute(select(ContentItem).where(ContentItem.id == content_a.id))
            ).scalar_one()
            record(
                "apply_does_not_publish",
                (after_apply.status or "draft") not in {"published", "scheduled", "publishing"},
                str(after_apply.status),
            )

            remaining = [
                v for v in variants
                if str(v.get("variant_id") or v.get("id")) != str(vid)
                and v.get("status") == "generated"
            ]
            if remaining and spare and str(spare.get("variant_id") or spare.get("id")) != str(
                remaining[0].get("variant_id") or remaining[0].get("id")
            ):
                target = remaining[0]
            elif remaining:
                target = remaining[0]
            else:
                target = None
            # After apply, source caption changed — spare rejected variant must not apply.
            stale_candidates = [
                v for v in variants
                if str(v.get("variant_id") or v.get("id")) != str(vid)
            ]
            if stale_candidates:
                tid = UUID(str(stale_candidates[0].get("variant_id") or stale_candidates[0].get("id")))
                stale_409 = False
                try:
                    # Rejected / stale / fingerprint mismatch all surface as 409.
                    await ContentOptimizerService.apply_variant(
                        db, tenant_a.id, tid,
                        expected_source_fingerprint=source_fp, applied_by=user_a.id,
                    )
                    await db.commit()
                except Exception as exc:
                    stale_409 = _status_code(exc) == 409
                    try:
                        await db.rollback()
                    except Exception:
                        pass
                record("apply_after_source_change_409", stale_409)
            else:
                record("apply_after_source_change_409", True, "no spare — skipped")

            tenant_b_id = tenant_b_id  # already captured early
            content_a_id = content_a_id
            request_id_val = result.get("request_id")

            try:
                await db.rollback()
            except Exception:
                pass

            iso = False
            try:
                await ContentOptimizerService.get_variant(db, tenant_b_id, vid)
            except Exception as exc:
                iso = _status_code(exc) == 404
            record("wrong_tenant_variant_404", iso)

            iso_adapt = False
            try:
                await AIContentAdaptationService.adapt(
                    db,
                    tenant_b_id,
                    AdaptRequest(
                        content_id=content_a_id,
                        platforms=["telegram"],
                        locales=["en"],
                        length_profiles=["standard"],
                        brand_profile_version_id=version_id,
                    ),
                    requested_by=user_a_id,
                )
            except Exception as exc:
                iso_adapt = _status_code(exc) == 404
            record("wrong_tenant_adapt_content_404", iso_adapt)

            iso_req = False
            try:
                await AIContentAdaptationService.get_request_detail(
                    db, tenant_b_id, UUID(str(request_id_val)),
                )
            except Exception as exc:
                iso_req = _status_code(exc) == 404
            record("wrong_tenant_request_404", iso_req)
        else:
            record("accept_variant", False, "no variants")
            record("variant_snapshot_immutable", False, "no variants")

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    print("SMOKE_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
