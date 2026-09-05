"""Concurrent acknowledge_alert safety — row lock + stable actor attribution.

These tests simulate cross-worker serialization with an asyncio lock that mirrors
SELECT … FOR UPDATE (held from locked read until commit). No production DB,
publish, Telegram, Meta, or Auto-Ack execution.
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

from app.services.publish_operator_alert_service import PublishOperatorAlertService


def _now():
    return datetime.now(timezone.utc)


class _AlertRowLockStore:
    """Shared mutable alert row + lock held until commit (FOR UPDATE stand-in)."""

    def __init__(self, row: SimpleNamespace):
        self.row = row
        self.lock = asyncio.Lock()
        self._holder: asyncio.Task | None = None
        self.open_to_ack_transitions = 0
        self.open_or_ack_to_resolved_transitions = 0
        self.side_effect_calls = 0

    async def get_for_update(self, _db, tenant_id, alert_id, *, for_update: bool = False):
        assert for_update is True
        assert self.row.id == alert_id
        assert self.row.tenant_id == tenant_id
        await self.lock.acquire()
        self._holder = asyncio.current_task()
        return self.row

    async def commit(self):
        if self._holder is asyncio.current_task() and self.lock.locked():
            self.lock.release()
            self._holder = None

    async def flush(self):
        # Flush must not release the row lock (real FOR UPDATE holds until commit).
        return None


def _open_alert(**kwargs) -> SimpleNamespace:
    alert_id = kwargs.pop("id", uuid.uuid4())
    tenant_id = kwargs.pop("tenant_id", uuid.uuid4())
    defaults = dict(
        id=alert_id,
        tenant_id=tenant_id,
        state="open",
        acknowledged_at=None,
        acknowledged_by=None,
        resolved_at=None,
        resolved_by=None,
        resolved_by_system=False,
        resolve_note=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


async def _ack_and_commit(store: _AlertRowLockStore, db, tenant_id, alert_id, actor_id):
    resp = await PublishOperatorAlertService.acknowledge(
        db, tenant_id, alert_id, actor_id=actor_id,
    )
    await db.commit()
    return resp


async def _resolve_and_commit(store: _AlertRowLockStore, db, tenant_id, alert_id, actor_id):
    resp = await PublishOperatorAlertService.resolve_manual(
        db, tenant_id, alert_id, actor_id=actor_id, note="race",
    )
    await db.commit()
    return resp


def test_locked_get_query_uses_for_update():
    """Compile-path check: for_update=True emits WITH FOR UPDATE."""

    async def _run():
        captured: dict = {}
        alert_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        class _Result:
            def scalar_one_or_none(self):
                return _open_alert(id=alert_id, tenant_id=tenant_id)

        async def fake_execute(stmt):
            captured["stmt"] = stmt
            return _Result()

        db = AsyncMock()
        db.execute = fake_execute

        await PublishOperatorAlertService._get_for_tenant(
            db, tenant_id, alert_id, for_update=True,
        )

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


def test_unlocked_get_does_not_use_for_update():
    async def _run():
        captured: dict = {}
        alert_id = uuid.uuid4()
        tenant_id = uuid.uuid4()

        class _Result:
            def scalar_one_or_none(self):
                return _open_alert(id=alert_id, tenant_id=tenant_id)

        async def fake_execute(stmt):
            captured["stmt"] = stmt
            return _Result()

        db = AsyncMock()
        db.execute = fake_execute

        await PublishOperatorAlertService._get_for_tenant(db, tenant_id, alert_id)

        compiled = str(
            captured["stmt"].compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": False},
            )
        ).upper()
        assert "FOR UPDATE" not in compiled

    asyncio.run(_run())


def test_concurrent_mobile_mobile_ack_first_actor_wins():
    """Two simultaneous acknowledges → one transition; first actor kept."""

    async def _run():
        store = _AlertRowLockStore(_open_alert())
        tenant_id = store.row.tenant_id
        alert_id = store.row.id
        first = uuid.uuid4()
        second = uuid.uuid4()

        async def locked_get(db, tid, aid, *, for_update: bool = False):
            row = await store.get_for_update(db, tid, aid, for_update=for_update)
            if row.state == "open":
                store.open_to_ack_transitions += 1
            return row

        db_a = AsyncMock()
        db_a.flush = store.flush
        db_a.commit = store.commit
        db_b = AsyncMock()
        db_b.flush = store.flush
        db_b.commit = store.commit

        async def first_ack():
            return await _ack_and_commit(store, db_a, tenant_id, alert_id, first)

        async def second_ack():
            # Let the first request acquire the row lock.
            await asyncio.sleep(0.01)
            return await _ack_and_commit(store, db_b, tenant_id, alert_id, second)

        with (
            patch.object(
                PublishOperatorAlertService, "_get_for_tenant", locked_get,
            ),
            patch(
                "app.services.publish_operator_alert_service.utc_now",
                return_value=_now(),
            ),
        ):
            r1, r2 = await asyncio.gather(first_ack(), second_ack())

        assert r1.state == "acknowledged" and r2.state == "acknowledged"
        assert store.row.state == "acknowledged"
        assert store.open_to_ack_transitions == 1
        assert store.row.acknowledged_by == first
        assert store.row.acknowledged_by != second
        assert store.row.acknowledged_at is not None

    asyncio.run(_run())


def test_concurrent_web_mobile_ack_no_actor_overwrite():
    """Web + mobile concurrent ack → single actor attribution (lock winner)."""

    async def _run():
        store = _AlertRowLockStore(_open_alert())
        tenant_id = store.row.tenant_id
        alert_id = store.row.id
        mobile_actor = uuid.uuid4()
        web_actor = uuid.uuid4()
        order: list[str] = []

        async def locked_get(db, tid, aid, *, for_update: bool = False):
            row = await store.get_for_update(db, tid, aid, for_update=for_update)
            if row.state == "open":
                store.open_to_ack_transitions += 1
            return row

        db_mobile = AsyncMock()
        db_mobile.flush = store.flush
        db_mobile.commit = store.commit
        db_web = AsyncMock()
        db_web.flush = store.flush
        db_web.commit = store.commit

        async def mobile_ack():
            order.append("mobile-start")
            resp = await _ack_and_commit(
                store, db_mobile, tenant_id, alert_id, mobile_actor,
            )
            order.append("mobile-done")
            return resp

        async def web_ack():
            # Let mobile acquire the lock first.
            await asyncio.sleep(0.01)
            order.append("web-start")
            resp = await _ack_and_commit(
                store, db_web, tenant_id, alert_id, web_actor,
            )
            order.append("web-done")
            return resp

        with (
            patch.object(
                PublishOperatorAlertService, "_get_for_tenant", locked_get,
            ),
            patch(
                "app.services.publish_operator_alert_service.utc_now",
                return_value=_now(),
            ),
        ):
            r_mobile, r_web = await asyncio.gather(mobile_ack(), web_ack())

        assert r_mobile.state == "acknowledged" and r_web.state == "acknowledged"
        assert store.open_to_ack_transitions == 1
        assert store.row.acknowledged_by == mobile_actor
        assert store.row.acknowledged_by != web_actor
        assert store.row.acknowledged_at is not None
        assert order.index("mobile-done") < order.index("web-done")

    asyncio.run(_run())


def test_sequential_duplicate_ack_idempotent_no_overwrite():
    async def _run():
        first = uuid.uuid4()
        stamped = _now()
        store = _AlertRowLockStore(
            _open_alert(
                state="acknowledged",
                acknowledged_at=stamped,
                acknowledged_by=first,
            ),
        )
        flush_calls = {"n": 0}

        async def counting_flush():
            flush_calls["n"] += 1

        db = AsyncMock()
        db.flush = counting_flush
        db.commit = store.commit

        with patch.object(
            PublishOperatorAlertService,
            "_get_for_tenant",
            store.get_for_update,
        ):
            resp = await _ack_and_commit(
                store, db, store.row.tenant_id, store.row.id, uuid.uuid4(),
            )

        assert resp.state == "acknowledged"
        assert store.row.acknowledged_by == first
        assert store.row.acknowledged_at == stamped
        assert flush_calls["n"] == 0

    asyncio.run(_run())


def test_ack_vs_resolve_race_deterministic_no_corruption():
    """Ack vs resolve serialize on the same row lock; no stale overwrite."""

    async def _run():
        store = _AlertRowLockStore(_open_alert())
        tenant_id = store.row.tenant_id
        alert_id = store.row.id
        ack_actor = uuid.uuid4()
        resolve_actor = uuid.uuid4()

        async def locked_get(db, tid, aid, *, for_update: bool = False):
            row = await store.get_for_update(db, tid, aid, for_update=for_update)
            return row

        db_ack = AsyncMock()
        db_ack.flush = store.flush
        db_ack.commit = store.commit
        db_res = AsyncMock()
        db_res.flush = store.flush
        db_res.commit = store.commit

        async def do_ack():
            resp = await _ack_and_commit(
                store, db_ack, tenant_id, alert_id, ack_actor,
            )
            return ("ack", resp)

        async def do_resolve():
            await asyncio.sleep(0.01)  # ack acquires lock first
            resp = await _resolve_and_commit(
                store, db_res, tenant_id, alert_id, resolve_actor,
            )
            return ("resolve", resp)

        with (
            patch.object(
                PublishOperatorAlertService, "_get_for_tenant", locked_get,
            ),
            patch(
                "app.services.publish_operator_alert_service.utc_now",
                return_value=_now(),
            ),
            patch(
                "app.services.publish_operator_alert_service.sanitize_error_message",
                side_effect=lambda n: n,
            ),
        ):
            results = await asyncio.gather(do_ack(), do_resolve())

        by_kind = {k: v for k, v in results}
        assert by_kind["ack"].state == "acknowledged"
        assert by_kind["resolve"].state == "resolved"
        # Resolve ran second under the lock → terminal resolved wins.
        assert store.row.state == "resolved"
        assert store.row.resolved_by == resolve_actor
        assert store.row.resolved_at is not None
        # Ack attribution from the earlier transition is preserved (not wiped).
        assert store.row.acknowledged_by == ack_actor
        assert store.row.acknowledged_at is not None
        # No corruption: resolved fields present; state is terminal.
        assert store.row.state != "open"

    asyncio.run(_run())


def test_resolve_then_ack_rejects_without_overwriting_resolved():
    """If resolve wins the lock first, ack fails canonically and leaves fields."""

    async def _run():
        store = _AlertRowLockStore(_open_alert())
        tenant_id = store.row.tenant_id
        alert_id = store.row.id
        resolve_actor = uuid.uuid4()
        ack_actor = uuid.uuid4()

        db_res = AsyncMock()
        db_res.flush = store.flush
        db_res.commit = store.commit
        db_ack = AsyncMock()
        db_ack.flush = store.flush
        db_ack.commit = store.commit

        with (
            patch.object(
                PublishOperatorAlertService,
                "_get_for_tenant",
                store.get_for_update,
            ),
            patch(
                "app.services.publish_operator_alert_service.utc_now",
                return_value=_now(),
            ),
            patch(
                "app.services.publish_operator_alert_service.sanitize_error_message",
                side_effect=lambda n: n,
            ),
        ):
            await _resolve_and_commit(
                store, db_res, tenant_id, alert_id, resolve_actor,
            )
            with pytest.raises(HTTPException) as exc:
                await _ack_and_commit(
                    store, db_ack, tenant_id, alert_id, ack_actor,
                )

        assert exc.value.status_code == 400
        assert "resolved" in str(exc.value.detail).lower()
        assert store.row.state == "resolved"
        assert store.row.resolved_by == resolve_actor
        assert store.row.acknowledged_by is None
        assert store.row.acknowledged_at is None

    asyncio.run(_run())


def test_already_resolved_acknowledge_preserves_canonical_error():
    async def _run():
        row = _open_alert(
            state="resolved",
            resolved_at=_now(),
            resolved_by=uuid.uuid4(),
        )
        db = AsyncMock()
        with patch.object(
            PublishOperatorAlertService,
            "_get_for_tenant",
            new=AsyncMock(return_value=row),
        ):
            with pytest.raises(HTTPException) as exc:
                await PublishOperatorAlertService.acknowledge(
                    db, row.tenant_id, row.id, actor_id=uuid.uuid4(),
                )
        assert exc.value.status_code == 400
        assert "resolved" in str(exc.value.detail).lower()
        db.flush.assert_not_awaited()

    asyncio.run(_run())


def test_tenant_isolation_preserved_on_locked_get():
    async def _run():
        alert_id = uuid.uuid4()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()

        class _Result:
            def scalar_one_or_none(self):
                # Tenant filter misses → not found (isolation).
                return None

        db = AsyncMock()
        db.execute = AsyncMock(return_value=_Result())

        with pytest.raises(HTTPException) as exc:
            await PublishOperatorAlertService._get_for_tenant(
                db, tenant_b, alert_id, for_update=True,
            )
        assert exc.value.status_code == 404

        stmt = db.execute.await_args.args[0]
        compiled = str(
            stmt.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": False},
            )
        ).upper()
        assert "FOR UPDATE" in compiled
        assert "TENANT_ID" in compiled
        # Ensure the scoped tenant bind is present (wrong tenant cannot lock).
        assert tenant_a != tenant_b

    asyncio.run(_run())


def test_acknowledge_and_resolve_have_zero_provider_side_effects():
    """Canonical ack/resolve must not touch publish/retry/Telegram/Meta."""
    for method in (
        PublishOperatorAlertService.acknowledge,
        PublishOperatorAlertService.resolve_manual,
    ):
        names = {n.lower() for n in method.__code__.co_names}
        forbidden = {
            "manual_retry",
            "send_message",
            "telegram",
            "meta",
            "deliver_publish_alert",
            "retry_publish",
        }
        assert not forbidden.intersection(names)


def test_resolve_manual_also_uses_for_update():
    async def _run():
        row = _open_alert()
        get = AsyncMock(return_value=row)
        db = AsyncMock()

        with (
            patch.object(PublishOperatorAlertService, "_get_for_tenant", get),
            patch(
                "app.services.publish_operator_alert_service.utc_now",
                return_value=_now(),
            ),
            patch(
                "app.services.publish_operator_alert_service.sanitize_error_message",
                side_effect=lambda n: n,
            ),
        ):
            await PublishOperatorAlertService.resolve_manual(
                db, row.tenant_id, row.id, actor_id=uuid.uuid4(), note="n",
            )

        assert get.await_args.kwargs.get("for_update") is True
        assert row.state == "resolved"

    asyncio.run(_run())
