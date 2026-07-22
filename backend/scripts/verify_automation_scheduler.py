"""Verify Automation Scheduler Phase 1 migration + schema."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
PREV = "20260903_automation_reliability"
SCHEDULER = "20260904_automation_scheduler"
HEAD = "20260911_measurement_foundation"


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

    heads = _alembic("heads")
    record("alembic_one_head", heads.returncode == 0 and (heads.stdout or "").count(HEAD) >= 1, (heads.stdout or "")[:200])
    record("alembic_only_one_head_line", (heads.stdout or "").count("(head)") == 1, (heads.stdout or "")[:200])

    up = _alembic("upgrade", "head")
    record("upgrade_head", up.returncode == 0, (up.stderr or up.stdout)[-400:])
    cur = _alembic("current")
    record("current_is_head", HEAD in (cur.stdout or ""), (cur.stdout or "")[:200])

    down = _alembic("downgrade", PREV)
    record("downgrade_to_reliability", down.returncode == 0, (down.stderr or down.stdout)[-400:])

    async with AsyncSessionLocal() as db:
        exists_after_down = (
            await db.execute(text("SELECT to_regclass('public.tenant_automation_jobs')"))
        ).scalar_one()
        record("jobs_table_removed_on_downgrade", exists_after_down is None, str(exists_after_down))

    up2 = _alembic("upgrade", "head")
    record("reupgrade_head", up2.returncode == 0, (up2.stderr or up2.stdout)[-400:])

    down_base = _alembic("downgrade", "base")
    record("downgrade_base", down_base.returncode == 0, (down_base.stderr or down_base.stdout)[-400:])
    up3 = _alembic("upgrade", "head")
    record("upgrade_from_base", up3.returncode == 0, (up3.stderr or up3.stdout)[-400:])
    cur2 = _alembic("current")
    record("current_equals_head", HEAD in (cur2.stdout or ""), (cur2.stdout or "")[:200])
    heads2 = _alembic("heads")
    record("heads_single", (heads2.stdout or "").count("(head)") == 1, (heads2.stdout or "")[:200])

    await ensure_platform_event_bus_schema()
    async with AsyncSessionLocal() as db:
        exists = (
            await db.execute(text("SELECT to_regclass('public.tenant_automation_jobs')"))
        ).scalar_one()
        record("jobs_table_exists", exists is not None)

        cols = (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_automation_jobs'"
                ),
            )
        ).scalars().all()
        colset = set(cols)
        for required in (
            "deduplication_key",
            "scheduled_for",
            "available_at",
            "lease_owner",
            "lease_expires_at",
            "lease_recovery_count",
            "job_kind",
            "status",
            "payload",
        ):
            record(f"column_{required}", required in colset)

        indexes = (
            await db.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE tablename = 'tenant_automation_jobs'"
                ),
            )
        ).scalars().all()
        idxset = set(indexes)
        record("uq_dedup_index", "uq_tenant_automation_jobs_dedup" in idxset, str(sorted(idxset)[:8]))
        record("claim_index", "ix_tenant_automation_jobs_claim" in idxset)

    print("")
    if failures:
        print(f"FAILED {len(failures)} checks")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
