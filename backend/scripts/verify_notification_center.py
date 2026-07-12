"""Verify Notification Center — tenant isolation, filters, mutations, EventBus integration."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    import asyncio

    return asyncio.run(_run())


async def _create_notification(
    db,
    *,
    tenant_id,
    title: str,
    body: str,
    category: str = "crm",
    severity: str = "info",
    is_read: bool = False,
    event_type: str = "tenant.crm.lead_created",
) -> "TenantEventNotification":
    from app.models.platform_event import TenantEventNotification

    row = TenantEventNotification(
        id=uuid4(),
        tenant_id=tenant_id,
        event_id=uuid4(),
        event_type=event_type,
        category=category,
        title=title,
        body=body,
        severity=severity,
        is_read=is_read,
        read_at=datetime.now(timezone.utc) if is_read else None,
        status="read" if is_read else "unread",
    )
    db.add(row)
    await db.flush()
    return row


async def _run() -> int:
    from fastapi import HTTPException

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.models.tenant import Tenant, TenantUser
    from app.services.auth_service import hash_password
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration
    from app.services.notification_service import NotificationService
    from app.services.platform_event_service import PlatformEventService

    await ensure_platform_event_bus_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []
    checks: list[dict] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        status = "passed" if ok else "failed"
        checks.append({"id": check_id, "status": status, "detail": detail})
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant_a = Tenant(
            id=uuid4(),
            company_name=f"Notify Verify A {stamp}",
            status="active",
            plan="trial",
        )
        tenant_b = Tenant(
            id=uuid4(),
            company_name=f"Notify Verify B {stamp}",
            status="active",
            plan="trial",
        )
        user_a = TenantUser(
            id=uuid4(),
            tenant_id=tenant_a.id,
            email=f"notify-a-{stamp}@example.com",
            password_hash=hash_password("test1234"),
            role="owner",
            status="active",
        )
        db.add(tenant_a)
        db.add(tenant_b)
        db.add(user_a)
        await db.commit()
        tenant_a_id = tenant_a.id
        tenant_b_id = tenant_b.id

        unread_a = await _create_notification(
            db,
            tenant_id=tenant_a_id,
            title=f"Unread CRM {stamp}",
            body="Lead assigned to pipeline",
            category="crm",
            severity="info",
        )
        read_a = await _create_notification(
            db,
            tenant_id=tenant_a_id,
            title=f"Read publishing {stamp}",
            body="Post published successfully",
            category="publishing",
            severity="success",
            is_read=True,
        )
        warn_a = await _create_notification(
            db,
            tenant_id=tenant_a_id,
            title=f"Integration warning {stamp}",
            body="Token expires soon",
            category="integrations",
            severity="warning",
        )
        await _create_notification(
            db,
            tenant_id=tenant_b_id,
            title=f"Tenant B only {stamp}",
            body="Hidden from tenant A",
            category="platform",
        )
        await db.commit()
        unread_a_id = unread_a.id
        read_a_id = read_a.id
        warn_a_id = warn_a.id

        listed = await NotificationService.list_notifications(db, tenant_a_id, page=1, page_size=50)
        record("list_tenant_a_only", listed.total >= 3, f"total={listed.total}")
        record(
            "tenant_a_no_b_titles",
            all("Tenant B only" not in (item.title or "") for item in listed.items),
            f"items={len(listed.items)}",
        )

        listed_b = await NotificationService.list_notifications(db, tenant_b_id)
        record("list_tenant_b", listed_b.total >= 1, f"total={listed_b.total}")
        record(
            "tenant_b_isolated",
            all(item.title.startswith("Tenant B") for item in listed_b.items),
            "titles isolated",
        )

        unread = await NotificationService.get_unread_count(db, tenant_a_id)
        record("unread_count", unread.unread_count >= 2, f"count={unread.unread_count}")

        by_category = await NotificationService.list_notifications(
            db, tenant_a_id, category="integrations",
        )
        record(
            "category_filter",
            all(item.category == "integrations" for item in by_category.items),
            f"count={len(by_category.items)}",
        )

        by_severity = await NotificationService.list_notifications(
            db, tenant_a_id, severity="warning",
        )
        record(
            "severity_filter",
            all(item.severity == "warning" for item in by_severity.items),
            f"count={len(by_severity.items)}",
        )

        by_read = await NotificationService.list_notifications(
            db, tenant_a_id, is_read=False,
        )
        record(
            "read_filter",
            all(not item.is_read for item in by_read.items),
            f"count={len(by_read.items)}",
        )

        search = await NotificationService.list_notifications(
            db, tenant_a_id, search="Integration warning",
        )
        record("search_filter", len(search.items) >= 1, f"count={len(search.items)}")

        page1 = await NotificationService.list_notifications(db, tenant_a_id, page=1, page_size=2)
        page2 = await NotificationService.list_notifications(db, tenant_a_id, page=2, page_size=2)
        record("pagination", page1.page == 1 and page2.page == 2, f"p1={len(page1.items)} p2={len(page2.items)}")

        marked = await NotificationService.mark_as_read(db, tenant_a_id, unread_a_id)
        record("mark_single_read", marked.is_read is True, f"id={marked.id}")

        marked_again = await NotificationService.mark_as_read(db, tenant_a_id, unread_a_id)
        record("mark_read_idempotent", marked_again.is_read is True, "second call ok")

        all_read = await NotificationService.mark_all_as_read(db, tenant_a_id)
        record("mark_all_read", all_read.updated_count >= 0, f"updated={all_read.updated_count}")
        unread_after_all = await NotificationService.get_unread_count(db, tenant_a_id)
        record("unread_zero_after_all", unread_after_all.unread_count == 0, f"count={unread_after_all.unread_count}")

        deleted = await NotificationService.delete_notification(db, tenant_a_id, read_a_id)
        record("delete_soft", deleted.deleted is True, f"id={deleted.id}")
        after_delete = await NotificationService.list_notifications(db, tenant_a_id)
        record(
            "deleted_hidden_from_list",
            all(item.id != read_a_id for item in after_delete.items),
            "deleted row absent",
        )
        unread_after_delete = await NotificationService.get_unread_count(db, tenant_a_id)
        record(
            "delete_not_in_unread_count",
            unread_after_delete.unread_count == 0,
            f"count={unread_after_delete.unread_count}",
        )

        cross_mark_failed = False
        try:
            await NotificationService.mark_as_read(db, tenant_b_id, unread_a_id)
        except HTTPException as exc:
            cross_mark_failed = exc.status_code == 404
        record("tenant_b_cannot_mark_a", cross_mark_failed, "404 on cross-tenant mark")

        cross_delete_failed = False
        try:
            await NotificationService.delete_notification(db, tenant_b_id, warn_a_id)
        except HTTPException as exc:
            cross_delete_failed = exc.status_code == 404
        record("tenant_b_cannot_delete_a", cross_delete_failed, "404 on cross-tenant delete")

        deleted_row = await NotificationService.list_notifications(db, tenant_a_id)
        record(
            "soft_deleted_absent",
            all(item.id != read_a_id for item in deleted_row.items),
            "soft-deleted hidden",
        )

        emit_tenant = uuid4()
        db.add(Tenant(id=emit_tenant, company_name=f"Notify Emit {stamp}", status="active", plan="trial"))
        await db.commit()
        await PlatformEventService.emit(
            db,
            "tenant.crm.deal_stage_changed",
            emit_tenant,
            payload={"deal_id": str(uuid4()), "from_stage": "lead", "to_stage": "qualified"},
            title="Deal moved to Qualified",
            description="Pipeline stage transition",
            commit=True,
        )
        emitted = await NotificationService.list_notifications(db, emit_tenant)
        record("eventbus_creates_notification", emitted.total >= 1, f"total={emitted.total}")

        rollback_tenant = uuid4()
        db.add(Tenant(id=rollback_tenant, company_name=f"Notify Rollback {stamp}", status="active", plan="trial"))
        await db.commit()
        await PlatformEventService.emit(
            db,
            "tenant.onboarding.platform_ready",
            rollback_tenant,
            title="Platform ready",
            description="Rollback test",
            commit=False,
        )
        await db.rollback()
        rolled = await NotificationService.list_notifications(db, rollback_tenant)
        record("commit_false_rollback", rolled.total == 0, f"total={rolled.total}")

        commit_tenant = uuid4()
        db.add(Tenant(id=commit_tenant, company_name=f"Notify Commit {stamp}", status="active", plan="trial"))
        await db.commit()
        await PlatformEventService.emit(
            db,
            "tenant.onboarding.platform_ready",
            commit_tenant,
            title="Platform ready",
            description="Commit test",
            commit=True,
        )
        committed = await NotificationService.list_notifications(db, commit_tenant)
        record("commit_true_persists", committed.total >= 1, f"total={committed.total}")

        old = await _create_notification(
            db,
            tenant_id=tenant_a_id,
            title=f"Old notification {stamp}",
            body="pagination edge",
            category="billing",
        )
        old.created_at = datetime.now(timezone.utc) - timedelta(days=3)
        await db.commit()
        ranged = await NotificationService.list_notifications(
            db,
            tenant_a_id,
            created_from=datetime.now(timezone.utc) - timedelta(days=1),
        )
        record(
            "created_from_filter",
            all(item.id != old.id for item in ranged.items),
            f"count={len(ranged.items)}",
        )

    print(f"\n{len(checks) - len(failures)}/{len(checks)} checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
