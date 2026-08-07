"""HIGH-3: Tenant isolation on publish / queue loaders."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import HTTPException

from app.core.api_auth_context import ApiAuthContext, _auth_ctx
from app.core.client_scope_guard import guard_resource_client_id
from app.services.content_review_service import ContentReviewService
from app.services.publish_service import PublishService


def _tenant_ctx(client_ids: list[uuid.UUID], tenant_id: uuid.UUID | None = None) -> ApiAuthContext:
    return ApiAuthContext(
        kind="tenant",
        tenant_id=tenant_id or uuid.uuid4(),
        client_ids=tuple(client_ids),
    )


def test_guard_rejects_cross_tenant_client():
    owned = uuid.uuid4()
    foreign = uuid.uuid4()
    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        try:
            guard_resource_client_id(foreign)
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403
        guard_resource_client_id(owned)
    finally:
        _auth_ctx.reset(token)


async def _publish_get_content_rejects_cross_tenant() -> None:
    owned = uuid.uuid4()
    foreign_client = uuid.uuid4()
    foreign_content = uuid.uuid4()

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(id=foreign_content, client_id=foreign_client)

    class _Db:
        async def execute(self, _q):
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        try:
            await PublishService._get_content(_Db(), foreign_content)
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403
    finally:
        _auth_ctx.reset(token)


def test_publish_loader_rejects_cross_tenant_content():
    asyncio.run(_publish_get_content_rejects_cross_tenant())


async def _review_loader_rejects_cross_tenant() -> None:
    owned = uuid.uuid4()
    foreign_client = uuid.uuid4()
    foreign_content = uuid.uuid4()

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(id=foreign_content, client_id=foreign_client)

    class _Db:
        async def execute(self, _q):
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        try:
            await ContentReviewService._load_item_for_preview(_Db(), foreign_content)
            raise AssertionError("expected HTTPException")
        except HTTPException as exc:
            assert exc.status_code == 403
    finally:
        _auth_ctx.reset(token)


def test_client_review_loader_rejects_cross_tenant_content():
    asyncio.run(_review_loader_rejects_cross_tenant())


async def _publish_loader_allows_own_tenant() -> None:
    owned = uuid.uuid4()
    content_id = uuid.uuid4()
    item = SimpleNamespace(id=content_id, client_id=owned)

    class _Result:
        def scalar_one_or_none(self):
            return item

    class _Db:
        async def execute(self, _q):
            return _Result()

    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        loaded = await PublishService._get_content(_Db(), content_id)
        assert loaded is item
    finally:
        _auth_ctx.reset(token)


def test_publish_loader_allows_own_tenant_content():
    asyncio.run(_publish_loader_allows_own_tenant())


async def _worker_without_auth_ctx_still_loads() -> None:
    """Background workers have no tenant JWT — must not be blocked."""
    content_id = uuid.uuid4()
    item = SimpleNamespace(id=content_id, client_id=uuid.uuid4())

    class _Result:
        def scalar_one_or_none(self):
            return item

    class _Db:
        async def execute(self, _q):
            return _Result()

    # Ensure no auth context
    token = _auth_ctx.set(None)
    try:
        loaded = await PublishService._get_content(_Db(), content_id)
        assert loaded is item
    finally:
        _auth_ctx.reset(token)


def test_worker_path_without_auth_context_still_loads():
    asyncio.run(_worker_without_auth_ctx_still_loads())


def test_two_tenants_isolation_matrix():
    """Prove tenant A cannot operate on tenant B resources via guards."""
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    client_a = uuid.uuid4()
    client_b = uuid.uuid4()

    token_a = _auth_ctx.set(_tenant_ctx([client_a], tenant_id=tenant_a))
    try:
        guard_resource_client_id(client_a)
        try:
            guard_resource_client_id(client_b)
            raise AssertionError("tenant A must not access tenant B client")
        except HTTPException as exc:
            assert exc.status_code == 403
    finally:
        _auth_ctx.reset(token_a)

    token_b = _auth_ctx.set(_tenant_ctx([client_b], tenant_id=tenant_b))
    try:
        guard_resource_client_id(client_b)
        try:
            guard_resource_client_id(client_a)
            raise AssertionError("tenant B must not access tenant A client")
        except HTTPException as exc:
            assert exc.status_code == 403
    finally:
        _auth_ctx.reset(token_b)


if __name__ == "__main__":
    test_guard_rejects_cross_tenant_client()
    test_publish_loader_rejects_cross_tenant_content()
    test_client_review_loader_rejects_cross_tenant_content()
    test_publish_loader_allows_own_tenant_content()
    test_worker_path_without_auth_context_still_loads()
    test_two_tenants_isolation_matrix()
    print("tenant isolation publish/queue tests passed")
