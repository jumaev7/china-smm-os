"""Verify Publishing Intelligence migration + schema lifecycle."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
PREV = "20260906_marketing_intelligence"
HEAD = "20260911_measurement_foundation"

PI_TABLES = (
    "tenant_publishing_reviews",
    "tenant_publishing_review_checks",
    "tenant_publishing_platform_reviews",
)

MIP_TABLES = (
    "tenant_marketing_signals",
    "tenant_marketing_scores",
    "tenant_marketing_recommendations",
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

    from app.core.database import (
        AsyncSessionLocal,
        ensure_intelligence_schema,
        ensure_publishing_intelligence_schema,
    )

    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    await ensure_intelligence_schema()
    await ensure_publishing_intelligence_schema()

    heads = _alembic("heads")
    record("alembic_one_head", heads.returncode == 0 and HEAD in (heads.stdout or ""), (heads.stdout or "")[:200])
    record("alembic_only_one_head_line", (heads.stdout or "").count("(head)") == 1, (heads.stdout or "")[:200])

    up = _alembic("upgrade", "head")
    record("upgrade_head", up.returncode == 0, (up.stderr or up.stdout)[-400:])
    cur = _alembic("current")
    record("current_is_pi_head", HEAD in (cur.stdout or ""), (cur.stdout or "")[:200])

    down = _alembic("downgrade", PREV)
    record("downgrade_to_mip", down.returncode == 0, (down.stderr or down.stdout)[-400:])

    async with AsyncSessionLocal() as db:
        for table in PI_TABLES:
            exists_after_down = (
                await db.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            record(f"{table}_removed_on_downgrade", exists_after_down is None, str(exists_after_down))
        for table in MIP_TABLES:
            exists = (
                await db.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            record(f"{table}_kept_after_pi_downgrade", exists is not None)

    up2 = _alembic("upgrade", "head")
    record("reupgrade_head", up2.returncode == 0, (up2.stderr or up2.stdout)[-400:])

    down_base = _alembic("downgrade", "base")
    record("downgrade_base", down_base.returncode == 0, (down_base.stderr or down_base.stdout)[-400:])
    up3 = _alembic("upgrade", "head")
    record("upgrade_from_base", up3.returncode == 0, (up3.stderr or up3.stdout)[-400:])

    await ensure_publishing_intelligence_schema()
    async with AsyncSessionLocal() as db:
        for table in PI_TABLES:
            exists = (
                await db.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            record(f"{table}_exists", exists is not None)

        cols = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tenant_publishing_reviews'"
                    ),
                )
            ).scalars().all()
        )
        for required in (
            "tenant_id",
            "content_id",
            "review_version",
            "content_fingerprint",
            "overall_score",
            "status",
            "summary",
        ):
            record(f"review_col_{required}", required in cols)

    cur2 = _alembic("current")
    heads2 = _alembic("heads")
    record("final_current_equals_head", HEAD in (cur2.stdout or "") and HEAD in (heads2.stdout or ""))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
