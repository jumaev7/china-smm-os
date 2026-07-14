"""Integration checks for production automation event emitters."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import asyncio

    return asyncio.run(_run())


async def _run() -> int:
    from sqlalchemy import func, select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.models.automation import TenantAutomationExecution
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.platform_event import TenantActivityEvent, TenantEventNotification
    from app.models.publishing_account import PublishingAccount
    from app.models.tenant import Tenant
    from app.schemas.buyer_crm import BuyerCreate, BuyerUpdate
    from app.schemas.publishing import PublishContentRequest, PublishingAccountUpdate
    from app.services.automation_domain_events import scrub_payload
    from app.services.automation_service import AutomationService
    from app.services.buyer_crm_service import BuyerCrmService
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration
    from app.services.meta_connection_service import MetaConnectionService
    from app.services.publish_service import ADAPTERS, PublishService
    from app.services.publishing_account_service import PublishingAccountService

    await ensure_platform_event_bus_schema()
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
        tenant_a = Tenant(id=uuid4(), company_name=f"Emit A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Emit B {stamp}", status="active", plan="trial")
        client_a = Client(
            id=uuid4(),
            tenant_id=tenant_a.id,
            company_name=tenant_a.company_name,
            source_language="en",
            business_category="manufacturing",
        )
        client_b = Client(
            id=uuid4(),
            tenant_id=tenant_b.id,
            company_name=tenant_b.company_name,
            source_language="en",
            business_category="manufacturing",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add_all([client_a, client_b])
        await db.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        client_a_id = client_a.id

        await AutomationService.ensure_system_flows(db, tenant_a_id)
        await AutomationService.ensure_system_flows(db, tenant_b_id)
        await db.commit()

        # --- Publish failure via real PublishService path (failing adapter) ---
        content = ContentItem(
            id=uuid4(),
            client_id=client_a_id,
            platforms=["linkedin"],
            status="approved",
            source="manual",
            caption_short_en=f"Emitter post {stamp}",
            approved_at=datetime.now(timezone.utc),
            client_review_status="approved",
            client_approved_at=datetime.now(timezone.utc),
        )
        account = PublishingAccount(
            id=uuid4(),
            tenant_id=tenant_a_id,
            platform="linkedin",
            account_name="LinkedIn Mock",
            account_id=f"li-{stamp}",
            status="mock",
        )
        db.add_all([content, account])
        await db.commit()
        content_id = content.id

        async def _failing_adapter(ctx):  # noqa: ANN001
            return {
                "platform": "linkedin",
                "success": False,
                "error": "adapter_simulated_failure",
                "platform_post_id": None,
                "mock": True,
                "account_id": str(account.id),
                "account_name": account.account_name,
                "access_token": "SHOULD_NOT_APPEAR",
            }

        from app.services.publish_safety_service import PublishSafetyService

        async def _noop_enforce(*_args, **_kwargs):
            return None

        original = ADAPTERS.get("linkedin")
        original_enforce = PublishSafetyService.enforce_or_block
        ADAPTERS["linkedin"] = _failing_adapter
        PublishSafetyService.enforce_or_block = staticmethod(_noop_enforce)
        try:
            result = await PublishService.publish_content(
                db,
                content_id,
                request=PublishContentRequest(platforms=["linkedin"], mode="manual_publish"),
            )
        except Exception as exc:
            record("publish_failed_status", False, f"exception={exc}")
            result = {}
        finally:
            PublishSafetyService.enforce_or_block = original_enforce
            if original is not None:
                ADAPTERS["linkedin"] = original
            else:
                ADAPTERS.pop("linkedin", None)

        if result:
            record("publish_failed_status", result.get("status") == "failed", str(result.get("status")))

        execs = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=50)
        publish_execs = [e for e in execs.items if e.trigger_event == "tenant.content.publish_failed"]
        record("publish_failed_emits_once", len(publish_execs) == 1, f"count={len(publish_execs)}")
        if publish_execs:
            record("publish_failed_execution_success", publish_execs[0].status == "success", publish_execs[0].status)

        noti_count = (
            await db.execute(
                select(func.count())
                .select_from(TenantEventNotification)
                .where(
                    TenantEventNotification.tenant_id == tenant_a_id,
                    TenantEventNotification.event_type == "tenant.content.publish_failed",
                ),
            )
        ).scalar_one()
        record("publish_failed_notification", int(noti_count) >= 1, f"count={noti_count}")

        # Re-persist same terminal failed content without a new publish run — no duplicate event.
        item = await PublishService._get_content(db, content_id)
        item.status = "failed"
        await db.commit()
        execs_after_resave = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=50)
        publish_after = [e for e in execs_after_resave.items if e.trigger_event == "tenant.content.publish_failed"]
        record("publish_failed_no_dup_on_resave", len(publish_after) == 1, f"count={len(publish_after)}")

        # Distinct retry attempt should emit again.
        item = await PublishService._get_content(db, content_id)
        item.status = "approved"
        item.approved_at = datetime.now(timezone.utc)
        await db.commit()
        ADAPTERS["linkedin"] = _failing_adapter
        PublishSafetyService.enforce_or_block = staticmethod(_noop_enforce)
        try:
            await PublishService.publish_content(
                db,
                content_id,
                request=PublishContentRequest(platforms=["linkedin"], mode="manual_publish"),
            )
        finally:
            PublishSafetyService.enforce_or_block = original_enforce
            if original is not None:
                ADAPTERS["linkedin"] = original
            else:
                ADAPTERS.pop("linkedin", None)

        execs_retry = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=50)
        publish_retry = [e for e in execs_retry.items if e.trigger_event == "tenant.content.publish_failed"]
        record("publish_failed_retry_distinct", len(publish_retry) == 2, f"count={len(publish_retry)}")

        wrong_tenant_execs = await AutomationService.list_executions(db, tenant_b_id, page=1, page_size=50)
        record(
            "publish_failed_tenant_isolation",
            all(e.trigger_event != "tenant.content.publish_failed" for e in wrong_tenant_execs.items),
            f"tenant_b_total={wrong_tenant_execs.total}",
        )

        # Inspect latest execution input for secrets.
        latest = (
            await db.execute(
                select(TenantAutomationExecution)
                .where(
                    TenantAutomationExecution.tenant_id == tenant_a_id,
                    TenantAutomationExecution.trigger_event == "tenant.content.publish_failed",
                )
                .order_by(TenantAutomationExecution.created_at.desc())
                .limit(1),
            )
        ).scalar_one()
        payload = latest.input_payload or {}
        scrubbed = scrub_payload(payload)
        secrets_absent = (
            "access_token" not in payload
            and "SHOULD_NOT_APPEAR" not in str(payload)
            and "access_token" not in scrubbed
        )
        record("publish_failed_secrets_absent", secrets_absent, "payload scrubbed")
        record(
            "publish_failed_attempt_number",
            int(payload.get("attempt_number") or 0) >= 1,
            str(payload.get("attempt_number")),
        )

        # Stale recovery path
        stale = ContentItem(
            id=uuid4(),
            client_id=client_a_id,
            platforms=["tiktok"],
            status="publishing",
            source="manual",
            caption_short_en=f"Stale {stamp}",
            updated_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        )
        db.add(stale)
        await db.commit()
        recovered = await PublishService.recover_stale_publishing(db, content_id=stale.id)
        record("stale_recovery_marks_failed", recovered == 1, f"recovered={recovered}")
        stale_execs = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        stale_hits = [
            e for e in stale_execs.items
            if e.trigger_event == "tenant.content.publish_failed"
            and (e.id not in {x.id for x in publish_retry})
        ]
        # Count total publish_failed should be >= 3 (2 retries + stale)
        pf_total = sum(1 for e in stale_execs.items if e.trigger_event == "tenant.content.publish_failed")
        record("stale_recovery_emits", pf_total >= 3, f"publish_failed_total={pf_total}")

        # --- Integration disconnect ---
        meta_account = PublishingAccount(
            id=uuid4(),
            tenant_id=tenant_a_id,
            platform="facebook",
            account_name="FB Page",
            account_id=f"fb-{stamp}",
            status="connected",
            access_token_encrypted="enc-secret-token",
            refresh_token_encrypted="enc-refresh-token",
        )
        db.add(meta_account)
        await db.commit()
        meta_id = meta_account.id

        await MetaConnectionService.disconnect(db, tenant_a_id)
        disc_execs = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        disc_hits = [e for e in disc_execs.items if e.trigger_event == "tenant.integration.disconnected"]
        record("integration_disconnect_emits_once", len(disc_hits) == 1, f"count={len(disc_hits)}")
        if disc_hits:
            record("integration_disconnect_success", disc_hits[0].status == "success", disc_hits[0].status)
            disc_payload = (
                await db.execute(
                    select(TenantAutomationExecution).where(TenantAutomationExecution.id == disc_hits[0].id),
                )
            ).scalar_one().input_payload or {}
            record(
                "integration_disconnect_no_tokens",
                "access_token" not in str(disc_payload)
                and "enc-secret-token" not in str(disc_payload)
                and "refresh_token" not in str(disc_payload),
                "secrets absent",
            )

        # Repeated disconnect / health-style no-op: already disconnected — no new event.
        await MetaConnectionService.disconnect(db, tenant_a_id)
        disc_execs2 = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        disc_hits2 = [e for e in disc_execs2.items if e.trigger_event == "tenant.integration.disconnected"]
        record("integration_disconnect_idempotent", len(disc_hits2) == 1, f"count={len(disc_hits2)}")

        # Publishing account status update transition
        other = PublishingAccount(
            id=uuid4(),
            tenant_id=tenant_a_id,
            platform="telegram",
            account_name="TG",
            account_id=f"-100{stamp}",
            status="connected",
        )
        db.add(other)
        await db.commit()
        await PublishingAccountService.update(
            db,
            tenant_a_id,
            other.id,
            PublishingAccountUpdate(status="disconnected"),
        )
        # No-op same status
        await PublishingAccountService.update(
            db,
            tenant_a_id,
            other.id,
            PublishingAccountUpdate(status="disconnected"),
        )
        disc_execs3 = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        disc_hits3 = [e for e in disc_execs3.items if e.trigger_event == "tenant.integration.disconnected"]
        record("integration_status_update_once", len(disc_hits3) == 2, f"count={len(disc_hits3)}")

        wrong_disc = await AutomationService.list_executions(db, tenant_b_id, page=1, page_size=50)
        record(
            "integration_disconnect_tenant_isolation",
            all(e.trigger_event != "tenant.integration.disconnected" for e in wrong_disc.items),
        )

        # --- Buyer created ---
        buyer = await BuyerCrmService.create_buyer(
            db,
            tenant_a_id,
            BuyerCreate(
                company_name=f"Buyer Co {stamp}",
                contact_person="Alex",
                country="Uzbekistan",
                industry="textiles",
            ),
            created_by="verify",
        )
        buyer_execs = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        buyer_hits = [e for e in buyer_execs.items if e.trigger_event == "tenant.buyer.created"]
        record("buyer_created_emits_once", len(buyer_hits) == 1, f"count={len(buyer_hits)}")
        if buyer_hits:
            record("buyer_created_execution_success", buyer_hits[0].status == "success", buyer_hits[0].status)
            row = (
                await db.execute(
                    select(TenantAutomationExecution).where(TenantAutomationExecution.id == buyer_hits[0].id),
                )
            ).scalar_one()
            result_payload = row.result_payload or {}
            record(
                "buyer_crm_lead_linkage",
                result_payload.get("source_buyer_id") == str(buyer.id) or "buyer_id" in str(row.input_payload),
                f"result={result_payload}",
            )

        # Update must not emit buyer.created
        await BuyerCrmService.update_buyer(
            db,
            buyer.id,
            tenant_a_id,
            BuyerUpdate(notes="updated notes only"),
            changed_by="verify",
        )
        buyer_execs2 = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        buyer_hits2 = [e for e in buyer_execs2.items if e.trigger_event == "tenant.buyer.created"]
        record("buyer_update_no_create_event", len(buyer_hits2) == 1, f"count={len(buyer_hits2)}")

        # Second create is a new durable row — may emit again; re-process same event must not duplicate lead.
        if buyer_hits:
            same_event = (
                await db.execute(
                    select(TenantAutomationExecution).where(TenantAutomationExecution.id == buyer_hits[0].id),
                )
            ).scalar_one()
            from app.core.events import build_tenant_event
            from app.services.automation_execution_service import AutomationExecutionService

            evt = build_tenant_event(
                "tenant.buyer.created",
                tenant_a_id,
                payload={"buyer_id": str(buyer.id), "buyer_name": "Alex", "company_name": buyer.company_name},
            )
            evt.event_id = same_event.event_id
            again = await AutomationExecutionService.process_event(db, evt)
            await db.commit()
            record(
                "buyer_automation_idempotent",
                len(again) == 1 and again[0].id == same_event.id,
                "same execution reused",
            )

        wrong_buyer = await AutomationService.list_executions(db, tenant_b_id, page=1, page_size=50)
        record(
            "buyer_created_tenant_isolation",
            all(e.trigger_event != "tenant.buyer.created" for e in wrong_buyer.items),
        )

        activity = (
            await db.execute(
                select(func.count())
                .select_from(TenantActivityEvent)
                .where(TenantActivityEvent.tenant_id == tenant_a_id),
            )
        ).scalar_one()
        record("activity_records_present", int(activity) >= 1, f"count={activity}")

    print(f"\n{len(failures)} failures" if failures else "\nAll production emitter checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
