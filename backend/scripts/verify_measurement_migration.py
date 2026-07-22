"""Document and sanity-check Measurement foundation migration revision.

Does not apply migrations destructively. Confirms the expected Alembic revision
id and that ensure_measurement_schema can create tables idempotently.

Run from backend/:  python scripts/verify_measurement_migration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

EXPECTED_REVISION = "20260911_measurement_foundation"
EXPECTED_DOWN_REVISION = "20260910_campaign_planner"
MIGRATION_FILE = "migrations/versions/20260911_measurement_foundation.py"

EXPECTED_TABLES = (
    "tenant_external_publications",
    "tenant_metric_ingestion_runs",
    "tenant_publication_metric_snapshots",
    "tenant_publication_metric_values",
    "tenant_publication_metric_aggregates",
    "tenant_campaign_metric_aggregates",
    "tenant_attribution_records",
    "tenant_measurement_anomalies",
    "tenant_measurement_jobs",
    "tenant_tracked_links",
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

    migration_path = Path(__file__).resolve().parents[1] / MIGRATION_FILE
    record("migration_file_exists", migration_path.is_file(), str(migration_path.name))

    text = migration_path.read_text(encoding="utf-8") if migration_path.is_file() else ""
    record(
        "revision_id",
        f'revision = "{EXPECTED_REVISION}"' in text or f"revision = '{EXPECTED_REVISION}'" in text,
        EXPECTED_REVISION,
    )
    record(
        "down_revision",
        f'down_revision = "{EXPECTED_DOWN_REVISION}"' in text
        or f"down_revision = '{EXPECTED_DOWN_REVISION}'" in text,
        EXPECTED_DOWN_REVISION,
    )
    record("no_secrets_columns", "access_token" not in text and "password" not in text.lower())

    for table in EXPECTED_TABLES:
        record(f"migration_mentions_{table}", f'"{table}"' in text or f"'{table}'" in text)

    from app.core.database import AsyncSessionLocal, ensure_measurement_schema, engine
    from sqlalchemy import inspect, text as sa_text

    await ensure_measurement_schema()
    record("ensure_measurement_schema_idempotent", True)

    async with engine.connect() as conn:
        def _tables(sync_conn):
            return set(inspect(sync_conn).get_table_names())

        tables = await conn.run_sync(_tables)

    for table in EXPECTED_TABLES:
        record(f"table_present_{table}", table in tables)

    # Second ensure is a no-op
    await ensure_measurement_schema()
    record("ensure_measurement_schema_rerun_ok", True)

    print()
    print(f"Expected Alembic revision: {EXPECTED_REVISION}")
    print(f"Down revision: {EXPECTED_DOWN_REVISION}")
    print("Apply with: alembic upgrade 20260911_measurement_foundation")
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
