"""Verify Workflow Builder Phase 1 migration + schema."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
PREV = "20260904_automation_scheduler"
FEATURE = "20260905_workflow_definitions"
HEAD = "20260910_campaign_planner"

WORKFLOW_TABLES = (
    "tenant_workflows",
    "tenant_workflow_versions",
    "tenant_workflow_executions",
    "tenant_workflow_step_executions",
)


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
    hist = _alembic("history", "-r", f"{PREV}:{HEAD}")
    record("workflow_revision_in_chain", FEATURE in (hist.stdout or ""), (hist.stdout or "")[:200])

    down = _alembic("downgrade", PREV)
    record("downgrade_to_scheduler", down.returncode == 0, (down.stderr or down.stdout)[-400:])

    async with AsyncSessionLocal() as db:
        for table in WORKFLOW_TABLES:
            exists_after_down = (
                await db.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            record(f"{table}_removed_on_downgrade", exists_after_down is None, str(exists_after_down))

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
        for table in WORKFLOW_TABLES:
            exists = (
                await db.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            record(f"{table}_exists", exists is not None)

        workflow_cols = (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_workflows'"
                ),
            )
        ).scalars().all()
        wf_colset = set(workflow_cols)
        for required in (
            "key",
            "name",
            "status",
            "active_version_id",
            "draft_version_id",
            "draft_revision",
            "trigger_event",
            "failure_policy",
            "archived_at",
        ):
            record(f"tenant_workflows_column_{required}", required in wf_colset)

        version_cols = (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_workflow_versions'"
                ),
            )
        ).scalars().all()
        ver_colset = set(version_cols)
        for required in (
            "workflow_id",
            "version_number",
            "state",
            "definition",
            "definition_hash",
            "validation_status",
            "validation_errors",
            "published_at",
        ):
            record(f"tenant_workflow_versions_column_{required}", required in ver_colset)

        execution_cols = (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_workflow_executions'"
                ),
            )
        ).scalars().all()
        exec_colset = set(execution_cols)
        for required in (
            "workflow_id",
            "workflow_version_id",
            "platform_event_id",
            "execution_kind",
            "deduplication_key",
            "status",
            "trigger_event",
            "matched_conditions",
            "current_step_id",
        ):
            record(f"tenant_workflow_executions_column_{required}", required in exec_colset)

        step_cols = (
            await db.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'tenant_workflow_step_executions'"
                ),
            )
        ).scalars().all()
        step_colset = set(step_cols)
        for required in (
            "workflow_execution_id",
            "step_id",
            "step_type",
            "action_type",
            "step_index",
            "status",
        ):
            record(f"tenant_workflow_step_executions_column_{required}", required in step_colset)

        indexes = (
            await db.execute(
                text(
                    "SELECT indexname FROM pg_indexes WHERE tablename IN "
                    "('tenant_workflows', 'tenant_workflow_versions', "
                    "'tenant_workflow_executions', 'tenant_workflow_step_executions')"
                ),
            )
        ).scalars().all()
        idxset = set(indexes)
        record("uq_workflows_tenant_key", "uq_tenant_workflows_tenant_key" in idxset, str(sorted(idxset)[:10]))
        record("uq_workflow_versions_number", "uq_tenant_workflow_versions_workflow_number" in idxset)
        record("uq_workflow_executions_dedup", "uq_tenant_workflow_executions_dedup" in idxset)
        record("uq_step_executions_exec_step", "uq_tenant_workflow_step_executions_exec_step" in idxset)
        record("ix_workflows_tenant_status_updated", "ix_tenant_workflows_tenant_status_updated" in idxset)
        record("ix_workflow_executions_platform_event_id", "ix_tenant_workflow_executions_platform_event_id" in idxset)

        fks = {
            row[0]
            for row in (
                await db.execute(
                    text(
                        "SELECT constraint_name FROM information_schema.table_constraints "
                        "WHERE table_name = 'tenant_workflows' AND constraint_type = 'FOREIGN KEY'"
                    ),
                )
            )
        }
        record("fk_active_version", "fk_tenant_workflows_active_version" in fks, str(sorted(fks)))
        record("fk_draft_version", "fk_tenant_workflows_draft_version" in fks)

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
