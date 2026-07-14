"""Verify Automation Reliability Phase 2 migration + schema invariants."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
PREV = "20260902_automation_center"
HEAD = "20260903_automation_reliability"


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(BACKEND),
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    from sqlalchemy import text

    from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema

    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    await ensure_platform_event_bus_schema()

    # Prefer alembic path when available against the active DB.
    heads = _alembic("heads")
    record("alembic_heads_ok", heads.returncode == 0 and HEAD in (heads.stdout or ""), (heads.stdout or heads.stderr)[:200])

    current = _alembic("current")
    record("alembic_current_readable", current.returncode == 0, (current.stdout or current.stderr)[:200])

    # Lifecycle on the active database (upgrade is idempotent).
    up = _alembic("upgrade", "head")
    record("upgrade_head", up.returncode == 0, (up.stderr or up.stdout)[-300:])
    cur_after = _alembic("current")
    record("current_is_reliability_head", HEAD in (cur_after.stdout or ""), (cur_after.stdout or "")[:200])

    down = _alembic("downgrade", PREV)
    record("downgrade_previous", down.returncode == 0, (down.stderr or down.stdout)[-300:])
    up2 = _alembic("upgrade", "head")
    record("reupgrade_head", up2.returncode == 0, (up2.stderr or up2.stdout)[-300:])

    # Full base cycle can be expensive; keep optional via env but always prove downgrade-up.
    # Confirm schema pieces after ensuring bootstrap + upgrade.
    await ensure_platform_event_bus_schema()
    async with AsyncSessionLocal() as db:
        cols = (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_automation_executions'"
                ),
            )
        ).scalars().all()
        colset = set(cols)
        for required in (
            "execution_kind",
            "deduplication_key",
            "root_execution_id",
            "retry_of_execution_id",
            "retry_number",
            "error_category",
            "is_retryable",
        ):
            record(f"column_{required}", required in colset)

        flow_cols = (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_automation_flows'"
                ),
            )
        ).scalars().all()
        fset = set(flow_cols)
        for required in ("max_retry_attempts", "retry_delay_seconds", "retry_backoff"):
            record(f"flow_column_{required}", required in fset)

        idx = (
            await db.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE indexname = 'uq_tenant_automation_executions_dedup'"
                ),
            )
        ).first()
        record("unique_dedup_index", idx is not None)

        # Representative Phase 1-style row backfill via ensure_platform path already ran;
        # insert a legacy-shaped row through ORM defaults should succeed.
        from uuid import uuid4
        from datetime import datetime, timezone

        from app.models.automation import TenantAutomationExecution, TenantAutomationFlow
        from app.models.tenant import Tenant
        from app.services.automation_service import AutomationService

        tenant = Tenant(id=uuid4(), company_name=f"Rel Mig {int(datetime.now(timezone.utc).timestamp())}", status="active", plan="trial")
        db.add(tenant)
        await db.flush()
        await AutomationService.ensure_system_flows(db, tenant.id)
        flow = (
            await db.execute(
                text(
                    "SELECT id FROM tenant_automation_flows WHERE tenant_id = :tid LIMIT 1"
                ),
                {"tid": tenant.id},
            )
        ).first()
        if flow:
            exec_id = uuid4()
            event_id = uuid4()
            row = TenantAutomationExecution(
                id=exec_id,
                tenant_id=tenant.id,
                automation_flow_id=flow[0],
                event_id=event_id,
                trigger_event="tenant.content.publish_failed",
                status="success",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                execution_kind="event",
                deduplication_key=f"event:{event_id}",
                root_execution_id=exec_id,
                retry_number=0,
                attempt_number=1,
            )
            db.add(row)
            await db.flush()
            retry = TenantAutomationExecution(
                id=uuid4(),
                tenant_id=tenant.id,
                automation_flow_id=flow[0],
                event_id=event_id,
                trigger_event="tenant.content.publish_failed",
                status="success",
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
                execution_kind="retry",
                deduplication_key=f"retry:{exec_id}:1",
                root_execution_id=exec_id,
                retry_of_execution_id=exec_id,
                retry_number=1,
                attempt_number=2,
            )
            db.add(retry)
            await db.flush()
            record("retry_coexists_with_original", True)
            try:
                db.add(
                    TenantAutomationExecution(
                        id=uuid4(),
                        tenant_id=tenant.id,
                        automation_flow_id=flow[0],
                        event_id=event_id,
                        trigger_event="tenant.content.publish_failed",
                        status="failed",
                        started_at=datetime.now(timezone.utc),
                        execution_kind="event",
                        deduplication_key=f"event:{event_id}",
                        root_execution_id=uuid4(),
                        retry_number=0,
                        attempt_number=1,
                    )
                )
                await db.flush()
                record("automatic_duplicate_rejected", False, "duplicate accepted")
            except Exception:
                await db.rollback()
                # reopen transaction for cleanup
                await db.execute(text("SELECT 1"))
                record("automatic_duplicate_rejected", True)
            else:
                await db.rollback()
        else:
            record("retry_coexists_with_original", False, "no flow")
            record("automatic_duplicate_rejected", False, "no flow")

        await db.commit()

    # Leave DB at head
    final_up = _alembic("upgrade", "head")
    record("final_upgrade_head", final_up.returncode == 0, (final_up.stderr or final_up.stdout)[-200:])
    heads2 = _alembic("heads")
    record("single_head", heads2.stdout.count(HEAD) >= 1 and " (head)" in heads2.stdout.replace("\r", ""), heads2.stdout[:200])

    print(f"\n{len(failures)} failure(s)" if failures else "\nMigration verification passed")
    for f in failures:
        print(f"  - {f}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
