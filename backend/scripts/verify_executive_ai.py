"""Verify Executive AI Sales Assistant — rule engine v1 (no LLM)."""
from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPORT_PATH = Path(__file__).resolve().parent / ".verify_executive_ai_last.json"

ALL_RULE_IDS = frozenset({
    "R01_FOLLOW_UP_REQUIRED",
    "R02_LIKELY_TO_CLOSE",
    "R03_DEAL_AT_RISK",
    "R04_PROPOSAL_EXPIRING",
    "R05_PROPOSAL_WAITING_TOO_LONG",
    "R06_PUBLISHING_OPPORTUNITY",
    "R07_META_CONNECTION_OPPORTUNITY",
    "R08_UPSELL_OPPORTUNITY",
    "R09_INACTIVE_CUSTOMER",
    "R10_HIGH_VALUE_LEAD",
    "R11_STALE_DEAL",
    "R12_MANAGER_OVERLOAD",
})

ALL_CATEGORIES = frozenset({
    "follow_up_required",
    "likely_to_close",
    "deal_at_risk",
    "proposal_expiring",
    "proposal_waiting_too_long",
    "publishing_opportunity",
    "meta_connection_opportunity",
    "upsell_opportunity",
    "inactive_customer",
    "high_value_lead",
    "stale_deal",
    "manager_overload",
})

REQUIRED_FIELDS = frozenset({
    "rule_id", "category", "severity", "confidence",
    "business_reason", "recommended_action", "generated_at",
})


