"""In-process verification — tenant isolation, collectors, scores, recommendations."""
from __future__ import annotations

import json
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

    from app.core.database import AsyncSessionLocal, ensure_intelligence_schema, ensure_platform_event_bus_schema
    from app.models.intelligence import (
        TenantMarketingRecommendation,
        TenantMarketingScore,
        TenantMarketingSignal,
    )
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.intelligence.service import IntelligenceService
    from app.services.platform_event_service import PlatformEventService

    await ensure_platform_event_bus_schema()
    await ensure_intelligence_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []
    report: dict = {"checks": []}

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        report["checks"].append({"id": check_id, "ok": ok, "detail": detail})
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(
            id=uuid4(),
            company_name=f"MIP Verify A {stamp}",
            status="active",
            plan="trial",
        )
        tenant_b = Tenant(
            id=uuid4(),
            company_name=f"MIP Verify B {stamp}",
            status="active",
            plan="trial",
        )
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"mip-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        db.add(tenant_a)
        db.add(tenant_b)
        db.add(user_a)
        await db.commit()

        # Emit publishing failure for tenant A
        for _ in range(3):
            await PlatformEventService.emit(
                db,
                "tenant.content.publish_failed",
                tenant_a.id,
                payload={"platform": "instagram", "error": "token_expired"},
                actor_type="system",
                resource_type="content",
                resource_id=str(uuid4()),
                title="Publish failed",
                commit=True,
            )

        await PlatformEventService.emit(
            db,
            "tenant.integration.disconnected",
            tenant_a.id,
            payload={"provider": "meta"},
            actor_type="system",
            resource_type="integration",
            resource_id="meta",
            title="Integration disconnected",
            commit=True,
        )

        # Emit a CRM event for tenant B (should stay isolated)
        await PlatformEventService.emit(
            db,
            "tenant.crm.lead_created",
            tenant_b.id,
            payload={"source": "verify"},
            actor_type="system",
            resource_type="lead",
            resource_id=str(uuid4()),
            title="Lead created",
            commit=True,
        )

        signals_a = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantMarketingSignal).where(
                        TenantMarketingSignal.tenant_id == tenant_a.id,
                    )
                )
            ).scalar_one()
        )
        signals_b = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantMarketingSignal).where(
                        TenantMarketingSignal.tenant_id == tenant_b.id,
                    )
                )
            ).scalar_one()
        )
        leaked_to_b = int(
            (
                await db.execute(
                    select(func.count()).select_from(TenantMarketingSignal).where(
                        TenantMarketingSignal.tenant_id == tenant_b.id,
                        TenantMarketingSignal.signal_type == "publishing.failed",
                    )
                )
            ).scalar_one()
        )
        record("tenant_a_has_signals", signals_a >= 4, f"count={signals_a}")
        record("tenant_b_has_own_signals", signals_b >= 1, f"count={signals_b}")
        record("tenant_isolation_no_leak", leaked_to_b == 0, f"leaked={leaked_to_b}")

        # Idempotency: re-emitting same event_id isn't easy via emit (new id each time),
        # but collector insert uses signal_id uniqueness — verify scores exist.
        scores_a = (
            await db.execute(
                select(TenantMarketingScore).where(TenantMarketingScore.tenant_id == tenant_a.id)
            )
        ).scalars().all()
        record("scores_computed_for_tenant_a", len(scores_a) >= 9, f"count={len(scores_a)}")
        overall = next((s for s in scores_a if s.category == "overall"), None)
        record("overall_score_present", overall is not None and 0 <= (overall.score if overall else -1) <= 100)

        recs_a = (
            await db.execute(
                select(TenantMarketingRecommendation).where(
                    TenantMarketingRecommendation.tenant_id == tenant_a.id,
                    TenantMarketingRecommendation.status == "open",
                )
            )
        ).scalars().all()
        keys = {r.recommendation_key for r in recs_a}
        record("recommendation_publish_accounts", "publishing.review_accounts" in keys, str(keys))
        record("recommendation_reconnect", "integration.reconnect" in keys, str(keys))
        record(
            "recommendations_explainable",
            all(isinstance(r.explanation, dict) and r.explanation.get("reasoning") for r in recs_a),
        )

        # Read API isolation
        listed_a = await IntelligenceService.list_signals(db, tenant_a.id, page_size=100)
        listed_b = await IntelligenceService.list_signals(db, tenant_b.id, page_size=100)
        a_types = {i["signal_type"] for i in listed_a["items"]}
        b_types = {i["signal_type"] for i in listed_b["items"]}
        record("service_list_a_has_publish_fail", "publishing.failed" in a_types, str(a_types))
        record("service_list_b_no_publish_fail", "publishing.failed" not in b_types, str(b_types))

        health = await IntelligenceService.get_health(db, tenant_a.id)
        record("health_status_present", health["status"] in {"healthy", "warning", "critical"}, health["status"])
        await db.commit()

    out = Path(__file__).resolve().parent / ".verify_marketing_intelligence_last.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if failures:
        print(f"\nFAILED {len(failures)} checks")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nMarketing Intelligence in-process verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
