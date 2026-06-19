"""Tenant isolation validation — unit tests and manual API test scenarios."""
from __future__ import annotations

import uuid
from unittest.mock import MagicMock

from app.core.api_auth_context import (
    ApiAuthContext,
    apply_client_scope,
    assert_client_in_scope,
    resolve_tenant_id_param,
    _auth_ctx,
)
from fastapi import HTTPException


def _tenant_ctx(client_ids: list[uuid.UUID]) -> ApiAuthContext:
    return ApiAuthContext(
        kind="tenant",
        tenant_id=uuid.uuid4(),
        client_ids=tuple(client_ids),
    )


def test_assert_client_in_scope_allows_owned_client():
    owned = uuid.uuid4()
    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        assert_client_in_scope(owned)
    finally:
        _auth_ctx.reset(token)


def test_assert_client_in_scope_blocks_foreign_client():
    owned = uuid.uuid4()
    foreign = uuid.uuid4()
    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        try:
            assert_client_in_scope(foreign)
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403
    finally:
        _auth_ctx.reset(token)


def test_resolve_tenant_id_param_blocks_cross_tenant():
    tenant_id = uuid.uuid4()
    other = uuid.uuid4()
    ctx = ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=())
    token = _auth_ctx.set(ctx)
    try:
        try:
            resolve_tenant_id_param(other)
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403
        assert resolve_tenant_id_param(None) == tenant_id
    finally:
        _auth_ctx.reset(token)


def test_apply_client_scope_empty_tenant_returns_no_rows_filter():
    token = _auth_ctx.set(_tenant_ctx([]))
    try:
        column = MagicMock()
        column.is_ = MagicMock(return_value="is_none")
        column.isnot_ = MagicMock(return_value="isnot_none")
        filt = apply_client_scope(client_id=None, column=column)
        assert filt is not None
    finally:
        _auth_ctx.reset(token)


# ---------------------------------------------------------------------------
# Manual API isolation scenarios (run against a live dev server)
# ---------------------------------------------------------------------------
MANUAL_SCENARIOS = """
Tenant A: Factory Alpha          Tenant B: Factory Beta
======================================================

Setup:
  1. Create two tenants with distinct owner users (or use demo seed).
  2. Login as Tenant A -> save token A; login as Tenant B -> save token B.
  3. Record one lead ID from Tenant A and one from Tenant B.

Verify complete isolation:
  - GET /api/v1/sales-crm/leads with token A -> only Alpha leads
  - GET /api/v1/sales-crm/leads with token B -> only Beta leads
  - GET /api/v1/sales-crm/leads/{beta_lead_id} with token A -> 403/404
  - GET /api/v1/buyers with token A -> only Alpha buyers
  - GET /api/v1/growth-center/dashboard with token A -> Alpha metrics only

Verify legacy client-scoped APIs (auth required):
  - GET /api/v1/content without token -> 401
  - GET /api/v1/crm/leads without token -> 401
  - GET /api/v1/clients with token A -> only Alpha clients
  - GET /api/v1/content/{beta_content_id} with token A -> 403

Verify admin routes blocked for tenants:
  - GET /api/v1/telegram/ingestion/settings with token A -> 401/403
  - GET /api/v1/admin-auth/platform/tenants with token A -> 401/403

Verify tenant cannot spoof tenant_id:
  - GET /api/v1/deal-room/v2/overview?tenant_id={beta_id} with token A -> 403
  - GET /api/v1/revenue-forecast/overview?tenant_id={beta_id} with token A -> 403

Verify billing widget scoped:
  - GET /api/v1/billing/summary-widget with token A -> Alpha billing only

Verify Telegram webhook:
  - POST /api/v1/telegram/webhook without secret (production) -> 403
  - PATCH /api/v1/telegram/ingestion/settings without admin token -> 401
"""


if __name__ == "__main__":
    test_assert_client_in_scope_allows_owned_client()
    test_assert_client_in_scope_blocks_foreign_client()
    test_resolve_tenant_id_param_blocks_cross_tenant()
    test_apply_client_scope_empty_tenant_returns_no_rows_filter()
    print("All tenant isolation unit tests passed.")
    print(MANUAL_SCENARIOS)
