"""Load and apply the frozen 20260521 baseline schema."""
from __future__ import annotations

from pathlib import Path

from alembic import op
from sqlalchemy import text

BASELINE_SQL = Path(__file__).resolve().parent / "baseline" / "20260521_schema.sql"

# Tables created by this revision only — downgrade must not drop migration-owned objects.
BASELINE_TABLES = (
    "calendar_entries",
    "content_items",
    "media_files",
    "clients",
)


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        buffer.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buffer).strip()
            if stmt.endswith(";"):
                stmt = stmt[:-1].strip()
            if stmt:
                statements.append(stmt)
            buffer = []
    if buffer:
        stmt = "\n".join(buffer).strip()
        if stmt.endswith(";"):
            stmt = stmt[:-1].strip()
        if stmt:
            statements.append(stmt)
    return statements


def apply_baseline_schema() -> None:
    sql = BASELINE_SQL.read_text(encoding="utf-8")
    bind = op.get_bind()
    for statement in _split_sql_statements(sql):
        bind.execute(text(statement))


def drop_baseline_schema() -> None:
    bind = op.get_bind()
    for table in BASELINE_TABLES:
        bind.execute(text(f'DROP TABLE IF EXISTS "{table}" CASCADE'))
