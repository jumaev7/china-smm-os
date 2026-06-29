"""Verify Executive CRM Pipeline Phase 2 — transitions, timeline, proposals, isolation."""
from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run() -> int:
    from fastapi import HTTPException
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_dev_schema_patches
    from app.models.sales_crm import SalesCustomer, SalesDeal, SalesLead, SalesProposal, SalesProposalItem
    from app.models.tenant import Tenant
    from app.schemas.crm_pipeline import PipelineStageUpdate
    from app.schemas.sales_crm import SalesProposalStatusUpdate
    from app.services.crm_pipeline_service import CrmPipelineService
    from app.services.crm_pipeline_timeline_service import CrmPipelineTimelineService
    from app.services.sales_proposal_service import SalesProposalService

    failures: list[str] = []
    stamp = int(datetime.now(timezone.utc).timestamp())

    await ensure_dev_schema_patches()
    print("OK schema patches applied")

    async with AsyncSessionLocal() as db:
        tenants = (await db.execute(select(Tenant).limit(2))).scalars().all()
        if len(tenants) < 2:
            print("FAIL need at least 2 tenants in database")
            return 1
        tenant_a, tenant_b = tenants[0], tenants[1]
        print(f"OK tenants {tenant_a.id} / {tenant_b.id}")

        customer_a = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            name=f"Pipeline Verify A {stamp}",
            company="Verify Co A",
        )
        customer_b = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            name=f"Pipeline Verify B {stamp}",
            company="Verify Co B",
        )
        db.add_all([customer_a, customer_b])
        await db.flush()

        lead_a = SalesLead(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            customer_id=customer_a.id,
            name=f"Lead A {stamp}",
            source="manual",
            status="new",
        )
        deal_a = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            customer_id=customer_a.id,
            lead_id=lead_a.id,
            title=f"Pipeline Deal A {stamp}",
            stage="lead",
            probability=5,
        )
        deal_b = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant_b.id,
            customer_id=customer_b.id,
            title=f"Pipeline Deal B {stamp}",
            stage="lead",
            probability=5,
        )
        db.add_all([lead_a, deal_a, deal_b])
        await db.flush()
        await CrmPipelineService.on_deal_created(db, deal_a, actor="verify")
        await CrmPipelineService.on_lead_created(db, lead_a, actor="verify")
        await db.commit()
        print("OK migration-compatible data created")

        try:
            await CrmPipelineService.transition_stage(
                db,
                deal_a.id,
                tenant_a.id,
                PipelineStageUpdate(stage="closed_won", stage_override=True),
                actor="verify",
            )
            failures.append("illegal transition lead->closed_won was not rejected")
        except HTTPException as exc:
            if exc.status_code == 422:
                print("OK illegal transition rejected")
            else:
                failures.append(f"illegal transition wrong status {exc.status_code}")

        moved = await CrmPipelineService.transition_stage(
            db,
            deal_a.id,
            tenant_a.id,
            PipelineStageUpdate(stage="qualified", stage_override=False),
            actor="verify",
        )
        if moved["stage"] != "qualified":
            failures.append(f"legal transition failed: {moved['stage']}")
        else:
            print("OK legal transition lead->qualified")

        events, total = await CrmPipelineTimelineService.list_deal_timeline(
            db, deal_a.id, tenant_a.id, limit=20,
        )
        stage_events = [e for e in events if e.event_type == "stage_changed"]
        if not stage_events:
            failures.append("stage transition did not write timeline event")
        else:
            print(f"OK stage transition timeline events={len(stage_events)} total={total}")

        now = datetime.now(timezone.utc)
        proposal = SalesProposal(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            proposal_number=f"PROP-VERIFY-{stamp}",
            title=f"Verify Proposal {stamp}",
            customer_id=customer_a.id,
            lead_id=lead_a.id,
            deal_id=deal_a.id,
            issue_date=now,
            currency="USD",
            subtotal=Decimal("1000"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("1000"),
            status="draft",
            status_history=[],
        )
        db.add(proposal)
        await db.flush()
        db.add(SalesProposalItem(
            proposal_id=proposal.id,
            product_or_service_name="Service",
            quantity=Decimal("1"),
            unit_price=Decimal("1000"),
            total=Decimal("1000"),
        ))
        await db.commit()

        await SalesProposalService.update_status(
            db,
            proposal.id,
            SalesProposalStatusUpdate(status="sent"),
            tenant_a.id,
            actor="verify",
        )
        deal_after_sent = await CrmPipelineService._load_deal(db, deal_a.id, tenant_a.id)
        if deal_after_sent.stage != "proposal_sent":
            failures.append(f"proposal sent expected proposal_sent got {deal_after_sent.stage}")
        else:
            print("OK proposal sent -> proposal_sent")

        proposal_refreshed = await SalesProposalService.get_proposal(db, proposal.id, tenant_a.id)
        if not proposal_refreshed.get("sent_at"):
            failures.append("proposal sent_at not recorded")
        else:
            print("OK proposal sent_at recorded")

        await SalesProposalService.update_status(
            db,
            proposal.id,
            SalesProposalStatusUpdate(status="accepted"),
            tenant_a.id,
            actor="verify",
        )
        deal_after_accept = await CrmPipelineService._load_deal(db, deal_a.id, tenant_a.id)
        if deal_after_accept.stage != "contract_pending":
            failures.append(f"proposal accepted expected contract_pending got {deal_after_accept.stage}")
        else:
            print("OK proposal accepted -> contract_pending (no client_id)")

        from app.models.client import Client

        client_row = (await db.execute(
            select(Client.id).where(Client.tenant_id == tenant_a.id).limit(1)
        )).scalar_one_or_none()

        customer_with_client = SalesCustomer(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            name=f"Client-linked {stamp}",
            client_id=client_row,
        )
        deal_client = SalesDeal(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            customer_id=customer_with_client.id,
            title=f"Client Deal {stamp}",
            stage="proposal_sent",
            probability=40,
        )
        proposal_client = SalesProposal(
            id=uuid.uuid4(),
            tenant_id=tenant_a.id,
            proposal_number=f"PROP-CLIENT-{stamp}",
            title="Client linked proposal",
            customer_id=customer_with_client.id,
            deal_id=deal_client.id,
            issue_date=now,
            currency="USD",
            subtotal=Decimal("500"),
            discount=Decimal("0"),
            tax=Decimal("0"),
            total=Decimal("500"),
            status="sent",
            sent_at=now,
            status_history=[],
        )
        db.add_all([customer_with_client, deal_client, proposal_client])
        await db.flush()
        db.add(SalesProposalItem(
            proposal_id=proposal_client.id,
            product_or_service_name="Service",
            quantity=Decimal("1"),
            unit_price=Decimal("500"),
            total=Decimal("500"),
        ))
        await db.commit()

        await SalesProposalService.update_status(
            db,
            proposal_client.id,
            SalesProposalStatusUpdate(status="accepted"),
            tenant_a.id,
            actor="verify",
        )
        deal_client_after = await CrmPipelineService._load_deal(db, deal_client.id, tenant_a.id)
        expected_client_stage = "client_active" if client_row else "contract_pending"
        if deal_client_after.stage != expected_client_stage:
            failures.append(
                f"client acceptance expected {expected_client_stage} got {deal_client_after.stage}",
            )
        else:
            print(f"OK proposal accepted -> {expected_client_stage}")

        try:
            await CrmPipelineService._load_deal(db, deal_b.id, tenant_a.id)
            failures.append("tenant isolation failed — cross-tenant deal readable")
        except HTTPException as exc:
            if exc.status_code == 404:
                print("OK tenant isolation enforced")
            else:
                failures.append(f"tenant isolation wrong status {exc.status_code}")

        events_b, _ = await CrmPipelineTimelineService.list_deal_timeline(
            db, deal_b.id, tenant_b.id, limit=5,
        )
        events_a_on_b = [e for e in events_b if e.tenant_id == tenant_a.id]
        if events_a_on_b:
            failures.append("cross-tenant timeline leakage")
        else:
            print("OK timeline tenant scoped")

    if failures:
        print("\nFAILURES:")
        for item in failures:
            print(" -", item)
        return 1

    print("\nALL CRM PIPELINE CHECKS PASSED")
    return 0


def main() -> int:
    return asyncio.run(_run())


if __name__ == "__main__":
    raise SystemExit(main())
