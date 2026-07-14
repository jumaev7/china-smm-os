"""Automation Reliability Phase 2 — service-level checks."""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    from fastapi import HTTPException
    from sqlalchemy import func, select, text
    from sqlalchemy.exc import IntegrityError

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.core.events import build_tenant_event
    from app.models.automation import TenantAutomationExecution, TenantAutomationFlow
    from app.models.client import Client
    from app.models.content import ContentItem
    from app.models.platform_event import TenantEventNotification
    from app.models.publishing_account import PublishingAccount
    from app.models.tenant import Tenant
    from app.schemas.publishing import PublishContentRequest
    from app.services.automation_execution_service import (
        AutomationExecutionService,
        event_deduplication_key,
    )
    from app.services.automation_service import AutomationService
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )
    from app.services.publish_safety_service import PublishSafetyService
    from app.services.publish_service import ADAPTERS, PublishService

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
        tenant_a = Tenant(id=uuid4(), company_name=f"Rel A {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Rel B {stamp}", status="active", plan="trial")
        client_a = Client(
            id=uuid4(),
            tenant_id=tenant_a.id,
            company_name=tenant_a.company_name,
            source_language="en",
            business_category="manufacturing",
        )
        db.add_all([tenant_a, tenant_b])
        await db.commit()
        db.add(client_a)
        await db.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id
        client_a_id = client_a.id

        created = await AutomationService.ensure_system_flows(db, tenant_a_id)
        await AutomationService.ensure_system_flows(db, tenant_b_id)
        await db.commit()
        flows = await AutomationService.list_flows(db, tenant_a_id)
        partial_flow = next(
            (f for f in flows.items if f.key == "system_publish_partial_failed_notify"),
            None,
        )
        publish_flow = next(
            (f for f in flows.items if f.key == "system_publish_failed_notify"),
            None,
        )
        record("partial_system_flow_seeded", partial_flow is not None, f"created={created}")
        record("seed_count_ge_4", flows.total >= 4, f"total={flows.total}")

        # --- DB idempotency ---
        if publish_flow:
            event = build_tenant_event(
                "tenant.content.publish_failed",
                tenant_a_id,
                payload={"resource_name": "Idempotency widget"},
            )
            first = await AutomationExecutionService.process_event(db, event)
            await db.commit()
            second = await AutomationExecutionService.process_event(db, event)
            await db.commit()
            record("duplicate_event_one_execution", len(first) == 1 and len(second) == 1 and first[0].id == second[0].id)

            count = (
                await db.execute(
                    select(func.count())
                    .select_from(TenantAutomationExecution)
                    .where(
                        TenantAutomationExecution.tenant_id == tenant_a_id,
                        TenantAutomationExecution.automation_flow_id == publish_flow.id,
                        TenantAutomationExecution.deduplication_key == event_deduplication_key(event.event_id),
                    ),
                )
            ).scalar_one()
            record("unique_dedup_key_enforced_row_count", int(count) == 1, f"count={count}")

            # Concurrent duplicate attempts
            event_c = build_tenant_event(
                "tenant.content.publish_failed",
                tenant_a_id,
                payload={"resource_name": "Concurrent widget"},
            )

            async def _race() -> list:
                async with AsyncSessionLocal() as race_db:
                    flow_row = (
                        await race_db.execute(
                            select(TenantAutomationFlow).where(
                                TenantAutomationFlow.id == publish_flow.id,
                            ),
                        )
                    ).scalar_one()
                    out = await AutomationExecutionService._execute_flow(
                        race_db,
                        flow=flow_row,
                        event_id=event_c.event_id,
                        trigger_event=event_c.event_type,
                        payload=event_c.payload or {},
                        execution_kind="event",
                        deduplication_key=event_deduplication_key(event_c.event_id),
                    )
                    await race_db.commit()
                    return out

            raced = await asyncio.gather(_race(), _race(), return_exceptions=True)
            ok_raced = [
                r for r in raced
                if not isinstance(r, BaseException) and r is not None
            ]
            race_ids = {r.id for r in ok_raced}
            race_count = (
                await db.execute(
                    select(func.count())
                    .select_from(TenantAutomationExecution)
                    .where(
                        TenantAutomationExecution.tenant_id == tenant_a_id,
                        TenantAutomationExecution.deduplication_key
                        == event_deduplication_key(event_c.event_id),
                    ),
                )
            ).scalar_one()
            record(
                "concurrent_duplicate_one_row",
                int(race_count) == 1 and len(race_ids) == 1,
                f"rows={race_count} ids={len(race_ids)} errs={[type(e).__name__ for e in raced if isinstance(e, BaseException)]}",
            )

            # Unique constraint rejects raw duplicate insert
            existing = ok_raced[0] if ok_raced else first[0]
            dup = TenantAutomationExecution(
                id=uuid4(),
                tenant_id=tenant_a_id,
                automation_flow_id=publish_flow.id,
                event_id=uuid4(),
                trigger_event="tenant.content.publish_failed",
                status="failed",
                started_at=datetime.now(timezone.utc),
                execution_kind="event",
                deduplication_key=existing.deduplication_key,
                root_execution_id=uuid4(),
                retry_number=0,
                attempt_number=1,
            )
            try:
                async with AsyncSessionLocal() as db2:
                    db2.add(dup)
                    await db2.commit()
                record("unique_constraint_rejects_duplicate", False, "insert succeeded")
            except IntegrityError:
                record("unique_constraint_rejects_duplicate", True)
            except Exception as exc:
                record("unique_constraint_rejects_duplicate", "unique" in str(exc).lower() or "duplicate" in str(exc).lower(), str(exc)[:120])

            manual1 = await AutomationService.manual_run(db, tenant_a_id, publish_flow.id)
            manual2 = await AutomationService.manual_run(db, tenant_a_id, publish_flow.id)
            await db.commit()
            record(
                "manual_runs_independent",
                manual1.execution_id != manual2.execution_id,
                f"{manual1.execution_id} vs {manual2.execution_id}",
            )

        # --- Retry behavior ---
        if publish_flow:
            flow_row = (
                await db.execute(
                    select(TenantAutomationFlow).where(TenantAutomationFlow.id == publish_flow.id),
                )
            ).scalar_one()
            flow_row.max_retry_attempts = 2
            await db.flush()

            failed_id = uuid4()
            event_id = uuid4()
            failed = TenantAutomationExecution(
                id=failed_id,
                tenant_id=tenant_a_id,
                automation_flow_id=publish_flow.id,
                event_id=event_id,
                trigger_event="tenant.content.publish_failed",
                status="failed",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                duration_ms=12,
                input_payload={"resource_name": "Retry me", "manual_test": False},
                error_code="execution_error",
                error_message="transient boom",
                error_category="internal",
                is_retryable=True,
                execution_kind="event",
                deduplication_key=event_deduplication_key(event_id),
                root_execution_id=failed_id,
                retry_number=0,
                attempt_number=1,
            )
            db.add(failed)
            await db.commit()

            retry_resp = await AutomationService.retry_execution(db, tenant_a_id, failed_id)
            await db.commit()
            record(
                "retryable_failed_can_retry",
                retry_resp.execution_kind == "retry" and retry_resp.retry_number == 1,
                f"kind={retry_resp.execution_kind} n={retry_resp.retry_number} status={retry_resp.status}",
            )
            record(
                "retry_creates_new_execution",
                retry_resp.execution_id != failed_id,
                str(retry_resp.execution_id),
            )
            record(
                "retry_links_root_and_parent",
                retry_resp.root_execution_id == failed_id
                and retry_resp.retry_of_execution_id == failed_id,
            )

            original = (
                await db.execute(
                    select(TenantAutomationExecution).where(TenantAutomationExecution.id == failed_id),
                )
            ).scalar_one()
            record(
                "original_execution_unchanged",
                original.status == "failed" and original.error_code == "execution_error",
                original.status,
            )

            success_row = TenantAutomationExecution(
                id=uuid4(),
                tenant_id=tenant_a_id,
                automation_flow_id=publish_flow.id,
                event_id=uuid4(),
                trigger_event="tenant.content.publish_failed",
                status="success",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                input_payload={},
                execution_kind="event",
                deduplication_key=f"event:{uuid4()}",
                root_execution_id=None,
                retry_number=0,
                attempt_number=1,
                is_retryable=False,
            )
            success_row.root_execution_id = success_row.id
            db.add(success_row)
            await db.commit()
            try:
                await AutomationService.retry_execution(db, tenant_a_id, success_row.id)
                record("success_cannot_retry", False, "expected 409")
            except HTTPException as exc:
                record("success_cannot_retry", exc.status_code == 409, f"status={exc.status_code}")

            try:
                await AutomationService.retry_execution(db, tenant_b_id, failed_id)
                record("wrong_tenant_retry_404", False, "expected 404")
            except HTTPException as exc:
                record("wrong_tenant_retry_404", exc.status_code == 404, f"status={exc.status_code}")

            non_retryable = TenantAutomationExecution(
                id=uuid4(),
                tenant_id=tenant_a_id,
                automation_flow_id=publish_flow.id,
                event_id=uuid4(),
                trigger_event="tenant.content.publish_failed",
                status="failed",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                input_payload={},
                error_code="invalid_config",
                error_message="bad config",
                error_category="validation",
                is_retryable=False,
                execution_kind="event",
                deduplication_key=f"event:{uuid4()}",
                root_execution_id=None,
                retry_number=0,
                attempt_number=1,
            )
            non_retryable.root_execution_id = non_retryable.id
            db.add(non_retryable)
            await db.commit()
            try:
                await AutomationService.retry_execution(db, tenant_a_id, non_retryable.id)
                record("non_retryable_409", False, "expected 409")
            except HTTPException as exc:
                record("non_retryable_409", exc.status_code == 409, f"detail={exc.detail}")

            # Exhaust retry limit (max=2; already used 1)
            r2 = await AutomationService.retry_execution(db, tenant_a_id, failed_id)
            await db.commit()
            record("second_retry_allowed", r2.retry_number == 2, f"n={r2.retry_number}")
            try:
                await AutomationService.retry_execution(db, tenant_a_id, failed_id)
                record("retry_limit_enforced", False, "expected 409")
            except HTTPException as exc:
                record("retry_limit_enforced", exc.status_code == 409, f"detail={exc.detail}")

            # Same retry number cannot duplicate unintentionally
            same_key = (
                await db.execute(
                    select(func.count())
                    .select_from(TenantAutomationExecution)
                    .where(
                        TenantAutomationExecution.tenant_id == tenant_a_id,
                        TenantAutomationExecution.deduplication_key == f"retry:{failed_id}:1",
                    ),
                )
            ).scalar_one()
            record("retry_key_unique", int(same_key) == 1, f"count={same_key}")

        # --- Partial publishing failure ---
        content = ContentItem(
            id=uuid4(),
            client_id=client_a_id,
            platforms=["linkedin", "tiktok"],
            status="approved",
            source="manual",
            caption_short_en=f"Partial {stamp}",
            approved_at=datetime.now(timezone.utc),
            client_review_status="approved",
            client_approved_at=datetime.now(timezone.utc),
        )
        acct_li = PublishingAccount(
            id=uuid4(),
            tenant_id=tenant_a_id,
            platform="linkedin",
            account_name="LI",
            account_id=f"li-{stamp}",
            status="mock",
        )
        acct_tt = PublishingAccount(
            id=uuid4(),
            tenant_id=tenant_a_id,
            platform="tiktok",
            account_name="TT",
            account_id=f"tt-{stamp}",
            status="mock",
        )
        db.add_all([content, acct_li, acct_tt])
        await db.commit()
        content_id = content.id

        async def _ok(ctx):  # noqa: ANN001
            return {
                "platform": "linkedin",
                "success": True,
                "platform_post_id": "ok-1",
                "mock": True,
                "account_id": str(acct_li.id),
                "account_name": "LI",
            }

        async def _fail(ctx):  # noqa: ANN001
            return {
                "platform": "tiktok",
                "success": False,
                "error": "partial_adapter_failure",
                "platform_post_id": None,
                "mock": True,
                "account_id": str(acct_tt.id),
                "account_name": "TT",
                "access_token": "SECRET_SHOULD_NOT_PERSIST",
            }

        originals = {k: ADAPTERS.get(k) for k in ("linkedin", "tiktok")}
        original_enforce = PublishSafetyService.enforce_or_block

        async def _noop_enforce(*_args, **_kwargs):
            return None

        ADAPTERS["linkedin"] = _ok
        ADAPTERS["tiktok"] = _fail
        PublishSafetyService.enforce_or_block = staticmethod(_noop_enforce)
        try:
            result = await PublishService.publish_content(
                db,
                content_id,
                request=PublishContentRequest(platforms=["linkedin", "tiktok"], mode="manual_publish"),
            )
        finally:
            PublishSafetyService.enforce_or_block = original_enforce
            for k, v in originals.items():
                if v is not None:
                    ADAPTERS[k] = v
                else:
                    ADAPTERS.pop(k, None)

        record("partial_status", result.get("status") == "partial_failed", str(result.get("status")))

        execs = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        partial_execs = [e for e in execs.items if e.trigger_event == "tenant.content.publish_partial_failed"]
        full_fail_from_partial = [
            e for e in execs.items
            if e.trigger_event == "tenant.content.publish_failed"
            and "Partial" in str((getattr(e, "automation_name", None) or ""))
        ]
        # More precise: only count executions whose input mentions this content
        partial_for_content = []
        for e in partial_execs:
            detail = await AutomationService.get_execution(db, tenant_a_id, e.id)
            summary = detail.input_summary or {}
            if summary.get("content_id") == str(content_id):
                partial_for_content.append(e)

        record("partial_emits_partial_event", len(partial_for_content) == 1, f"count={len(partial_for_content)}")

        # Ensure no full-failure event for this content
        full_for_content = 0
        for e in execs.items:
            if e.trigger_event != "tenant.content.publish_failed":
                continue
            detail = await AutomationService.get_execution(db, tenant_a_id, e.id)
            if (detail.input_summary or {}).get("content_id") == str(content_id):
                full_for_content += 1
        record("partial_no_full_failure_event", full_for_content == 0, f"full={full_for_content}")

        # Re-save content as partial_failed — no duplicate
        item = await PublishService._get_content(db, content_id)
        item.status = "partial_failed"
        await db.commit()
        execs2 = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        partial2 = [e for e in execs2.items if e.trigger_event == "tenant.content.publish_partial_failed"]
        record("partial_no_dup_on_resave", len(partial2) == len(partial_execs), f"{len(partial2)} vs {len(partial_execs)}")

        noti = (
            await db.execute(
                select(func.count())
                .select_from(TenantEventNotification)
                .where(
                    TenantEventNotification.tenant_id == tenant_a_id,
                    TenantEventNotification.event_type == "tenant.content.publish_partial_failed",
                ),
            )
        ).scalar_one()
        record("partial_system_flow_notification", int(noti) >= 1, f"count={noti}")

        if partial_for_content:
            detail = await AutomationService.get_execution(db, tenant_a_id, partial_for_content[0].id)
            blob = str(detail.input_summary) + str(detail.result_summary)
            record("partial_payload_no_secrets", "SECRET_SHOULD_NOT_PERSIST" not in blob and "access_token" not in blob)

        # Full success emits neither failure event
        content_ok = ContentItem(
            id=uuid4(),
            client_id=client_a_id,
            platforms=["linkedin"],
            status="approved",
            source="manual",
            caption_short_en=f"OK {stamp}",
            approved_at=datetime.now(timezone.utc),
            client_review_status="approved",
            client_approved_at=datetime.now(timezone.utc),
        )
        db.add(content_ok)
        await db.commit()
        ADAPTERS["linkedin"] = _ok
        PublishSafetyService.enforce_or_block = staticmethod(_noop_enforce)
        before = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=1)
        before_total = before.total
        try:
            ok_result = await PublishService.publish_content(
                db,
                content_ok.id,
                request=PublishContentRequest(platforms=["linkedin"], mode="manual_publish"),
            )
        finally:
            PublishSafetyService.enforce_or_block = original_enforce
            if originals["linkedin"] is not None:
                ADAPTERS["linkedin"] = originals["linkedin"]
            else:
                ADAPTERS.pop("linkedin", None)
        record("full_success_status", ok_result.get("status") == "published", str(ok_result.get("status")))
        after = await AutomationService.list_executions(db, tenant_a_id, page=1, page_size=100)
        new_fail_events = [
            e for e in after.items
            if e.trigger_event in (
                "tenant.content.publish_failed",
                "tenant.content.publish_partial_failed",
            )
            and e.created_at  # filtered below by content
        ]
        # Check none reference content_ok
        ok_fail_refs = 0
        for e in new_fail_events:
            d = await AutomationService.get_execution(db, tenant_a_id, e.id)
            if (d.input_summary or {}).get("content_id") == str(content_ok.id):
                ok_fail_refs += 1
        record("full_success_no_failure_events", ok_fail_refs == 0, f"refs={ok_fail_refs} total_delta={after.total - before_total}")

        # --- KPI behavior ---
        kpis = await AutomationService.get_kpis(db, tenant_a_id)
        record("kpi_success_rate_defined", kpis.success_rate is not None and 0 <= kpis.success_rate <= 100)
        record("kpi_retry_metrics", kpis.retry_count_today >= 1, f"retries={kpis.retry_count_today}")
        record(
            "kpi_partial_metric",
            kpis.partial_publish_failures_today >= 1,
            f"partial={kpis.partial_publish_failures_today}",
        )
        kpis_b = await AutomationService.get_kpis(db, tenant_b_id)
        record(
            "kpi_tenant_isolation",
            kpis_b.executions_today == 0 or kpis_b.partial_publish_failures_today == 0,
            f"b_exec={kpis_b.executions_today} b_partial={kpis_b.partial_publish_failures_today}",
        )
        empty_tenant = Tenant(id=uuid4(), company_name=f"Rel Empty {stamp}", status="active", plan="trial")
        db.add(empty_tenant)
        await db.commit()
        kpis_empty = await AutomationService.get_kpis(db, empty_tenant.id)
        record(
            "kpi_zero_execution_tenant",
            kpis_empty.executions_today == 0 and kpis_empty.success_rate == 100.0,
            f"rate={kpis_empty.success_rate}",
        )

        # Index presence
        idx = (
            await db.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_tenant_automation_executions_dedup'"
                ),
            )
        ).first()
        record("dedup_unique_index_present", idx is not None)

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll reliability checks passed")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
