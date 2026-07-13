"""Compare normalized PostgreSQL schemas between two databases."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import create_async_engine


async def snapshot(url: str) -> dict:
    engine = create_async_engine(url, poolclass=None)
    async with engine.connect() as conn:
        def _build(sync_conn):
            sync = inspect(sync_conn)
            out: dict = {"tables": {}}
            for table in sorted(sync.get_table_names()):
                if table == "alembic_version":
                    continue
                cols = sync.get_columns(table)
                out["tables"][table] = {
                    "columns": {
                        c["name"]: {
                            "type": str(c["type"]),
                            "nullable": c.get("nullable"),
                            "default": str(c.get("default")) if c.get("default") is not None else None,
                        }
                        for c in cols
                    },
                    "pk": sync.get_pk_constraint(table).get("constrained_columns") or [],
                    "fks": [
                        {
                            "local": fk.get("constrained_columns") or [],
                            "remote_table": fk.get("referred_table"),
                            "remote": fk.get("referred_columns") or [],
                            "ondelete": fk.get("options", {}).get("ondelete"),
                        }
                        for fk in sync.get_foreign_keys(table)
                    ],
                    "indexes": [
                        {
                            "name": idx["name"],
                            "columns": idx.get("column_names") or [],
                            "unique": idx.get("unique"),
                        }
                        for idx in sync.get_indexes(table)
                    ],
                    "uniques": sync.get_unique_constraints(table),
                }
            return out

        return await conn.run_sync(_build)
    await engine.dispose()


async def main() -> int:
    left = os.environ.get("SCHEMA_COMPARE_LEFT")
    right = os.environ.get("SCHEMA_COMPARE_RIGHT")
    if not left or not right:
        print("Set SCHEMA_COMPARE_LEFT and SCHEMA_COMPARE_RIGHT")
        return 1
    left_snap = await snapshot(left)
    right_snap = await snapshot(right)
    if left_snap == right_snap:
        print("PASS schemas match")
        return 0
    print("FAIL schema mismatch")
    left_tables = set(left_snap["tables"])
    right_tables = set(right_snap["tables"])
    only_left = sorted(left_tables - right_tables)
    only_right = sorted(right_tables - left_tables)
    if only_left:
        print("only left:", only_left)
    if only_right:
        print("only right:", only_right)
    for table in sorted(left_tables & right_tables):
        if left_snap["tables"][table] != right_snap["tables"][table]:
            print("diff table:", table)
            print(json.dumps({"left": left_snap["tables"][table], "right": right_snap["tables"][table]}, indent=2)[:2000])
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
