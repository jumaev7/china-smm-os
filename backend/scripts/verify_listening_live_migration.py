"""Verify Social Listening Phase 3 live-sources migration cycle.

Runs Alembic:
  20260915_listening_market_intelligence → 20260916_listening_live_sources
  downgrade back to 20260915
  re-upgrade to head

Also checks ensure_listening_schema() idempotency and structural parity for
Phase 3 columns on tenant_listening_sources / cursor width on ingestion runs.

Run from backend/:  python scripts/verify_listening_live_migration.py
"""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

PHASE2_REVISION = "20260915_listening_market_intelligence"
LIVE_REVISION = "20260916_listening_live_sources"
LIVE_MIGRATION_FILE = "migrations/versions/20260916_listening_live_sources.py"

LIVE_SOURCE_COLUMNS = (
    "integration_id",
    "provider_resource_ref",
    "health_status",
    "last_failure_at",
    "last_failure_code",
    "last_failure_summary",
    "last_checkpoint",
    "poll_interval_seconds",
    "provider_capability_version",
    "enabled_capabilities_json",
    "lock_owner",
    "lock_expires_at",
)


def _alembic(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(Path(__file__).resolve().parents[1]),
        capture_output=True,
        text=True,
        check=False,
    )


def main() -> int:
    import asyncio

    return asyncio.run(_run())


async def _run() -> int:
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    live_path = Path(__file__).resolve().parents[1] / LIVE_MIGRATION_FILE
    live_text = live_path.read_text(encoding="utf-8") if live_path.is_file() else ""
    record("live_migration_file_exists", live_path.is_file())
    record(
        "live_down_revision_phase2",
        f'down_revision = "{PHASE2_REVISION}"' in live_text,
        PHASE2_REVISION,
    )
    record(
        "live_migration_retains_alter",
        "op.add_column" in live_text and "op.alter_column" in live_text,
    )
    for col in LIVE_SOURCE_COLUMNS:
        record(f"live_migration_mentions_{col}", col in live_text)

    # Start from Phase 2 tip, then exercise Phase 3 upgrade/downgrade/re-upgrade.
    down_to_phase2 = _alembic("downgrade", PHASE2_REVISION)
    record(
        "alembic_downgrade_to_20260915",
        down_to_phase2.returncode == 0,
        (down_to_phase2.stdout or down_to_phase2.stderr or "")[:300],
    )

    up_live = _alembic("upgrade", LIVE_REVISION)
    record(
        "alembic_upgrade_20260915_to_20260916",
        up_live.returncode == 0,
        (up_live.stdout or up_live.stderr or "")[:300],
    )
    cur = _alembic("current")
    cur_text = (cur.stdout or "") + (cur.stderr or "")
    record(
        "alembic_current_at_20260916",
        LIVE_REVISION in cur_text,
        cur_text[:240],
    )

    from app.core.database import ensure_listening_schema, engine
    from sqlalchemy import inspect as sa_inspect, text

    async with engine.connect() as conn:
        def _columns(sync_conn, table: str) -> set[str]:
            return {c["name"] for c in sa_inspect(sync_conn).get_columns(table)}

        def _col_type(sync_conn, table: str, col: str) -> str:
            for c in sa_inspect(sync_conn).get_columns(table):
                if c["name"] == col:
                    return str(c["type"])
            return ""

        def _fk_targets(sync_conn, table: str) -> set[str]:
            return {
                fk["referred_table"]
                for fk in sa_inspect(sync_conn).get_foreign_keys(table)
            }

        cols = await conn.run_sync(lambda c: _columns(c, "tenant_listening_sources"))
        for col in LIVE_SOURCE_COLUMNS:
            record(f"live_column_after_upgrade_{col}", col in cols)

        fks = await conn.run_sync(
            lambda c: _fk_targets(c, "tenant_listening_sources")
        )
        record(
            "integration_id_fk_publishing_accounts",
            "publishing_accounts" in fks,
            str(sorted(fks)),
        )

        cursor_before = await conn.run_sync(
            lambda c: _col_type(c, "tenant_listening_ingestion_runs", "cursor_before")
        )
        cursor_after = await conn.run_sync(
            lambda c: _col_type(c, "tenant_listening_ingestion_runs", "cursor_after")
        )
        record(
            "ingestion_cursor_width_after_upgrade",
            "1000" in cursor_before and "1000" in cursor_after,
            f"before={cursor_before} after={cursor_after}",
        )

    down_live = _alembic("downgrade", PHASE2_REVISION)
    record(
        "alembic_downgrade_20260916_to_20260915",
        down_live.returncode == 0,
        (down_live.stdout or down_live.stderr or "")[:300],
    )
    cur2 = _alembic("current")
    cur2_text = (cur2.stdout or "") + (cur2.stderr or "")
    record(
        "alembic_current_back_at_20260915",
        PHASE2_REVISION in cur2_text and LIVE_REVISION not in cur2_text.split("(")[0],
        cur2_text[:240],
    )

    async with engine.connect() as conn:
        cols_down = await conn.run_sync(
            lambda c: {x["name"] for x in sa_inspect(c).get_columns("tenant_listening_sources")}
        )
    residual = [c for c in LIVE_SOURCE_COLUMNS if c in cols_down]
    record(
        "live_columns_removed_on_downgrade",
        residual == [],
        str(residual),
    )

    up_head = _alembic("upgrade", "head")
    record(
        "alembic_reupgrade_to_head",
        up_head.returncode == 0,
        (up_head.stdout or up_head.stderr or "")[:300],
    )
    cur3 = _alembic("current")
    record(
        "alembic_current_at_head_live",
        LIVE_REVISION in ((cur3.stdout or "") + (cur3.stderr or "")),
        (cur3.stdout or cur3.stderr or "")[:240],
    )

    from app.core import database as db_mod

    ensure_src = inspect.getsource(db_mod._ensure_listening_tables)
    record("ensure_create_only_no_alter", "ALTER TABLE" not in ensure_src.upper())
    record(
        "ensure_fresh_includes_live_columns",
        all(col in ensure_src for col in ("integration_id", "lock_owner", "last_checkpoint")),
    )
    record(
        "ensure_fresh_cursor_width_1000",
        "cursor_before VARCHAR(1000)" in ensure_src
        and "cursor_after VARCHAR(1000)" in ensure_src,
    )

    await ensure_listening_schema()
    await ensure_listening_schema()
    record("ensure_listening_schema_idempotent", True)

    # Fresh-schema structural parity after ensure + alembic head
    async with engine.connect() as conn:
        cols_final = await conn.run_sync(
            lambda c: {x["name"] for x in sa_inspect(c).get_columns("tenant_listening_sources")}
        )
        for col in LIVE_SOURCE_COLUMNS:
            record(f"parity_live_column_{col}", col in cols_final)

        # Smoke: lock columns are writable (no type mismatch)
        await conn.execute(text("SELECT lock_owner, lock_expires_at FROM tenant_listening_sources LIMIT 0"))
        record("lock_columns_selectable", True)
        await conn.rollback()

    print()
    print(f"Phase 2 revision: {PHASE2_REVISION}")
    print(f"Phase 3 live revision: {LIVE_REVISION}")
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
