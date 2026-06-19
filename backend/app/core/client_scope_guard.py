"""Helpers for applying tenant client scope in service-layer queries."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select

from app.core.api_auth_context import apply_client_scope, assert_tenant_resource


def scope_select(
    query: Select,
    count_query: Select | None,
    column,
    *,
    client_id: UUID | None = None,
) -> tuple[Select, Select | None]:
    """Apply tenant client isolation to list queries."""
    filt = apply_client_scope(client_id=client_id, column=column)
    if filt is not None:
        query = query.where(filt)
        if count_query is not None:
            count_query = count_query.where(filt)
    return query, count_query


def guard_resource_client_id(client_id: UUID | None) -> None:
    assert_tenant_resource(client_id)