async def _run() -> int:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_dev_schema_patches
    from app.models.sales_crm import SalesCustomer, SalesDeal, SalesLead, SalesProposal
    from app.models.tenant import Tenant, TenantUser
    from app.schemas.crm_pipeline import RECOMMENDATION_CATEGORIES
    from app.services.crm_pipeline_intelligence_service import CrmPipelineIntelligenceService

    failures: list[str] = []
    checks: list[dict] = []
    stamp = int(datetime.now(timezone.utc).timestamp())
    now = datetime.now(timezone.utc)

    await ensure_dev_schema_patches()
    print("OK schema patches applied")

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(Tenant).limit(2))).scalars().all()
        if len(tenants) < 2:
            failures.append("need at least 2 tenants")
            print("FAIL need at least 2 tenants")
            return 1
        tenant_a, tenant_b = tenants[0], tenants[1]
        print(f"OK tenants {tenant_a.id} / {tenant_b.id}")

        owner_a = (await db.execute(
            select(TenantUser).where(TenantUser.tenant_id == tenant_a.id).limit(1)
        )).scalar_one_or_none()
        owner_id = owner_a.id if owner_a else None

        customer_a = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            name=f"Exec AI Customer A {stamp}",
            company="Exec AI Co",
        )
        customer_b = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            name=f"Exec AI Customer B {stamp}",
            company="Exec AI Co B",
        )
        db.add_all([customer_a, customer_b])
        await db.flush()

        follow_up_updated = now - timedelta(days=10)
        stale_updated = now - timedelta(days=20)
        inactive_updated = now - timedelta(days=35)
        close_soon = now + timedelta(days=14)

        deals_a = [
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Follow Up Deal {stamp}",
                value=Decimal("5000"),
                stage="contacted",
                probability=20,
                owner_id=owner_id,
                created_at=now - timedelta(days=30),
                updated_at=follow_up_updated,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Likely Close Deal {stamp}",
                value=Decimal("25000"),
                stage="contract_pending",
                probability=75,
                owner_id=owner_id,
                expected_close_date=close_soon,
                created_at=now - timedelta(days=20),
                updated_at=now,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"At Risk Deal {stamp}",
                value=Decimal("15000"),
                stage="negotiation",
                probability=55,
                owner_id=owner_id,
                created_at=now - timedelta(days=40),
                updated_at=stale_updated,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Stale Deal {stamp}",
                value=Decimal("3000"),
                stage="lead",
                probability=5,
                created_at=now - timedelta(days=50),
                updated_at=stale_updated,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Client Active No Pub {stamp}",
                value=Decimal("8000"),
                stage="client_active",
                probability=85,
                owner_id=owner_id,
                created_at=now - timedelta(days=60),
                updated_at=now,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Publishing Upsell {stamp}",
                value=Decimal("12000"),
                stage="publishing_active",
                probability=90,
                owner_id=owner_id,
                created_at=now - timedelta(days=30),
                updated_at=now,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Inactive Client {stamp}",
                value=Decimal("6000"),
                stage="client_active",
                probability=85,
                created_at=now - timedelta(days=90),
                updated_at=inactive_updated,
            ),
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"High Value Lead Deal {stamp}",
                value=Decimal("50000"),
                stage="qualified",
                probability=15,
                owner_id=owner_id,
                created_at=now - timedelta(days=5),
                updated_at=now,
            ),
        ]

        overload_deals = [
            SalesDeal(
                id=uuid.uuid4(),
                tenant_id=tenant_a.id,
                customer_id=customer_a.id,
                title=f"Overload Deal {i} {stamp}",
                value=Decimal("2000"),
                stage="lead",
                probability=5,
                owner_id=owner_id,
                created_at=now - timedelta(days=10),
                updated_at=now,
            )
            for i in range(9)
        ]

        deal_b = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            customer_id=customer_b.id,
            title=f"Tenant B Deal {stamp}",
            value=Decimal("999999"),
            stage="negotiation",
            probability=80,
            created_at=now - timedelta(days=20),
            updated_at=stale_updated,
        )
        db.add_all([*deals_a, *overload_deals, deal_b])
        await db.flush()

        likely_deal = deals_a[1]
        at_risk_deal = deals_a[2]

        lead_high = SalesLead(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            name=f"High Priority Lead {stamp}",
            priority="high",
            status="new",
            created_at=now - timedelta(days=2),
            updated_at=now,
        )
        db.add(lead_high)
        await db.flush()

        prop_expiring = SalesProposal(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            proposal_number=f"PROP-EXP-{stamp}",
            title=f"Expiring Proposal {stamp}",
            customer_id=customer_a.id,
            deal_id=likely_deal.id,
            issue_date=now - timedelta(days=20),
            valid_until=now + timedelta(days=3),
            total=Decimal("10000"),
            status="sent",
            sent_at=now - timedelta(days=20),
        )
        prop_waiting = SalesProposal(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            proposal_number=f"PROP-WAIT-{stamp}",
            title=f"Waiting Proposal {stamp}",
            customer_id=customer_a.id,
            deal_id=at_risk_deal.id,
            issue_date=now - timedelta(days=30),
            valid_until=now + timedelta(days=30),
            total=Decimal("8000"),
            status="viewed",
            sent_at=now - timedelta(days=20),
        )
        db.add_all([prop_expiring, prop_waiting])
        await db.commit()
        print("OK executive AI fixture data created")

        intel_a = await CrmPipelineIntelligenceService.generate_recommendations(db, tenant_a.id)
        intel_b = await CrmPipelineIntelligenceService.generate_recommendations(db, tenant_b.id)
        brief_a = await CrmPipelineIntelligenceService.morning_brief(db, tenant_a.id)
        insights_a = await CrmPipelineIntelligenceService.manager_insights(db, tenant_a.id)

        checks.append({"id": "recommendations_generated", "status": "ok", "count": intel_a.total})

        if intel_a.total == 0:
            failures.append("tenant A produced zero recommendations")
        else:
            print(f"OK tenant A recommendations={intel_a.total}")

        triggered_rules = {r.rule_id for r in intel_a.recommendations}
        missing_rules = ALL_RULE_IDS - triggered_rules
        if missing_rules:
            failures.append(f"rules not triggered in fixture: {sorted(missing_rules)}")
        else:
            print("OK all 12 rules triggered")
            checks.append({"id": "all_rules_triggered", "status": "ok"})

        triggered_cats = {r.category for r in intel_a.recommendations}
        if triggered_cats != ALL_CATEGORIES:
            missing_cats = ALL_CATEGORIES - triggered_cats
            failures.append(f"categories missing: {sorted(missing_cats)}")
        else:
            print("OK all 12 categories present")
            checks.append({"id": "all_categories_present", "status": "ok"})

        if len(RECOMMENDATION_CATEGORIES) != 12:
            failures.append(f"schema category count expected 12 got {len(RECOMMENDATION_CATEGORIES)}")

        for rec in intel_a.recommendations:
            data = rec.model_dump()
            for field in REQUIRED_FIELDS:
                if field not in data or data[field] is None:
                    failures.append(f"recommendation missing field {field} on {rec.rule_id}")
            if not (0 <= rec.confidence <= 100):
                failures.append(f"confidence out of range on {rec.rule_id}")
            if rec.severity not in ("critical", "high", "medium", "low"):
                failures.append(f"invalid severity on {rec.rule_id}")

        if not failures:
            print("OK recommendation field validation")

        dedup_keys = [
            (r.rule_id, r.deal_id, r.customer_id, r.lead_id, r.proposal_id, r.owner_id)
            for r in intel_a.recommendations
        ]
        if len(dedup_keys) != len(set(dedup_keys)):
            failures.append("duplicate recommendations detected")
        else:
            print("OK no duplicate recommendations")
            checks.append({"id": "no_duplicates", "status": "ok"})

        scores = [r.priority_score for r in intel_a.recommendations]
        if scores != sorted(scores, reverse=True):
            failures.append("recommendations not sorted by priority_score descending")
        else:
            print("OK priority ordering (highest first)")
            checks.append({"id": "priority_ordering", "status": "ok"})

        critical_first = next(
            (r for r in intel_a.recommendations if r.severity == "critical"), None,
        )
        if critical_first and intel_a.recommendations[0].severity not in ("critical", "high"):
            failures.append("critical/high items should rank at top")
        elif critical_first:
            print("OK critical items rank highly")
            checks.append({"id": "critical_ranking", "status": "ok"})

        tenant_b_rules = {r.rule_id for r in intel_b.recommendations}
        tenant_b_titles = {
            r.deal_title for r in intel_b.recommendations if r.deal_title
        }
        leaked = [t for t in tenant_b_titles if str(stamp) in t and "Tenant B" not in t]
        if leaked:
            failures.append(f"tenant B recommendations leaked tenant A deals: {leaked}")
        else:
            print("OK tenant isolation on recommendations")
            checks.append({"id": "tenant_isolation_recommendations", "status": "ok"})

        if intel_b.total < 1:
            failures.append("tenant B should have at least stale deal recommendation")
        else:
            print(f"OK tenant B recommendations={intel_b.total}")

        if not brief_a.todays_priorities:
            failures.append("morning brief missing todays_priorities")
        if not brief_a.top_risks:
            failures.append("morning brief missing top_risks")
        if not brief_a.top_opportunities:
            failures.append("morning brief missing top_opportunities")
        if brief_a.pipeline_health is None:
            failures.append("morning brief missing pipeline_health")
        if brief_a.revenue_forecast is None:
            failures.append("morning brief missing revenue_forecast")
        if brief_a.manager_workload is None:
            failures.append("morning brief missing manager_workload")
        if brief_a.publishing_health is None:
            failures.append("morning brief missing publishing_health")
        if not brief_a.all_recommendations:
            failures.append("morning brief missing all_recommendations")
        if not failures:
            print("OK morning brief generation")
            checks.append({"id": "morning_brief", "status": "ok"})

        brief_keys = [
            (r.rule_id, r.deal_id, r.customer_id, r.lead_id, r.proposal_id, r.owner_id)
            for r in brief_a.all_recommendations
        ]
        intel_keys = [
            (r.rule_id, r.deal_id, r.customer_id, r.lead_id, r.proposal_id, r.owner_id)
            for r in intel_a.recommendations
        ]
        if len(brief_keys) != len(intel_keys):
            failures.append(
                f"morning brief recommendation count mismatch: brief={len(brief_keys)} intel={len(intel_keys)}",
            )
        elif set(brief_keys) != set(intel_keys):
            failures.append("morning brief all_recommendations keys mismatch with intelligence response")
        else:
            print("OK morning brief matches recommendations")
            checks.append({"id": "brief_recommendations_match", "status": "ok"})

        if owner_id:
            owner_insights = [m for m in insights_a.managers if m.owner_id == owner_id]
            if not owner_insights:
                failures.append("manager insights missing owner row")
            else:
                row = owner_insights[0]
                if row.open_deals < 10:
                    failures.append(f"manager open_deals expected >= 10 got {row.open_deals}")
                if row.likely_wins < 1:
                    failures.append("manager likely_wins expected >= 1")
                if row.workload_score < 50:
                    failures.append(f"manager workload_score expected >= 50 got {row.workload_score}")
                else:
                    print("OK manager insights metrics")
                    checks.append({"id": "manager_insights", "status": "ok"})
        else:
            print("SKIP manager insights (no tenant user)")

        no_openai_import = True
        service_path = Path(__file__).resolve().parents[1] / "app/services/crm_pipeline_intelligence_service.py"
        service_src = service_path.read_text(encoding="utf-8").lower()
        import_lines = [
            line for line in service_src.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        import_block = "\n".join(import_lines)
        for forbidden in ("openai", "chatgpt", "langchain", "anthropic"):
            if forbidden in import_block:
                failures.append(f"forbidden import '{forbidden}' found in intelligence service")
                no_openai_import = False
        if no_openai_import:
            print("OK no LLM/OpenAI dependencies in service")
            checks.append({"id": "no_llm", "status": "ok"})

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "failures": failures,
        "exit_code": 1 if failures else 0,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"OK report written to {REPORT_PATH}")

    if failures:
        print("\nFAILURES:")
        for item in failures:
            print(" -", item)
        return 1

    print("\nALL EXECUTIVE AI CHECKS PASSED")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
