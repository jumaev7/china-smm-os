"""HTTP verification for Automation Reliability Phase 2 — retry API, isolation, KPIs."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_http_bootstrap import ensure_admin_token  # noqa: E402

BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000/api/v1")


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


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.models.automation import TenantAutomationExecution, TenantAutomationFlow
    from app.services.automation_execution_service import event_deduplication_key
    from app.services.automation_service import AutomationService
    from app.services.event_handlers.registration import (
        register_event_bus_subscribers,
        reset_event_bus_registration,
    )

    run_id = f"{int(time.time())}-{uuid.uuid4().hex[:8]}"
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "PASS" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" -> {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    await ensure_platform_event_bus_schema()
    reset_event_bus_registration()
    register_event_bus_subscribers()

    admin_token, bootstrap_detail = await ensure_admin_token(req)
    record("bootstrap_admin", bool(admin_token), bootstrap_detail)
    if not admin_token:
        print("\nReliability HTTP verification failed — admin bootstrap unavailable")
        return 1

    email_a = f"rel-http-a-{run_id}@example.com"
    email_b = f"rel-http-b-{run_id}@example.com"

    code, created_a, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Rel HTTP A {run_id}", "owner_email": email_a, "plan": "trial"},
        token=admin_token,
    )
    code_b, created_b, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Rel HTTP B {run_id}", "owner_email": email_b, "plan": "trial"},
        token=admin_token,
    )
    if code != 201 or code_b != 201 or not isinstance(created_a, dict) or not isinstance(created_b, dict):
        record("bootstrap_tenants", False, f"A={code} B={code_b}")
        return 1
    record("bootstrap_tenants", True, f"run_id={run_id}")

    temp_a = created_a.get("temporary_password")
    temp_b = created_b.get("temporary_password")
    tenant_a_id = created_a.get("tenant_id")
    if not temp_a or not temp_b or not tenant_a_id:
        record("bootstrap_temp_passwords", False, "missing temporary_password or tenant_id")
        return 1

    code, login_a, _ = req("POST", "/auth/login", {"email": email_a, "password": temp_a})
    code_b_login, login_b, _ = req("POST", "/auth/login", {"email": email_b, "password": temp_b})
    token_a = login_a.get("access_token") if isinstance(login_a, dict) else None
    token_b = login_b.get("access_token") if isinstance(login_b, dict) else None
    record("tenant_login", code == 200 and bool(token_a), f"HTTP {code}")
    record("tenant_b_login", code_b_login == 200 and bool(token_b), f"HTTP {code_b_login}")
    if not token_a or not token_b:
        return 1

    code, flows, _ = req("GET", "/automation", token=token_a)
    record("list_flows", code == 200 and isinstance(flows, dict) and flows.get("total", 0) >= 4, f"code={code}")
    partial = next(
        (f for f in (flows.get("items") or []) if f.get("key") == "system_publish_partial_failed_notify"),
        None,
    ) if isinstance(flows, dict) else None
    record("partial_flow_present", partial is not None)

    code, kpis, _ = req("GET", "/automation/kpis", token=token_a)
    record(
        "kpis_reliability_fields",
        code == 200
        and isinstance(kpis, dict)
        and "retry_count_today" in kpis
        and "partial_publish_failures_today" in kpis
        and "success_rate" in kpis,
        f"keys={sorted(kpis.keys()) if isinstance(kpis, dict) else code}",
    )

    failed_exec_id = None
    non_retry_id = None
    async with AsyncSessionLocal() as db:
        from uuid import UUID

        tid = UUID(str(tenant_a_id))
        await AutomationService.ensure_system_flows(db, tid)
        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.tenant_id == tid,
                    TenantAutomationFlow.key == "system_publish_failed_notify",
                ),
            )
        ).scalar_one()
        flow.max_retry_attempts = 1
        failed_exec_id = uuid.uuid4()
        event_id = uuid.uuid4()
        failed = TenantAutomationExecution(
            id=failed_exec_id,
            tenant_id=tid,
            automation_flow_id=flow.id,
            event_id=event_id,
            trigger_event="tenant.content.publish_failed",
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            input_payload={"resource_name": "HTTP retry target"},
            error_code="execution_error",
            error_message="http verify boom",
            error_category="internal",
            is_retryable=True,
            execution_kind="event",
            deduplication_key=event_deduplication_key(event_id),
            root_execution_id=failed_exec_id,
            retry_number=0,
            attempt_number=1,
        )
        non_retry_id = uuid.uuid4()
        non_retry = TenantAutomationExecution(
            id=non_retry_id,
            tenant_id=tid,
            automation_flow_id=flow.id,
            event_id=uuid.uuid4(),
            trigger_event="tenant.content.publish_failed",
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            input_payload={},
            error_code="invalid_config",
            error_message="bad",
            error_category="validation",
            is_retryable=False,
            execution_kind="event",
            deduplication_key=f"event:{uuid.uuid4()}",
            root_execution_id=non_retry_id,
            retry_number=0,
            attempt_number=1,
        )
        db.add_all([failed, non_retry])
        await db.commit()

    record("seed_failed_execution", bool(failed_exec_id), str(failed_exec_id))

    code, detail, _ = req("GET", f"/automation/executions/{failed_exec_id}", token=token_a)
    record(
        "execution_detail",
        code == 200
        and isinstance(detail, dict)
        and detail.get("retry_eligible") is True
        and detail.get("execution_kind") == "event",
        f"code={code} eligible={detail.get('retry_eligible') if isinstance(detail, dict) else None}",
    )

    code, _wrong, _ = req("GET", f"/automation/executions/{failed_exec_id}", token=token_b)
    record("wrong_tenant_detail_404", code == 404, f"code={code}")

    code, _wrong_retry, _ = req(
        "POST",
        f"/automation/executions/{failed_exec_id}/retry",
        token=token_b,
    )
    record("wrong_tenant_retry_404", code == 404, f"code={code}")

    code, retry_body, _ = req(
        "POST",
        f"/automation/executions/{failed_exec_id}/retry",
        token=token_a,
    )
    record(
        "retry_endpoint",
        code == 200
        and isinstance(retry_body, dict)
        and retry_body.get("execution_kind") == "retry"
        and retry_body.get("retry_of_execution_id") == str(failed_exec_id)
        and retry_body.get("root_execution_id") == str(failed_exec_id),
        f"code={code} body={retry_body if isinstance(retry_body, dict) else retry_body}",
    )

    code, orig, _ = req("GET", f"/automation/executions/{failed_exec_id}", token=token_a)
    record(
        "original_still_failed",
        code == 200 and isinstance(orig, dict) and orig.get("status") == "failed",
        f"status={orig.get('status') if isinstance(orig, dict) else code}",
    )

    code, limit_body, _ = req(
        "POST",
        f"/automation/executions/{failed_exec_id}/retry",
        token=token_a,
    )
    record(
        "retry_limit_409",
        code == 409,
        f"code={code} detail={limit_body.get('detail') if isinstance(limit_body, dict) else limit_body}",
    )

    code, nr, _ = req("POST", f"/automation/executions/{non_retry_id}/retry", token=token_a)
    record("non_retryable_409", code == 409, f"code={code} detail={nr.get('detail') if isinstance(nr, dict) else nr}")

    code, kpis2, _ = req("GET", "/automation/kpis", token=token_a)
    record(
        "kpi_refresh_after_retry",
        code == 200 and isinstance(kpis2, dict) and int(kpis2.get("retry_count_today") or 0) >= 1,
        f"retries={kpis2.get('retry_count_today') if isinstance(kpis2, dict) else None}",
    )

    code, execs, _ = req("GET", "/automation/executions?page=1&page_size=20", token=token_a)
    retry_items = [
        e for e in (execs.get("items") or [])
        if isinstance(e, dict) and e.get("execution_kind") == "retry"
    ] if isinstance(execs, dict) else []
    record("retry_history_linkage", code == 200 and len(retry_items) >= 1, f"retries={len(retry_items)}")

    code, flows2, _ = req("GET", "/automation", token=token_a)
    record(
        "repeated_list_stable",
        code == 200 and isinstance(flows2, dict) and flows2.get("total") == flows.get("total"),
        f"{flows2.get('total') if isinstance(flows2, dict) else None} vs {flows.get('total') if isinstance(flows, dict) else None}",
    )

    print(f"\n{len(failures)} failure(s)" if failures else "\nAll reliability HTTP checks passed")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
