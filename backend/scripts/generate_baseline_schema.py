"""Generate frozen baseline DDL for 20260521_initial_schema.

Reconstruction method:
1. Introspect the head database schema.
2. Parse later Alembic revisions for create_table_if_missing / add_column_if_missing.
3. Baseline = head schema minus objects explicitly introduced by later revisions.
4. Emit deterministic SQL checked into migrations/baseline/20260521_schema.sql.

Run once from backend/: python scripts/generate_baseline_schema.py
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect

from app.core.database import engine

VERSIONS = Path(__file__).resolve().parents[1] / "migrations" / "versions"
OUTPUT = Path(__file__).resolve().parents[1] / "migrations" / "baseline" / "20260521_schema.sql"
BASELINE_TABLE_ORDER = ("clients", "media_files", "content_items", "calendar_entries")


def parse_migration_deltas() -> tuple[set[str], dict[str, set[str]]]:
    tables_created: set[str] = set()
    columns_added: dict[str, set[str]] = {}

    for path in sorted(VERSIONS.glob("*.py")):
        if "20260521_initial_schema" in path.name:
            continue
        body = path.read_text(encoding="utf-8")

        for match in re.finditer(r'create_table_if_missing\(\s*["\']([^"\']+)["\']', body):
            tables_created.add(match.group(1))
        for match in re.finditer(r'op\.create_table\(\s*["\']([^"\']+)["\']', body):
            tables_created.add(match.group(1))

        for match in re.finditer(
            r'add_column_if_missing\(\s*["\']([^"\']+)["\'],\s*sa\.Column\(\s*["\']([^"\']+)["\']',
            body,
            re.DOTALL,
        ):
            table, column = match.group(1), match.group(2)
            columns_added.setdefault(table, set()).add(column)

        for match in re.finditer(
            r'\(\s*"([^"]+)"\s*,\s*"(?:sales_leads|buyers|sales_deals|[^"]+)"\s*\)',
            body,
        ):
            columns_added.setdefault("content_items", set()).add(match.group(1))
        for match in re.finditer(
            r'\(\s*"([^"]+)"\s*,\s*"(?:sales_leads|sales_deals)"\s*\)',
            body,
        ):
            for table in ("communication_threads", "communication_contacts"):
                columns_added.setdefault(table, set()).add(match.group(1))

    return tables_created, columns_added


def _pg_type(col: dict) -> str:
    rendered = str(col["type"])
    if rendered.upper() == "ARRAY":
        return "VARCHAR[]"
    return rendered


def _column_ddl(col: dict) -> str:
    parts = [f'"{col["name"]}" {_pg_type(col)}']
    if col.get("nullable") is False:
        parts.append("NOT NULL")
    default = col.get("default")
    if default is not None:
        default_sql = str(default)
        if default_sql and default_sql.lower() not in {"null"}:
            parts.append(f"DEFAULT {default_sql}")
    return " ".join(parts)


def _build_create_table_sql(
    sync,
    table: str,
    *,
    skip_columns: set[str],
    baseline_tables: set[str],
) -> str | None:
    columns = [c for c in sync.get_columns(table) if c["name"] not in skip_columns]
    if not columns:
        return None

    pk = sync.get_pk_constraint(table)
    pk_cols = [c for c in (pk.get("constrained_columns") or []) if c not in skip_columns]

    fks = sync.get_foreign_keys(table)
    uniques = sync.get_unique_constraints(table)
    indexes = sync.get_indexes(table)

    lines = [f'CREATE TABLE IF NOT EXISTS "{table}" (']
    col_lines = [f"    {_column_ddl(c)}" for c in columns]

    if pk_cols:
        quoted = ", ".join(f'"{c}"' for c in pk_cols)
        col_lines.append(f"    PRIMARY KEY ({quoted})")

    for fk in fks:
        local = fk.get("constrained_columns") or []
        remote = fk.get("referred_columns") or []
        remote_table = fk.get("referred_table")
        if not local or not remote or not remote_table:
            continue
        if any(c in skip_columns for c in local):
            continue
        if remote_table not in baseline_tables:
            continue
        local_q = ", ".join(f'"{c}"' for c in local)
        remote_q = ", ".join(f'"{c}"' for c in remote)
        ondelete = fk.get("options", {}).get("ondelete")
        clause = f'    FOREIGN KEY ({local_q}) REFERENCES "{remote_table}" ({remote_q})'
        if ondelete:
            clause += f" ON DELETE {ondelete}"
        col_lines.append(clause)

    for uq in uniques:
        cols = [c for c in (uq.get("column_names") or []) if c not in skip_columns]
        if not cols:
            continue
        name = uq.get("name") or f"uq_{table}_{'_'.join(cols)}"
        quoted = ", ".join(f'"{c}"' for c in cols)
        col_lines.append(f"    CONSTRAINT {name} UNIQUE ({quoted})")

    lines.append(",\n".join(col_lines))
    lines.append(");")
    ddl = "\n".join(lines)

    index_sql: list[str] = []
    for idx in indexes:
        cols = [c for c in (idx.get("column_names") or []) if c not in skip_columns]
        if not cols:
            continue
        name = idx["name"]
        quoted = ", ".join(f'"{c}"' for c in cols)
        unique = "UNIQUE " if idx.get("unique") else ""
        index_sql.append(f'CREATE {unique}INDEX IF NOT EXISTS {name} ON "{table}" ({quoted});')

    return ddl + ("\n" + "\n".join(index_sql) if index_sql else "")


async def generate() -> None:
    tables_created, columns_added = parse_migration_deltas()

    async with engine.connect() as conn:
        def _build(sync_conn):
            sync = inspect(sync_conn)
            all_tables = sorted(sync.get_table_names())
            baseline_tables = [
                t for t in all_tables if t not in tables_created and t != "alembic_version"
            ]
            baseline_set = set(baseline_tables)
            ordered = [t for t in BASELINE_TABLE_ORDER if t in baseline_set]
            ordered.extend(t for t in baseline_tables if t not in ordered)

            chunks: list[str] = [
                "-- Frozen baseline schema for revision 20260521_initial_schema",
                "-- Generated by scripts/generate_baseline_schema.py (do not edit by hand)",
                "-- Reconstruction: head schema minus objects created/added by later Alembic revisions.",
                "",
            ]

            for table in ordered:
                skip = columns_added.get(table, set())
                ddl = _build_create_table_sql(
                    sync,
                    table,
                    skip_columns=skip,
                    baseline_tables=baseline_set,
                )
                if ddl:
                    chunks.append(ddl)
                    chunks.append("")

            return chunks, ordered

        chunks, ordered = await conn.run_sync(_build)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(chunks), encoding="utf-8")
    print(f"Wrote {OUTPUT} ({len(ordered)} baseline tables: {', '.join(ordered)})")


if __name__ == "__main__":
    asyncio.run(generate())
