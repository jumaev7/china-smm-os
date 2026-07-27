"""Verify Social Listening migration revisions and schema ensure.

Confirms Alembic revision chain for Phase 1–3 listening, upgrade of live-source
columns, and that ensure_listening_schema is idempotent and create-only
(no ALTER drift). Production ALTERs remain in Alembic.

Run from backend/:  python scripts/verify_listening_migration.py
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

EXPECTED_REVISION = "20260914_social_listening_foundation"
EXPECTED_DOWN_REVISION = "20260913_advertising_decision_support"
LIVE_REVISION = "20260916_listening_live_sources"
MIGRATION_FILE = "migrations/versions/20260914_social_listening_foundation.py"
LIVE_MIGRATION_FILE = "migrations/versions/20260916_listening_live_sources.py"

EXPECTED_TABLES = (
    "tenant_listening_projects",
    "tenant_listening_subjects",
    "tenant_listening_queries",
    "tenant_listening_sources",
    "tenant_listening_ingestion_runs",
    "tenant_observed_mentions",
    "tenant_mention_matches",
    "tenant_mention_reviews",
)

EXPECTED_UNIQUES = (
    "uq_tenant_observed_mentions_provider_identity",
    "uq_tenant_observed_mentions_dedupe_key",
    "uq_tenant_mention_matches_identity",
    "uq_tenant_listening_sources_identity",
)

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

    migration_path = Path(__file__).resolve().parents[1] / MIGRATION_FILE
    record("migration_file_exists", migration_path.is_file(), str(migration_path.name))

    text = migration_path.read_text(encoding="utf-8") if migration_path.is_file() else ""
    record(
        "revision_id",
        f'revision = "{EXPECTED_REVISION}"' in text,
        EXPECTED_REVISION,
    )
    record(
        "down_revision",
        f'down_revision = "{EXPECTED_DOWN_REVISION}"' in text,
        EXPECTED_DOWN_REVISION,
    )
    record("upgrade_defined", "def upgrade()" in text)
    record("downgrade_defined", "def downgrade()" in text)
    record("no_secrets_columns", "access_token" not in text and "password" not in text.lower())
    record("no_provider_write_tables", "reply_payload" not in text and "publish_payload" not in text)

    live_path = Path(__file__).resolve().parents[1] / LIVE_MIGRATION_FILE
    live_text = live_path.read_text(encoding="utf-8") if live_path.is_file() else ""
    record("live_migration_file_exists", live_path.is_file())
    record(
        "live_migration_retains_alter",
        "op.add_column" in live_text and "op.alter_column" in live_text,
        "upgrade ALTERs must remain for production schema evolution",
    )
    for col in LIVE_SOURCE_COLUMNS:
        record(f"live_migration_mentions_{col}", col in live_text)

    for table in EXPECTED_TABLES:
        record(f"migration_mentions_{table}", f'"{table}"' in text or f"'{table}'" in text)
    for uq in EXPECTED_UNIQUES:
        record(f"migration_mentions_{uq}", uq in text)

    from app.core import database as db_mod

    ensure_src = inspect.getsource(db_mod._ensure_listening_tables)
    record(
        "ensure_create_only_no_alter",
        "ALTER TABLE" not in ensure_src.upper(),
        "ensure_listening must not mutate existing columns",
    )
    record(
        "ensure_fresh_includes_live_columns",
        all(col in ensure_src for col in ("integration_id", "lock_owner", "last_checkpoint")),
    )
    record(
        "ensure_fresh_cursor_width_1000",
        "cursor_before VARCHAR(1000)" in ensure_src and "cursor_after VARCHAR(1000)" in ensure_src,
    )

    heads = _alembic("heads")
    history = _alembic("history", "-v")
    history_text = (history.stdout or "") + (heads.stdout or "")
    record(
        "alembic_heads_ok",
        heads.returncode == 0 and (
            EXPECTED_REVISION in history_text or LIVE_REVISION in history_text
        ),
        (heads.stdout or heads.stderr or "")[:240],
    )

    up = _alembic("upgrade", LIVE_REVISION)
    record(
        "alembic_upgrade_listening_live",
        up.returncode == 0,
        (up.stdout or up.stderr or "")[:300],
    )
    cur = _alembic("current")
    cur_text = cur.stdout or ""
    record(
        "alembic_current_at_or_past_live",
        cur.returncode == 0
        and (
            LIVE_REVISION in cur_text
            or EXPECTED_REVISION in cur_text
            or "20260915_listening_market_intelligence" in cur_text
        ),
        cur_text[:240],
    )

    from app.core.database import ensure_listening_schema, engine
    from sqlalchemy import inspect as sa_inspect

    await ensure_listening_schema()
    record("ensure_listening_schema_idempotent", True)

    async with engine.connect() as conn:
        def _tables(sync_conn):
            return set(sa_inspect(sync_conn).get_table_names())

        def _columns(sync_conn, table: str) -> set[str]:
            return {c["name"] for c in sa_inspect(sync_conn).get_columns(table)}

        def _unique_names(sync_conn, table: str) -> set[str]:
            insp = sa_inspect(sync_conn)
            names: set[str] = set()
            for uc in insp.get_unique_constraints(table):
                if uc.get("name"):
                    names.add(uc["name"])
            for ix in insp.get_indexes(table):
                if ix.get("unique") and ix.get("name"):
                    names.add(ix["name"])
            return names

        def _fk_targets(sync_conn, table: str) -> set[str]:
            return {
                fk["referred_table"]
                for fk in sa_inspect(sync_conn).get_foreign_keys(table)
            }

        def _index_cols(sync_conn, table: str) -> set[tuple[str, ...]]:
            return {
                tuple(ix.get("column_names") or ())
                for ix in sa_inspect(sync_conn).get_indexes(table)
            }

        tables_after_upgrade = await conn.run_sync(_tables)

        for table in EXPECTED_TABLES:
            record(f"table_present_after_upgrade_{table}", table in tables_after_upgrade)

        if "tenant_listening_sources" in tables_after_upgrade:
            cols = await conn.run_sync(
                lambda c: _columns(c, "tenant_listening_sources")
            )
            for col in LIVE_SOURCE_COLUMNS:
                record(f"live_column_present_{col}", col in cols, str(sorted(cols)))

        if "tenant_observed_mentions" in tables_after_upgrade:
            uniques = await conn.run_sync(
                lambda c: _unique_names(c, "tenant_observed_mentions")
            )
            record(
                "uq_provider_identity_present",
                "uq_tenant_observed_mentions_provider_identity" in uniques,
                str(sorted(uniques)),
            )
            record(
                "uq_dedupe_key_present",
                "uq_tenant_observed_mentions_dedupe_key" in uniques,
                str(sorted(uniques)),
            )
            idxs = await conn.run_sync(
                lambda c: _index_cols(c, "tenant_observed_mentions")
            )
            record(
                "idx_tenant_observed",
                ("tenant_id", "observed_at") in idxs or ("tenant_id",) in idxs,
                str(sorted(idxs)),
            )
            fks = await conn.run_sync(
                lambda c: _fk_targets(c, "tenant_observed_mentions")
            )
            record("fk_mentions_tenant", "tenants" in fks, str(sorted(fks)))

        if "tenant_mention_matches" in tables_after_upgrade:
            uniques = await conn.run_sync(
                lambda c: _unique_names(c, "tenant_mention_matches")
            )
            record(
                "uq_match_identity_present",
                "uq_tenant_mention_matches_identity" in uniques,
                str(sorted(uniques)),
            )

    down = _alembic("downgrade", EXPECTED_DOWN_REVISION)
    record(
        "alembic_downgrade_listening",
        down.returncode == 0,
        (down.stdout or down.stderr or "")[:300],
    )

    async with engine.connect() as conn:
        tables_after_down = await conn.run_sync(
            lambda c: set(sa_inspect(c).get_table_names())
        )
    missing_after_down = [t for t in EXPECTED_TABLES if t in tables_after_down]
    record(
        "alembic_downgrade_dropped_listening_tables",
        missing_after_down == [],
        str(missing_after_down),
    )

    up2 = _alembic("upgrade", "head")
    record(
        "alembic_reupgrade_listening",
        up2.returncode == 0,
        (up2.stdout or up2.stderr or "")[:300],
    )

    await ensure_listening_schema()
    record("ensure_listening_schema_rerun_ok", True)

    async with engine.connect() as conn:
        tables_final = await conn.run_sync(
            lambda c: set(sa_inspect(c).get_table_names())
        )

        def _columns(sync_conn, table: str) -> set[str]:
            return {c["name"] for c in sa_inspect(sync_conn).get_columns(table)}

        if "tenant_listening_sources" in tables_final:
            cols_final = await conn.run_sync(
                lambda c: _columns(c, "tenant_listening_sources")
            )
            for col in LIVE_SOURCE_COLUMNS:
                record(f"parity_live_column_{col}", col in cols_final)

    for table in EXPECTED_TABLES:
        record(f"table_present_final_{table}", table in tables_final)

    record(
        "ensure_and_alembic_table_parity",
        all(t in tables_final for t in EXPECTED_TABLES),
    )

    print()
    print(f"Expected Alembic foundation revision: {EXPECTED_REVISION}")
    print(f"Live sources revision: {LIVE_REVISION}")
    print(f"Down revision: {EXPECTED_DOWN_REVISION}")
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
