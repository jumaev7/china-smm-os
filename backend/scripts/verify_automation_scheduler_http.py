"""HTTP verification for automation scheduler APIs."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
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
    from uuid import UUID, uuid4

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
    from app.models.automation import TenantAutomationExecution, TenantAutomationFlow, TenantAutomationJob
    from app.services.automation_job_service import AutomationJobService
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
        return 1

    email = f"sched-http-{run_id}@example.com"
    code, created, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Sched HTTP {run_id}", "owner_email": email, "plan": "trial"},
        token=admin_token,
    )
    record("bootstrap_tenant", code == 201 and isinstance(created, dict), str(code))
    if code != 201 or not isinstance(created, dict):
        return 1

    temp = created.get("temporary_password")
    tenant_id = created.get("tenant_id")
    login_code, login_body, _ = req("POST", "/auth/login", {"email": email, "password": temp})
    record("login", login_code == 200 and isinstance(login_body, dict), str(login_code))
    if login_code != 200 or not isinstance(login_body, dict):
        return 1
    token = login_body["access_token"]
    tid = UUID(str(tenant_id))

    kpi_code, kpi_body, _ = req("GET", "/automation/kpis", token=token)
    record("kpis", kpi_code == 200, str(kpi_code))
    if isinstance(kpi_body, dict):
        for key in (
            "scheduled_jobs",
            "due_jobs",
            "running_jobs",
            "failed_jobs",
            "dead_letter_jobs",
            "recovered_leases_today",
            "automatic_retries_today",
            "automatic_retry_success_today",
            "average_schedule_delay_ms",
        ):
            record(f"kpi_{key}", key in kpi_body)

    list_code, list_body, _ = req("GET", "/automation/jobs", token=token)
    record("jobs_list", list_code == 200, str(list_code))

    async with AsyncSessionLocal() as db:
        await AutomationService.ensure_system_flows(db, tid)
        flow = (
            await db.execute(
                select(TenantAutomationFlow).where(
                    TenantAutomationFlow.tenant_id == tid,
                    TenantAutomationFlow.key == "system_publish_failed_notify",
                ),
            )
        ).scalar_one()
        flow.max_retry_attempts = 2
        failed = TenantAutomationExecution(
            id=uuid4(),
            tenant_id=tid,
            automation_flow_id=flow.id,
            event_id=uuid4(),
            trigger_event=flow.trigger_event,
            status="failed",
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            duration_ms=1,
            input_payload={"resource_name": "HTTP sched"},
            execution_kind="event",
            deduplication_key=f"event:{uuid4()}",
            retry_number=0,
            attempt_number=1,
            error_code="execution_error",
            error_message="http seed",
            error_category="internal",
            is_retryable=True,
        )
        failed.root_execution_id = failed.id
        db.add(failed)
        await db.commit()
        job = await AutomationJobService.enqueue_automatic_retry(db, execution=failed, flow=flow)
        await db.commit()
        job_id = str(job.id) if job else None
        flow_id = flow.id

    record("seeded_job", bool(job_id))
    if job_id:
        d_code, d_body, _ = req("GET", f"/automation/jobs/{job_id}", token=token)
        record("job_detail", d_code == 200, str(d_code))
        if isinstance(d_body, dict):
            record("safe_no_stack", "Traceback" not in str(d_body.get("error_message") or ""))
            record("safe_no_raw_payload", "payload" not in d_body or "payload_summary" in d_body)

        f_code, f_body, _ = req("GET", f"/automation/jobs?status=scheduled&flow_id={flow_id}", token=token)
        record(
            "jobs_filters",
            f_code == 200 and isinstance(f_body, dict) and int(f_body.get("total") or 0) >= 1,
            str(f_code),
        )

        c_code, c_body, _ = req("POST", f"/automation/jobs/{job_id}/cancel", token=token)
        record("cancel_scheduled", c_code == 200 and isinstance(c_body, dict) and c_body.get("status") == "cancelled")

        w_code, _, _ = req("GET", f"/automation/jobs/{uuid4()}", token=token)
        record("wrong_job_404", w_code == 404, str(w_code))

        async with AsyncSessionLocal() as db:
            dead = TenantAutomationJob(
                id=uuid4(),
                tenant_id=tid,
                automation_flow_id=flow_id,
                execution_id=failed.id,
                root_execution_id=failed.id,
                job_kind="automation_retry",
                status="dead_letter",
                scheduled_for=datetime.now(timezone.utc),
                available_at=datetime.now(timezone.utc),
                attempt_number=1,
                max_attempts=2,
                priority=100,
                deduplication_key=f"http-dl:{uuid4()}",
                error_code="lease_recovery_exceeded",
                error_message="seed dead",
                payload={},
            )
            db.add(dead)
            await db.commit()
            dead_id = str(dead.id)

        r_code, r_body, _ = req("POST", f"/automation/jobs/{dead_id}/requeue", token=token)
        record(
            "requeue_dead_letter",
            r_code == 200 and isinstance(r_body, dict) and r_body.get("status") == "scheduled",
            str(r_code),
        )

    print("")
    if failures:
        print(f"FAILED {len(failures)} checks")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
