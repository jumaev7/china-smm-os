"""Verify Marketing Intelligence Platform migration + schema lifecycle."""
from __future__ import annotations

import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BACKEND = Path(__file__).resolve().parents[1]
PREV = "20260905_workflow_definitions"
# Chain head includes Publishing Intelligence after MIP.
HEAD = "20260910_campaign_planner"
MIP_REVISION = "20260906_marketing_intelligence"

INTEL_TABLES = (
    "tenant_marketing_signals",
    "tenant_marketing_scores",
    "tenant_marketing_score_history",
    "tenant_marketing_recommendations",
    "tenant_marketing_recommendation_history",
    "tenant_marketing_insights",
    "tenant_marketing_trends",
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

    from app.core.database import AsyncSessionLocal, ensure_intelligence_schema

    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    await ensure_intelligence_schema()

    heads = _alembic("heads")
    record("alembic_one_head", heads.returncode == 0 and HEAD in (heads.stdout or ""), (heads.stdout or "")[:200])
    record("alembic_only_one_head_line", (heads.stdout or "").count("(head)") == 1, (heads.stdout or "")[:200])

    up = _alembic("upgrade", "head")
    record("upgrade_head", up.returncode == 0, (up.stderr or up.stdout)[-400:])
    cur = _alembic("current")
    record("current_is_head", HEAD in (cur.stdout or ""), (cur.stdout or "")[:200])
    hist = _alembic("history", "-r", f"{PREV}:{HEAD}")
    record(
        "mip_revision_in_chain",
        MIP_REVISION in (hist.stdout or ""),
        (hist.stdout or "")[:240],
    )

    # Prove MIP tables drop when going below the MIP revision.
    down_mip = _alembic("downgrade", PREV)
    record("downgrade_to_workflow", down_mip.returncode == 0, (down_mip.stderr or down_mip.stdout)[-400:])

    async with AsyncSessionLocal() as db:
        for table in INTEL_TABLES:
            exists_after_down = (
                await db.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            record(f"{table}_removed_on_downgrade", exists_after_down is None, str(exists_after_down))

    up2 = _alembic("upgrade", "head")
    record("reupgrade_head", up2.returncode == 0, (up2.stderr or up2.stdout)[-400:])

    await ensure_intelligence_schema()
    async with AsyncSessionLocal() as db:
        for table in INTEL_TABLES:
            exists = (
                await db.execute(text(f"SELECT to_regclass('public.{table}')"))
            ).scalar_one()
            record(f"{table}_exists", exists is not None)

        signal_cols = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tenant_marketing_signals'"
                    ),
                )
            ).scalars().all()
        )
        for required in (
            "signal_id",
            "tenant_id",
            "signal_type",
            "entity_type",
            "entity_id",
            "occurred_at",
            "metadata",
            "source",
            "severity",
            "confidence",
        ):
            record(f"signals_column_{required}", required in signal_cols)

        score_cols = set(
            (
                await db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_name = 'tenant_marketing_scores'"
                    ),
                )
            ).scalars().all()
        )
        for required in ("category", "score", "weight", "scoring_version", "explanation", "evidence"):
            record(f"scores_column_{required}", required in score_cols)

    if failures:
        print(f"\nFAILED {len(failures)} checks")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nMarketing Intelligence migration verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
