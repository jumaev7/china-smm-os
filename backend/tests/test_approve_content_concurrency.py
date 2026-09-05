"""Concurrent approve_content safety — row lock + single Telegram side effect.

These tests simulate cross-worker serialization with an asyncio lock that mirrors
SELECT … FOR UPDATE (held from locked read until commit). No production DB or
Telegram calls.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql import Select

from app.services.content_service import ContentService
from app.services.operator_workspace_actions import (
    ACTION_APPROVE_CONTENT,
    OperatorWorkspaceActionService,
)


def _now():
    return datetime.now(timezone.utc)


class _RowLockStore:
    """Shared mutable content row + lock held until commit (FOR UPDATE stand-in)."""

    def __init__(self, item: SimpleNamespace):
        self.item = item
        self.lock = asyncio.Lock()
        self._holder: asyncio.Task | None = None
        self.after_admin_approve_calls = 0
        self.telegram_sends = 0
        self.transition_count = 0

    async def get_for_update(self, _db, content_id):
        assert self.item.id == content_id
        await self.lock.acquire()
        self._holder = asyncio.current_task()
        return self.item

    async def commit(self):
        if self._holder is asyncio.current_task() and self.lock.locked():
            self.lock.release()
            self._holder = None

    async def after_admin_approve(self, _db, content_id):
        assert content_id == self.item.id
        self.after_admin_approve_calls += 1
        self.telegram_sends += 1
        self.item.client_review_status = "pending"


def _eligible_item(**kwargs) -> SimpleNamespace:
    content_id = kwargs.pop("id", uuid.uuid4())
    defaults = dict(
        id=content_id,
        status="ready",
        approved_at=None,
        client_review_status=None,
        client_id=uuid.uuid4(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


async def _approve_under_store(store: _RowLockStore, db, content_id):
    """Mirrors ContentService.approve against the shared locked store."""
    item = await store.get_for_update(db, content_id)
    if item.status == "approved" and item.approved_at is not None:
        await db.commit()
        return item
    if item.status not in ContentService._APPROVE_ELIGIBLE_STATUSES:
        raise HTTPException(status_code=400, detail="Only draft/ready content can be approved")
    item.status = "approved"
    item.approved_at = _now()
    store.transition_count += 1
    await db.commit()
    await store.after_admin_approve(db, content_id)
    return item


def test_approve_query_uses_for_update():
    """Compile-path check: get_for_update issues WITH FOR UPDATE."""

    async def _run():
        captured: dict = {}

        class _Result:
            def scalar_one_or_none(self):
                return SimpleNamespace(
                    id=uuid.uuid4(),
                    client_id=uuid.uuid4(),
                    status="ready",
                    approved_at=None,
                )

        async def fake_execute(stmt):
            captured["stmt"] = stmt
            return _Result()

        db = AsyncMock()
        db.execute = fake_execute

        with patch(
            "app.services.content_service.guard_resource_client_id",
            return_value=None,
        ):
            await ContentService.get_for_update(db, uuid.uuid4())

        stmt = captured["stmt"]
        assert isinstance(stmt, Select)
        compiled = str(
            stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": False},
            )
        ).upper()
        assert "FOR UPDATE" in compiled

    asyncio.run(_run())


def test_concurrent_approve_single_transition_and_telegram():
    """Two concurrent ContentService.approve calls → one transition, one Telegram."""

    async def _run():
        store = _RowLockStore(_eligible_item())
        content_id = store.item.id
        after = AsyncMock(side_effect=store.after_admin_approve)

        async def fake_get(_db, cid):
            assert cid == content_id
            return store.item

        db_a = AsyncMock()
        db_a.commit = store.commit
        db_b = AsyncMock()
        db_b.commit = store.commit

        async def locked_get_for_update(db, cid):
            item = await store.get_for_update(db, cid)
            # Count canonical transitions under the lock (eligible → approved).
            if item.status != "approved":
                store.transition_count += 1
            return item

        with (
            patch.object(
                ContentService, "get_for_update", staticmethod(locked_get_for_update)
            ),
            patch.object(ContentService, "get", staticmethod(fake_get)),
            patch(
                "app.services.content_review_service.ContentReviewService.after_admin_approve",
                after,
            ),
        ):
            r1, r2 = await asyncio.gather(
                ContentService.approve(db_a, content_id),
                ContentService.approve(db_b, content_id),
            )

        assert r1.status == "approved" and r2.status == "approved"
        assert store.item.status == "approved"
        assert store.item.approved_at is not None
        # Winner sees eligible under lock; loser sees approved — one transition path.
        assert store.transition_count == 1
        assert after.await_count == 1
        assert store.telegram_sends == 1

    asyncio.run(_run())


def test_content_service_approve_skips_telegram_when_already_approved():
    async def _run():
        item = _eligible_item(
            status="approved", approved_at=_now(), client_review_status="pending"
        )
        db = AsyncMock()
        db.commit = AsyncMock()
        after = AsyncMock()

        with (
            patch.object(ContentService, "get_for_update", new=AsyncMock(return_value=item)),
            patch(
                "app.services.content_review_service.ContentReviewService.after_admin_approve",
                after,
            ),
        ):
            result = await ContentService.approve(db, item.id)

        assert result.status == "approved"
        after.assert_not_awaited()
        db.commit.assert_awaited()

    asyncio.run(_run())


def test_content_service_approve_calls_telegram_once_on_transition():
    async def _run():
        item = _eligible_item()
        db = AsyncMock()
        db.commit = AsyncMock()
        after = AsyncMock()

        async def fake_get(_db, _cid):
            return item

        with (
            patch.object(ContentService, "get_for_update", new=AsyncMock(return_value=item)),
            patch.object(ContentService, "get", fake_get),
            patch(
                "app.services.content_review_service.ContentReviewService.after_admin_approve",
                after,
            ),
        ):
            result = await ContentService.approve(db, item.id)

        assert result.status == "approved"
        assert item.approved_at is not None
        after.assert_awaited_once()

    asyncio.run(_run())


def test_sequential_duplicate_approve_workspace_no_second_telegram():
    async def _run():
        content_id = uuid.uuid4()
        item = _eligible_item(id=content_id, status="approved", approved_at=_now())
        db = AsyncMock()
        approve = AsyncMock()

        with (
            patch(
                "app.services.operator_workspace_actions.ContentService.get",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "app.services.operator_workspace_actions.ContentService.approve",
                approve,
            ),
            patch(
                "app.services.operator_workspace_actions.OperatorWorkspaceMetricsService.record_action",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await OperatorWorkspaceActionService.execute(
                db,
                attention_id=f"content-review:{content_id}",
                action_id=ACTION_APPROVE_CONTENT,
                actor_id=None,
                tenant_id=uuid.uuid4(),
                source="mobile",
            )

        approve.assert_not_awaited()
        assert result.success is True
        assert "already approved" in result.message.lower()

    asyncio.run(_run())


def test_mobile_and_web_concurrent_approve_single_telegram():
    """Mobile + web both hit approve; shared row lock → one Telegram."""

    async def _run():
        store = _RowLockStore(_eligible_item())
        content_id = store.item.id
        tenant_id = uuid.uuid4()

        async def locked_approve(db, cid):
            return await _approve_under_store(store, db, cid)

        async def unlocked_get(_db, _cid):
            # Both concurrent callers observe eligible pre-image.
            return SimpleNamespace(
                id=content_id,
                status="ready",
                approved_at=None,
                client_review_status=None,
                client_id=store.item.client_id,
            )

        db_mobile = AsyncMock()
        db_mobile.commit = store.commit
        db_web = AsyncMock()
        db_web.commit = store.commit

        with (
            patch(
                "app.services.operator_workspace_actions.ContentService.get",
                unlocked_get,
            ),
            patch(
                "app.services.operator_workspace_actions.ContentService.approve",
                locked_approve,
            ),
            patch(
                "app.services.operator_workspace_actions.OperatorWorkspaceMetricsService.record_action",
                new=AsyncMock(return_value=None),
            ),
        ):
            r_mobile, r_web = await asyncio.gather(
                OperatorWorkspaceActionService.execute(
                    db_mobile,
                    attention_id=f"content-review:{content_id}",
                    action_id=ACTION_APPROVE_CONTENT,
                    actor_id=None,
                    tenant_id=tenant_id,
                    source="mobile",
                ),
                OperatorWorkspaceActionService.execute(
                    db_web,
                    attention_id=f"content-review:{content_id}",
                    action_id=ACTION_APPROVE_CONTENT,
                    actor_id=None,
                    tenant_id=tenant_id,
                    source="web",
                ),
            )

        assert r_mobile.success and r_web.success
        assert store.item.status == "approved"
        assert store.transition_count == 1
        assert store.telegram_sends == 1
        assert store.after_admin_approve_calls == 1

    asyncio.run(_run())


def test_stale_ineligible_status_conflict():
    async def _run():
        content_id = uuid.uuid4()
        item = _eligible_item(
            id=content_id,
            status="published",
            approved_at=_now(),
            client_review_status="approved",
        )
        db = AsyncMock()
        approve = AsyncMock()

        with (
            patch(
                "app.services.operator_workspace_actions.ContentService.get",
                new=AsyncMock(return_value=item),
            ),
            patch(
                "app.services.operator_workspace_actions.ContentService.approve",
                approve,
            ),
            patch(
                "app.services.operator_workspace_actions.OperatorWorkspaceMetricsService.record_action",
                new=AsyncMock(return_value=None),
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await OperatorWorkspaceActionService.execute(
                    db,
                    attention_id=f"content-review:{content_id}",
                    action_id=ACTION_APPROVE_CONTENT,
                    actor_id=None,
                    tenant_id=uuid.uuid4(),
                )
        assert exc.value.status_code == 409
        approve.assert_not_awaited()

    asyncio.run(_run())


def test_approve_ineligible_under_lock_raises_400():
    async def _run():
        item = _eligible_item(status="published", approved_at=None)
        db = AsyncMock()
        db.commit = AsyncMock()
        after = AsyncMock()

        with (
            patch.object(ContentService, "get_for_update", new=AsyncMock(return_value=item)),
            patch(
                "app.services.content_review_service.ContentReviewService.after_admin_approve",
                after,
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await ContentService.approve(db, item.id)
        assert exc.value.status_code == 400
        after.assert_not_awaited()

    asyncio.run(_run())


def test_tenant_isolation_preserved_on_locked_get():
    async def _run():
        item = _eligible_item()
        db = AsyncMock()

        class _Result:
            def scalar_one_or_none(self):
                return item

        db.execute = AsyncMock(return_value=_Result())

        with patch(
            "app.services.content_service.guard_resource_client_id",
            side_effect=HTTPException(status_code=404, detail="Not found"),
        ):
            with pytest.raises(HTTPException) as exc:
                await ContentService.get_for_update(db, item.id)
        assert exc.value.status_code == 404

    asyncio.run(_run())


def test_real_approve_uses_get_for_update_not_plain_get():
    async def _run():
        item = _eligible_item()
        db = AsyncMock()
        db.commit = AsyncMock()
        get_fu = AsyncMock(return_value=item)
        plain_get = AsyncMock(return_value=item)
        after = AsyncMock()

        with (
            patch.object(ContentService, "get_for_update", get_fu),
            patch.object(ContentService, "get", plain_get),
            patch(
                "app.services.content_review_service.ContentReviewService.after_admin_approve",
                after,
            ),
        ):
            await ContentService.approve(db, item.id)

        get_fu.assert_awaited_once()
        assert plain_get.await_count >= 1
        after.assert_awaited_once()

    asyncio.run(_run())
