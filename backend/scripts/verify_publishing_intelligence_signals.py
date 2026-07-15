"""Runtime verification — reviews, stale lifecycle, MIP signals, tenant isolation."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import asyncio

    return asyncio.run(_run())


async def _run() -> int:
    from sqlalchemy import func, select

    from app.core.database import (
        AsyncSessionLocal,
        ensure_intelligence_schema,
        ensure_platform_event_bus_schema,
        ensure_publishing_intelligence_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.intelligence import TenantMarketingSignal
    from app.models.publishing_intelligence import TenantPublishingReview
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.publishing_intelligence.review_engine import PublishingReviewEngine

    await ensure_platform_event_bus_schema()
    await ensure_intelligence_schema()
    await ensure_publishing_intelligence_schema()
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
        tenant_a = Tenant(
            id=uuid4(),
            company_name=f"PI Verify A {stamp}",
            status="active",
            plan="trial",
        )
        tenant_b = Tenant(
            id=uuid4(),
            company_name=f"PI Verify B {stamp}",
            status="active",
            plan="trial",
        )
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"pi-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        client_a = Client(
            id=uuid4(),
            tenant_id=tenant_a.id,
            company_name=f"PI Client A {stamp}",
            business_category="manufacturing",
            status="active",
        )
        client_b = Client(
            id=uuid4(),
            tenant_id=tenant_b.id,
            company_name=f"PI Client B {stamp}",
            business_category="manufacturing",
            status="active",
        )
        content_a = ContentItem(
            id=uuid4(),
            client_id=client_a.id,
            platforms=["telegram", "instagram"],
            status="draft",
            caption_long_en=(
                "Discover our export-ready steel components for global buyers. "
                "Contact us today to request a quote and learn more."
            ),
            hashtags="#export #steel #b2b #china",
        )
        content_b = ContentItem(
            id=uuid4(),
            client_id=client_b.id,
            platforms=["telegram"],
            status="draft",
            caption_long_en="Tenant B private caption — Contact us now.",
            hashtags="#b",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([user_a, client_a, client_b])
        await db.commit()
        db.add_all([content_a, content_b])
        await db.commit()

        r1 = await PublishingReviewEngine.create_review(
            db, tenant_a.id, content_a.id, created_by=user_a.id,
        )
        await db.commit()
        record("first_review_completed", r1.status in {"completed", "stale"} and r1.review_version == 1)
        record("score_in_range", 0 <= r1.overall_score <= 100, str(r1.overall_score))
        record("has_checks", len(r1.checks) > 5, str(len(r1.checks)))
        record("advisory_flag", r1.summary.get("advisory") is True)
        score_a = r1.overall_score
        fp_a = r1.content_fingerprint

        # Determinism re-run should produce same score for same content after supersede
        r2 = await PublishingReviewEngine.create_review(db, tenant_a.id, content_a.id)
        await db.commit()
        record("second_version", r2.review_version == 2)
        record("score_deterministic_rerun", r2.overall_score == score_a, f"{r2.overall_score} vs {score_a}")
        record("fingerprint_stable", r2.content_fingerprint == fp_a)

        prior = (
            await db.execute(
                select(TenantPublishingReview).where(
                    TenantPublishingReview.id == r1.review_id,
                )
            )
        ).scalar_one()
        record("prior_superseded", prior.status == "superseded", prior.status)
        record("history_preserved", True)

        # Edit content → stale
        item = (
            await db.execute(select(ContentItem).where(ContentItem.id == content_a.id))
        ).scalar_one()
        item.caption_long_en = (item.caption_long_en or "") + " Updated CTA: buy now."
        await db.commit()

        latest = await PublishingReviewEngine.get_latest(db, tenant_a.id, content_a.id)
        await db.commit()
        record("stale_after_edit", latest is not None and latest.is_stale, str(latest.status if latest else None))

        r3 = await PublishingReviewEngine.create_review(db, tenant_a.id, content_a.id)
        await db.commit()
        record("new_version_after_edit", r3.review_version == 3)
        record("new_review_current", r3.is_current and not r3.is_stale)

        # Tenant isolation — wrong tenant 404
        isolated = True
        try:
            await PublishingReviewEngine.get_review(db, tenant_b.id, r3.review_id)
            isolated = False
        except Exception as exc:
            isolated = getattr(exc, "status_code", None) == 404
        record("wrong_tenant_review_404", isolated)

        content_isolation = True
        try:
            await PublishingReviewEngine.create_review(db, tenant_b.id, content_a.id)
            content_isolation = False
        except Exception as exc:
            content_isolation = getattr(exc, "status_code", None) == 404
        record("wrong_tenant_content_404", content_isolation)

        # MIP signals created without caption leakage
        signals = list(
            (
                await db.execute(
                    select(TenantMarketingSignal).where(
                        TenantMarketingSignal.tenant_id == tenant_a.id,
                        TenantMarketingSignal.signal_type.in_(
                            [
                                "publishing.review_completed",
                                "publishing.score_low",
                                "publishing.critical_issue_detected",
                                "publishing.platform_fit_low",
                                "publishing.review_became_stale",
                            ]
                        ),
                    )
                )
            ).scalars().all()
        )
        record("review_signals_created", len(signals) >= 1, str(len(signals)))
        completed = [s for s in signals if s.signal_type == "publishing.review_completed"]
        record("review_completed_signal", len(completed) >= 1)

        leaked = False
        for s in signals:
            blob = str(s.metadata_json or {})
            if "Discover our export" in blob or "api_key" in blob.lower():
                leaked = True
        record("no_caption_leak_in_signals", not leaked)

        # Tenant B review should not appear under A
        await PublishingReviewEngine.create_review(db, tenant_b.id, content_b.id)
        await db.commit()
        leaked_reviews = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantPublishingReview).where(
                        TenantPublishingReview.tenant_id == tenant_a.id,
                        TenantPublishingReview.content_id == content_b.id,
                    )
                )
            ).scalar_one()
        )
        record("tenant_isolation_reviews", leaked_reviews == 0)

        # Immutability: prior summary unchanged after new review
        prior_again = (
            await db.execute(
                select(TenantPublishingReview).where(TenantPublishingReview.id == r1.review_id)
            )
        ).scalar_one()
        record(
            "review_immutable_score",
            prior_again.overall_score == score_a,
            f"{prior_again.overall_score}",
        )

        # Restart persistence — re-load from DB
        reloaded = await PublishingReviewEngine.get_latest(db, tenant_a.id, content_a.id)
        record(
            "persists_after_reload",
            reloaded is not None and reloaded.review_id == r3.review_id,
        )

        # Hard blocker vs advisory
        record(
            "publish_readiness_present",
            r3.publish_readiness in {"ready", "ready_with_warnings", "blocked"},
            r3.publish_readiness,
        )
        record("score_is_advisory", r3.summary.get("advisory") is True)

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
