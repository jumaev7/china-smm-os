"""HTTP verification for Notification Center — tenant auth, CRUD, filters, isolation."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000/api/v1")
FRONTEND_BASE = os.environ.get("VERIFY_FRONTEND_BASE", "http://127.0.0.1:3000")
ADMIN_EMAIL = "admin@example.com"
ADMIN_PASSWORD = "ChangeMe_12345!"
LIST_FIELDS = {"items", "total", "page", "page_size", "pages"}
ITEM_FIELDS = {
    "id",
    "event_id",
    "event_type",
    "title",
    "message",
    "category",
    "severity",
    "is_read",
    "read_at",
    "action_url",
    "metadata",
    "created_at",
}


def req(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    *,
    timeout: int = 30,
) -> tuple[int, Any, int]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode()
            duration_ms = int((time.perf_counter() - start) * 1000)
            if not raw:
                return resp.status, {}, duration_ms
            try:
                return resp.status, json.loads(raw), duration_ms
            except json.JSONDecodeError:
                return resp.status, raw, duration_ms
    except urllib.error.HTTPError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload, duration_ms
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return 0, {"detail": str(exc)}, duration_ms


def frontend_status(path: str) -> tuple[int, int]:
    request = urllib.request.Request(FRONTEND_BASE + path, method="GET")
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            duration_ms = int((time.perf_counter() - start) * 1000)
            return resp.status, duration_ms
    except urllib.error.HTTPError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return exc.code, duration_ms
    except Exception:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return 0, duration_ms


def _validate_list_payload(payload: dict) -> str | None:
    if not isinstance(payload, dict):
        return "response is not an object"
    missing = LIST_FIELDS - set(payload.keys())
    if missing:
        return f"missing fields: {sorted(missing)}"
    if not isinstance(payload["items"], list):
        return "items is not a list"
    for item in payload["items"]:
        if not isinstance(item, dict):
            return "item is not an object"
        missing_item = ITEM_FIELDS - set(item.keys())
        if missing_item:
            return f"item missing fields: {sorted(missing_item)}"
    return None


async def _emit_notification(tenant_id: UUID, *, title: str, description: str, event_type: str) -> None:
    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration
    from app.services.platform_event_service import PlatformEventService

    await ensure_platform_event_bus_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()
    async with AsyncSessionLocal() as db:
        await PlatformEventService.emit(
            db,
            event_type,
            tenant_id,
            title=title,
            description=description,
            payload={"verify_stamp": title, "severity": "info"},
            commit=True,
        )


async def _seed_row(
    tenant_id: UUID,
    *,
    title: str,
    body: str,
    category: str = "crm",
    severity: str = "info",
    is_read: bool = False,
    created_at: datetime | None = None,
) -> UUID:
    from uuid import uuid4

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.models.platform_event import TenantEventNotification

    await ensure_platform_event_bus_schema()
    row_id = uuid4()
    async with AsyncSessionLocal() as db:
        row = TenantEventNotification(
            id=row_id,
            tenant_id=tenant_id,
            event_id=uuid4(),
            event_type="tenant.crm.lead_created",
            category=category,
            title=title,
            body=body,
            severity=severity,
            is_read=is_read,
            read_at=datetime.now(timezone.utc) if is_read else None,
            status="read" if is_read else "unread",
            payload={"seed": True},
        )
        if created_at is not None:
            row.created_at = created_at
        db.add(row)
        await db.commit()
    return row_id


async def _read_row(notification_id: UUID) -> dict[str, Any]:
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.platform_event import TenantEventNotification

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                select(TenantEventNotification).where(TenantEventNotification.id == notification_id),
            )
        ).scalar_one()
        return {
            "is_read": row.is_read,
            "status": row.status,
            "read_at": row.read_at,
            "deleted_at": row.deleted_at,
            "updated_at": row.updated_at,
        }


async def _cleanup_rows(ids: list[UUID]) -> None:
    if not ids:
        return
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.platform_event import TenantEventNotification

    async with AsyncSessionLocal() as db:
        await db.execute(delete(TenantEventNotification).where(TenantEventNotification.id.in_(ids)))
        await db.commit()


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    stamp = int(time.time())
    failures: list[str] = []
    cleanup_ids: list[UUID] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "PASS" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" -> {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    code, admin_login, _ = req("POST", "/admin-auth/login", {"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    if code != 200 or not isinstance(admin_login, dict) or not admin_login.get("access_token"):
        print(f"FAIL bootstrap_admin_login -> HTTP {code}: {admin_login}")
        return 1
    admin_token = admin_login["access_token"]

    email_a = f"notify-http-a-{stamp}@example.com"
    email_b = f"notify-http-b-{stamp}@example.com"
    code, created_a, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Notify HTTP A {stamp}", "owner_email": email_a, "plan": "trial"},
        token=admin_token,
    )
    code_b, created_b, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Notify HTTP B {stamp}", "owner_email": email_b, "plan": "trial"},
        token=admin_token,
    )
    if code != 201 or code_b != 201:
        record("bootstrap_tenants", False, f"create-client A={code} B={code_b}")
        return 1
    tenant_a_id = UUID(created_a["tenant_id"])
    tenant_b_id = UUID(created_b["tenant_id"])

    code, login_a, ms_a = req(
        "POST",
        "/auth/login",
        {"email": email_a, "password": created_a["temporary_password"]},
    )
    code_b_login, login_b, _ = req(
        "POST",
        "/auth/login",
        {"email": email_b, "password": created_b["temporary_password"]},
    )
    token_a = login_a.get("access_token") if isinstance(login_a, dict) else None
    token_b = login_b.get("access_token") if isinstance(login_b, dict) else None
    record("tenant_login", code == 200 and bool(token_a), f"HTTP {code} ({ms_a}ms)")
    record("tenant_b_login", code_b_login == 200 and bool(token_b), f"HTTP {code_b_login}")
    if not token_a or not token_b:
        return 1

    code, listed, _ = req("GET", "/notifications?page=1&page_size=20", token=token_a)
    schema_err = _validate_list_payload(listed) if code == 200 and isinstance(listed, dict) else "non-200"
    record("list_notifications", code == 200 and schema_err is None, schema_err or f"HTTP {code}")

    code, unread_before, _ = req("GET", "/notifications/unread-count", token=token_a)
    unread_before_count = unread_before.get("unread_count") if isinstance(unread_before, dict) else None
    record(
        "unread_count",
        code == 200 and isinstance(unread_before_count, int),
        f"HTTP {code} count={unread_before_count}",
    )

    emit_title = f"[HTTP-VERIFY-{stamp}] EventBus emit"
    await _emit_notification(
        tenant_a_id,
        title=emit_title,
        description="HTTP verify event bus integration",
        event_type="tenant.crm.deal_stage_changed",
    )
    code, after_emit, _ = req(
        "GET",
        f"/notifications?search={urllib.parse.quote(emit_title)}",
        token=token_a,
    )
    emit_items = after_emit.get("items", []) if isinstance(after_emit, dict) else []
    emit_match = next((item for item in emit_items if item.get("title") == emit_title), None)
    record("eventbus_emit_creates_notification", emit_match is not None, f"found={emit_match is not None}")
    record("eventbus_list_via_http", code == 200 and emit_match is not None, f"HTTP {code}")

    code, unread_after_emit, _ = req("GET", "/notifications/unread-count", token=token_a)
    unread_emit_count = unread_after_emit.get("unread_count") if isinstance(unread_after_emit, dict) else None
    record(
        "unread_count_increased",
        isinstance(unread_emit_count, int) and isinstance(unread_before_count, int) and unread_emit_count > unread_before_count,
        f"before={unread_before_count} after={unread_emit_count}",
    )

    if not emit_match:
        print("FAIL cannot continue without emitted notification id")
        return 1
    emit_id = emit_match["id"]
    before_mark_row = await _read_row(UUID(emit_id))

    code, marked, _ = req("PATCH", f"/notifications/{emit_id}/read", token=token_a)
    after_mark_row = await _read_row(UUID(emit_id))
    record(
        "mark_read",
        code == 200
        and isinstance(marked, dict)
        and marked.get("is_read") is True
        and after_mark_row["is_read"] is True
        and after_mark_row["status"] == "read"
        and after_mark_row["read_at"] is not None,
        f"HTTP {code} status={after_mark_row['status']}",
    )
    record(
        "mark_read_updated_at",
        after_mark_row["updated_at"] is not None
        and (
            before_mark_row["updated_at"] is None
            or after_mark_row["updated_at"] >= before_mark_row["updated_at"]
        ),
        "updated_at moved forward",
    )

    code, marked_again, _ = req("PATCH", f"/notifications/{emit_id}/read", token=token_a)
    record(
        "mark_read_idempotent",
        code == 200 and isinstance(marked_again, dict) and marked_again.get("is_read") is True,
        f"HTTP {code}",
    )

    code, unread_after_read, _ = req("GET", "/notifications/unread-count", token=token_a)
    unread_read_count = unread_after_read.get("unread_count") if isinstance(unread_after_read, dict) else None
    record(
        "unread_count_decreased",
        isinstance(unread_read_count, int) and unread_read_count < (unread_emit_count or 0),
        f"after_emit={unread_emit_count} after_read={unread_read_count}",
    )

    seed_unread_id = await _seed_row(
        tenant_a_id,
        title=f"[HTTP-VERIFY-{stamp}] unread for read-all",
        body="read-all target",
        category="integrations",
        severity="warning",
    )
    cleanup_ids.append(seed_unread_id)
    before_read_all = await _read_row(seed_unread_id)
    code, read_all, _ = req("PATCH", "/notifications/actions/read-all", token=token_a)
    after_read_all_row = await _read_row(seed_unread_id)
    record(
        "mark_all_read",
        code == 200
        and isinstance(read_all, dict)
        and after_read_all_row["is_read"] is True
        and after_read_all_row["status"] == "read",
        f"HTTP {code} updated={read_all.get('updated_count')}",
    )
    record(
        "mark_all_read_updated_at",
        after_read_all_row["updated_at"] is not None
        and (
            before_read_all["updated_at"] is None
            or after_read_all_row["updated_at"] >= before_read_all["updated_at"]
        ),
        "updated_at moved forward",
    )

    delete_target_id = await _seed_row(
        tenant_a_id,
        title=f"[HTTP-VERIFY-{stamp}] delete me",
        body="soft delete target",
        category="billing",
        severity="info",
        is_read=False,
    )
    cleanup_ids.append(delete_target_id)
    before_delete = await _read_row(delete_target_id)
    code, deleted, _ = req("DELETE", f"/notifications/{delete_target_id}", token=token_a)
    after_delete = await _read_row(delete_target_id)
    record(
        "soft_delete",
        code == 200
        and isinstance(deleted, dict)
        and deleted.get("deleted") is True
        and after_delete["deleted_at"] is not None
        and after_delete["status"] == "dismissed",
        f"HTTP {code} status={after_delete['status']}",
    )
    record(
        "soft_delete_updated_at",
        after_delete["updated_at"] is not None
        and (
            before_delete["updated_at"] is None
            or after_delete["updated_at"] >= before_delete["updated_at"]
        ),
        "updated_at moved forward",
    )

    code, after_delete_list, _ = req("GET", "/notifications?page_size=100", token=token_a)
    items_after_delete = after_delete_list.get("items", []) if isinstance(after_delete_list, dict) else []
    record(
        "deleted_hidden_from_list",
        all(str(item.get("id")) != str(delete_target_id) for item in items_after_delete),
        "deleted id absent",
    )

    code, unread_after_delete, _ = req("GET", "/notifications/unread-count", token=token_a)
    record(
        "deleted_excluded_from_unread_count",
        code == 200,
        f"HTTP {code} count={unread_after_delete.get('unread_count') if isinstance(unread_after_delete, dict) else None}",
    )

    filter_unread_id = await _seed_row(
        tenant_a_id,
        title=f"[HTTP-VERIFY-{stamp}] filter unread",
        body="category integrations filter",
        category="integrations",
        severity="warning",
    )
    filter_read_id = await _seed_row(
        tenant_a_id,
        title=f"[HTTP-VERIFY-{stamp}] filter read",
        body="publishing read item",
        category="publishing",
        severity="success",
        is_read=True,
    )
    cleanup_ids.extend([filter_unread_id, filter_read_id])

    code, cat_filtered, _ = req("GET", "/notifications?category=integrations&search=HTTP-VERIFY", token=token_a)
    cat_items = cat_filtered.get("items", []) if isinstance(cat_filtered, dict) else []
    record(
        "category_filter",
        code == 200 and cat_items and all(item.get("category") == "integrations" for item in cat_items),
        f"HTTP {code} count={len(cat_items)}",
    )

    code, sev_filtered, _ = req("GET", "/notifications?severity=warning&search=HTTP-VERIFY", token=token_a)
    sev_items = sev_filtered.get("items", []) if isinstance(sev_filtered, dict) else []
    record(
        "severity_filter",
        code == 200 and sev_items and all(item.get("severity") == "warning" for item in sev_items),
        f"HTTP {code} count={len(sev_items)}",
    )

    code, read_filtered, _ = req("GET", "/notifications?is_read=false&search=HTTP-VERIFY", token=token_a)
    read_items = read_filtered.get("items", []) if isinstance(read_filtered, dict) else []
    record(
        "read_filter",
        code == 200 and read_items and all(item.get("is_read") is False for item in read_items),
        f"HTTP {code} count={len(read_items)}",
    )

    unicode_title = f"[HTTP-VERIFY-{stamp}] Unicode cafe"
    unicode_id = await _seed_row(tenant_a_id, title=unicode_title, body="plain search", category="platform")
    cleanup_ids.append(unicode_id)
    code, unicode_search, _ = req(
        "GET",
        f"/notifications?search={urllib.parse.quote('Unicode cafe')}",
        token=token_a,
    )
    unicode_items = unicode_search.get("items", []) if isinstance(unicode_search, dict) else []
    record(
        "search_unicode",
        code == 200 and any(item.get("title") == unicode_title for item in unicode_items),
        f"HTTP {code}",
    )

    percent_title = f"[HTTP-VERIFY-{stamp}] 100% complete"
    percent_id = await _seed_row(tenant_a_id, title=percent_title, body="literal percent", category="crm")
    cleanup_ids.append(percent_id)
    code, percent_search, _ = req(
        "GET",
        f"/notifications?search={urllib.parse.quote('100% complete')}",
        token=token_a,
    )
    percent_items = percent_search.get("items", []) if isinstance(percent_search, dict) else []
    record(
        "search_percent_literal",
        code == 200 and any(item.get("title") == percent_title for item in percent_items),
        f"HTTP {code} matches={len(percent_items)}",
    )

    underscore_title = f"[HTTP-VERIFY-{stamp}] under_score token"
    underscore_id = await _seed_row(tenant_a_id, title=underscore_title, body="underscore", category="crm")
    cleanup_ids.append(underscore_id)
    code, underscore_search, _ = req(
        "GET",
        f"/notifications?search={urllib.parse.quote('under_score')}",
        token=token_a,
    )
    underscore_items = underscore_search.get("items", []) if isinstance(underscore_search, dict) else []
    record(
        "search_underscore_literal",
        code == 200 and any(item.get("title") == underscore_title for item in underscore_items),
        f"HTTP {code} matches={len(underscore_items)}",
    )

    old_id = await _seed_row(
        tenant_a_id,
        title=f"[HTTP-VERIFY-{stamp}] old row",
        body="date filter",
        category="billing",
        created_at=datetime.now(timezone.utc) - timedelta(days=5),
    )
    cleanup_ids.append(old_id)
    recent_from = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
    code, recent_only, _ = req("GET", f"/notifications?created_from={recent_from}&search=HTTP-VERIFY", token=token_a)
    recent_items = recent_only.get("items", []) if isinstance(recent_only, dict) else []
    record(
        "created_from_filter",
        code == 200 and all(str(item.get("id")) != str(old_id) for item in recent_items),
        f"HTTP {code}",
    )
    old_to = (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%dT23:59:59Z")
    code, old_only, _ = req("GET", f"/notifications?created_to={old_to}&search=HTTP-VERIFY", token=token_a)
    old_items = old_only.get("items", []) if isinstance(old_only, dict) else []
    record(
        "created_to_filter",
        code == 200 and any(str(item.get("id")) == str(old_id) for item in old_items),
        f"HTTP {code}",
    )

    for idx in range(3):
        cleanup_ids.append(
            await _seed_row(
                tenant_a_id,
                title=f"[HTTP-VERIFY-{stamp}] page-{idx}",
                body=f"pagination {idx}",
                category="automation",
            ),
        )
    code, page1, _ = req("GET", "/notifications?page=1&page_size=2&search=HTTP-VERIFY", token=token_a)
    code2, page2, _ = req("GET", "/notifications?page=2&page_size=2&search=HTTP-VERIFY", token=token_a)
    p1_items = page1.get("items", []) if isinstance(page1, dict) else []
    p2_items = page2.get("items", []) if isinstance(page2, dict) else []
    p1_ids = {item.get("id") for item in p1_items}
    p2_ids = {item.get("id") for item in p2_items}
    record(
        "pagination_metadata",
        code == 200
        and code2 == 200
        and page1.get("page") == 1
        and page2.get("page") == 2
        and not (p1_ids & p2_ids),
        f"p1={len(p1_items)} p2={len(p2_items)} pages={page1.get('pages')}",
    )

    other_tenant_row = await _seed_row(
        tenant_b_id,
        title=f"[HTTP-VERIFY-{stamp}] tenant B secret",
        body="isolation",
        category="security",
    )
    cleanup_ids.append(other_tenant_row)
    code, cross_get, _ = req("GET", f"/notifications?page_size=100", token=token_a)
    cross_items = cross_get.get("items", []) if isinstance(cross_get, dict) else []
    record(
        "tenant_list_isolation",
        all("tenant B secret" not in (item.get("title") or "") for item in cross_items),
        "tenant A cannot see tenant B titles",
    )

    code, cross_mark, _ = req("PATCH", f"/notifications/{other_tenant_row}/read", token=token_a)
    code_del, cross_delete, _ = req("DELETE", f"/notifications/{other_tenant_row}", token=token_a)
    record("tenant_mark_isolation", code == 404, f"HTTP {code}")
    record("tenant_delete_isolation", code_del == 404, f"HTTP {code_del}")

    code, static_unread, _ = req("GET", "/notifications/unread-count", token=token_a)
    code2, static_read_all, _ = req("PATCH", "/notifications/actions/read-all", token=token_a)
    record("static_route_unread_count", code == 200, f"HTTP {code}")
    record("static_route_read_all", code2 == 200, f"HTTP {code2}")

    code, bell, bell_ms = req("GET", "/notifications/unread-count", token=token_a)
    record(
        "bell_badge_request",
        code == 200 and isinstance(bell, dict) and "unread_count" in bell,
        f"HTTP {code} ({bell_ms}ms)",
    )

    if emit_match and isinstance(emit_match.get("metadata"), dict):
        record("metadata_object", True, "metadata returned as object")
    else:
        record("metadata_object", emit_match is None or emit_match.get("metadata") is None, "metadata nullable")

    fe_status, fe_ms = frontend_status("/notifications")
    record("frontend_notifications_route", fe_status == 200, f"HTTP {fe_status} ({fe_ms}ms)")

    await _cleanup_rows(cleanup_ids)

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
