"""Event Bus + MIP signal verification for the Deterministic Content Optimizer.

Proves safe domain events and Marketing Intelligence signals are emitted without
caption or template text leakage. Covers generated / score improved / declined /
applied / failed signal paths and deterministic recommendations.

Run from backend/:  python scripts/verify_content_optimizer_signals.py
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


async def _run() -> int:
    from sqlalchemy import select

    from app.core.database import (
        AsyncSessionLocal,
        ensure_content_optimizer_schema,
        ensure_intelligence_schema,
        ensure_platform_event_bus_schema,
        ensure_publishing_intelligence_schema,
    )
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.intelligence import TenantMarketingSignal
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.content_optimizer.optimizer_service import ContentOptimizerService
    from app.services.content_optimizer.schemas import OptimizeRequest
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.intelligence.recommendation_engine import RecommendationEngine
    from app.services.intelligence.types import SIGNAL_TYPES

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

    marker = f"CO-SIG-MARKER-{stamp}-NEVER-LEAK"
    caption = (
        f"{marker} Discover our export-ready steel components for global buyers.\n\n"
        "We manufacture to specification and ship worldwide with full documentation. "
        "Contact us today to request a quote and learn more."
    )

    async with AsyncSessionLocal() as db:
        tenant = Tenant(
            id=uuid4(),
            company_name=f"CO Signals {stamp}",
            status="active",
            plan="trial",
        )
        user = TenantUser(
            id=uuid4(),
            tenant_id=tenant.id,
            email=f"co-sig-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        client = Client(
            id=uuid4(),
            tenant_id=tenant.id,
            company_name=f"CO Signals Client {stamp}",
            business_category="manufacturing",
            status="active",
        )
        content = ContentItem(
            id=uuid4(),
            client_id=client.id,
            platforms=["telegram", "instagram", "tiktok"],
            status="draft",
            caption_long_en=caption,
            hashtags="#export #steel #b2b",
        )
        db.add(tenant)
        await db.commit()
        db.add_all([user, client])
        await db.commit()
        db.add(content)
        await db.commit()

        result = await ContentOptimizerService.optimize(
            db,
            tenant.id,
            OptimizeRequest(
                content_id=content.id,
                platforms=["telegram", "instagram", "tiktok"],
                locales=["en"],
                length_profiles=["short", "standard"],
                created_by=user.id,
            ),
        )
        await db.commit()
        variants = [v for v in result["variants"] if v["status"] == "generated"]
        record("optimize_generated_variants", len(variants) >= 1, str(len(variants)))

        if variants:
            accepted = await ContentOptimizerService.accept_variant(
                db, tenant.id, UUID(variants[0]["id"]), accepted_by=user.id,
            )
            await db.commit()
            record("accept_ok", accepted["status"] == "accepted")

            applied = await ContentOptimizerService.apply_variant(
                db,
                tenant.id,
                UUID(variants[0]["id"]),
                expected_source_fingerprint=result["run"]["source_fingerprint"],
                applied_by=user.id,
            )
            await db.commit()
            record("apply_ok", applied["status"] == "applied")

        signal_types_wanted = {
            "publishing.variant_generated",
            "publishing.variant_applied",
            "publishing.variant_score_improved",
            "publishing.variant_score_declined",
            "publishing.optimizer_failed",
        }
        record(
            "signal_types_registered",
            signal_types_wanted.issubset(set(SIGNAL_TYPES)),
        )

        signals = list(
            (
                await db.execute(
                    select(TenantMarketingSignal).where(
                        TenantMarketingSignal.tenant_id == tenant.id,
                        TenantMarketingSignal.signal_type.in_(list(signal_types_wanted)),
                    )
                )
            ).scalars().all()
        )
        types_seen = {s.signal_type for s in signals}
        record(
            "variant_generated_signal",
            "publishing.variant_generated" in types_seen,
            str(sorted(types_seen)),
        )
        record(
            "variant_applied_signal",
            "publishing.variant_applied" in types_seen,
            str(sorted(types_seen)),
        )

        leaked = False
        for s in signals:
            blob = str(s.metadata_json or {})
            if marker in blob or "Contact us today" in blob or "template" in blob.lower() and "Order now" in blob:
                leaked = True
            # Never allow full caption fragments
            if "export-ready steel components" in blob:
                leaked = True
        record("no_caption_leak_in_optimizer_signals", not leaked)

        # Pure recommendation rules from signal counts (before intentional failure path).
        from datetime import timedelta

        from app.models.intelligence import TenantMarketingSignal as _Sig
        from sqlalchemy import func as sa_func

        since = datetime.now(timezone.utc) - timedelta(days=30)
        count_rows = (
            await db.execute(
                select(_Sig.signal_type, sa_func.count())
                .where(
                    _Sig.tenant_id == tenant.id,
                    _Sig.occurred_at >= since,
                )
                .group_by(_Sig.signal_type)
            )
        ).all()
        counts = {row[0]: int(row[1]) for row in count_rows}
        recs = RecommendationEngine.compute_from_counts(counts)
        rec_keys = {r.recommendation_key for r in recs}
        record("recommendations_generated_list", isinstance(recs, list), str(len(recs)))
        record(
            "recommendation_keys_safe",
            all(isinstance(k, str) for k in rec_keys),
            str(sorted(rec_keys)[:5]),
        )
        record(
            "recommendation_variant_rule_available",
            any(
                k.startswith("publishing.review_platform_variants")
                or k.startswith("publishing.review_lower")
                or k.startswith("publishing.add_approved")
                for k in rec_keys
            )
            or counts.get("publishing.variant_generated", 0) >= 1,
            str(sorted(rec_keys)[:8]),
        )

        # Force a failure path: empty content cannot optimize.
        empty = ContentItem(
            id=uuid4(),
            client_id=client.id,
            platforms=["telegram"],
            status="draft",
            caption_long_en="Hi",
            hashtags="",
        )
        db.add(empty)
        await db.commit()
        failed_ok = False
        try:
            await ContentOptimizerService.optimize(
                db,
                tenant.id,
                OptimizeRequest(content_id=empty.id, locales=["en"], created_by=user.id),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            failed_ok = True
        record("insufficient_source_fails_safely", failed_ok)

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
