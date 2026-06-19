"""Idempotent helpers for Alembic migrations (schema drift safe)."""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


def _inspector():
    return sa.inspect(op.get_bind())


def table_exists(table_name: str) -> bool:
    return table_name in _inspector().get_table_names()


def column_exists(table_name: str, column_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return column_name in {c["name"] for c in _inspector().get_columns(table_name)}


def add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if not table_exists(table_name):
        return
    if not column_exists(table_name, column.name):
        op.add_column(table_name, column)


def drop_column_if_exists(table_name: str, column_name: str) -> None:
    if column_exists(table_name, column_name):
        op.drop_column(table_name, column_name)


def index_exists(table_name: str, index_name: str) -> bool:
    if not table_exists(table_name):
        return False
    return index_name in {idx["name"] for idx in _inspector().get_indexes(table_name)}


def create_table_if_missing(table_name: str, *columns, **kwargs) -> None:
    if not table_exists(table_name):
        op.create_table(table_name, *columns, **kwargs)


def drop_table_if_exists(table_name: str) -> None:
    if table_exists(table_name):
        op.drop_table(table_name)


def create_index_if_missing(
    index_name: str,
    table_name: str,
    columns: list[str],
    *,
    unique: bool = False,
) -> None:
    if not table_exists(table_name):
        return
    if not index_exists(table_name, index_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def foreign_key_exists(constraint_name: str) -> bool:
    bind = op.get_bind()
    result = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :name AND constraint_type = 'FOREIGN KEY'"
        ),
        {"name": constraint_name},
    )
    return result.first() is not None


def create_foreign_key_if_missing(
    constraint_name: str,
    source_table: str,
    referent_table: str,
    local_cols: list[str],
    remote_cols: list[str],
    *,
    ondelete: str | None = None,
) -> None:
    if foreign_key_exists(constraint_name):
        return
    if not table_exists(source_table) or not table_exists(referent_table):
        return
    op.create_foreign_key(
        constraint_name,
        source_table,
        referent_table,
        local_cols,
        remote_cols,
        ondelete=ondelete,
    )

