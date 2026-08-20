"""PostgreSQL-backed regression: waiting-client UUID aggregation must not use min(uuid)."""
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import case, func, or_, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.api_auth_context import ApiAuthContext, _auth_ctx
from app.models.client import Client
from app.models.content import ContentItem
from app.services.content_review_service import (
    CLIENT_REVIEW_CHANGES,
    CLIENT_REVIEW_PENDING,
)
from app.services.operator_workspace_service import OperatorWorkspaceService

# Disposable local Postgres 16 started for this regression suite.
# Override with OPERATOR_WORKSPACE_PG_URL if needed.
DEFAULT_PG_URL = (
    "postgresql+asyncpg://postgres:password@127.0.0.1:54329/uuid_fix"
)


def _pg_url() -> str:
    return os.environ.get("OPERATOR_WORKSPACE_PG_URL", DEFAULT_PG_URL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _wait_ready(engine, attempts: int = 40) -> None:
    last_exc: Exception | None = None
    for _ in range(attempts):
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return
        except Exception as exc:  # noqa: BLE001 — readiness probe
            last_exc = exc
            await asyncio.sleep(0.5)
    raise RuntimeError(f"PostgreSQL not ready: {last_exc}")


async def _setup_schema(engine) -> None:
    async with engine.begin() as conn:
        await conn.execute(text("DROP TABLE IF EXISTS content_items CASCADE"))
        await conn.execute(text("DROP TABLE IF EXISTS clients CASCADE"))
        # Minimal columns referenced by the waiting-client window query.
        await conn.execute(
            text(
                """
                CREATE TABLE clients (
                    id UUID PRIMARY KEY,
                    company_name VARCHAR(255) NOT NULL,
                    tenant_id UUID NULL
                )
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TABLE content_items (
                    id UUID PRIMARY KEY,
                    client_id UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
                    status VARCHAR(30) NOT NULL DEFAULT 'draft',
                    client_review_status VARCHAR(30) NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )


async def _insert_client(session: AsyncSession, *, client_id: uuid.UUID, name: str) -> None:
    await session.execute(
        text("INSERT INTO clients (id, company_name) VALUES (:id, :name)"),
        {"id": client_id, "name": name},
    )


async def _insert_waiting(
    session: AsyncSession,
    *,
    content_id: uuid.UUID,
    client_id: uuid.UUID,
    updated_at: datetime,
    review_status: str = "pending",
    status: str = "ready_for_approval",
) -> None:
    await session.execute(
        text(
            """
            INSERT INTO content_items
                (id, client_id, status, client_review_status, updated_at)
            VALUES
                (:id, :client_id, :status, :review_status, :updated_at)
            """
        ),
        {
            "id": content_id,
            "client_id": client_id,
            "status": status,
            "review_status": review_status,
            "updated_at": updated_at,
        },
    )


async def _with_pg(coro_factory):
    url = _pg_url()
    engine = create_async_engine(url, echo=False)
    try:
        await _wait_ready(engine)
        await _setup_schema(engine)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            await coro_factory(session)
    except OSError as exc:
        pytest.skip(f"PostgreSQL 16 test DB unavailable at {url}: {exc}")
    except Exception as exc:
        msg = str(exc).lower()
        if "connect" in msg or "refused" in msg or "not ready" in msg:
            pytest.skip(f"PostgreSQL 16 test DB unavailable at {url}: {exc}")
        raise
    finally:
        await engine.dispose()


def test_pg_uuid_waiting_single_item_count_and_deep_link():
    client_id = uuid.uuid4()
    content_id = uuid.uuid4()
    now = _now()

    async def _body(session: AsyncSession):
        await _insert_client(session, client_id=client_id, name="Single Co")
        await _insert_waiting(
            session,
            content_id=content_id,
            client_id=client_id,
            updated_at=now - timedelta(hours=2),
        )
        await session.commit()

        token = _auth_ctx.set(ApiAuthContext(kind="admin", tenant_id=None, client_ids=()))
        try:
            items: list = []
            await OperatorWorkspaceService._collect_waiting_client(session, None, items.append)
        finally:
            _auth_ctx.reset(token)

        assert len(items) == 1
        item = items[0]
        assert item.client_id == client_id
        assert item.metadata["count"] == 1
        assert item.content_id == content_id
        assert item.action_path == f"/content/{content_id}"
        assert item.responsible_party == "client"

        summary = OperatorWorkspaceService._build_summary(items)
        assert summary.waiting_for_client == 1
        assert summary.total == 1

    asyncio.run(_with_pg(_body))


def test_pg_uuid_waiting_multiple_items_deterministic_representative():
    client_id = uuid.uuid4()
    older_id = uuid.uuid4()
    newer_id = uuid.uuid4()
    newest_id = uuid.uuid4()
    now = _now()

    async def _body(session: AsyncSession):
        await _insert_client(session, client_id=client_id, name="Multi Co")
        await _insert_waiting(
            session,
            content_id=older_id,
            client_id=client_id,
            updated_at=now - timedelta(days=3),
        )
        await _insert_waiting(
            session,
            content_id=newer_id,
            client_id=client_id,
            updated_at=now - timedelta(days=2),
            review_status="changes_requested",
        )
        await _insert_waiting(
            session,
            content_id=newest_id,
            client_id=client_id,
            updated_at=now - timedelta(hours=1),
        )
        await session.commit()

        token = _auth_ctx.set(ApiAuthContext(kind="admin", tenant_id=None, client_ids=()))
        try:
            items: list = []
            await OperatorWorkspaceService._collect_waiting_client(session, None, items.append)
        finally:
            _auth_ctx.reset(token)

        assert len(items) == 1
        item = items[0]
        assert item.metadata["count"] == 3
        assert item.content_id is None
        assert item.action_path == f"/content?client_id={client_id}"
        assert item.metadata["reason_code"] == "client_changes"
        assert item.created_at is not None
        assert abs((item.created_at - (now - timedelta(days=3))).total_seconds()) < 2

        # Deterministic representative = most recently updated row.
        await session.execute(
            text("DELETE FROM content_items WHERE id != :keep"),
            {"keep": newest_id},
        )
        await session.commit()
        items2: list = []
        token2 = _auth_ctx.set(ApiAuthContext(kind="admin", tenant_id=None, client_ids=()))
        try:
            await OperatorWorkspaceService._collect_waiting_client(session, None, items2.append)
        finally:
            _auth_ctx.reset(token2)
        assert len(items2) == 1
        assert items2[0].content_id == newest_id
        assert items2[0].action_path == f"/content/{newest_id}"

    asyncio.run(_with_pg(_body))


def test_pg_uuid_waiting_cross_client_grouping():
    client_a = uuid.uuid4()
    client_b = uuid.uuid4()
    a1 = uuid.uuid4()
    a2 = uuid.uuid4()
    b1 = uuid.uuid4()
    now = _now()

    async def _body(session: AsyncSession):
        await _insert_client(session, client_id=client_a, name="A Co")
        await _insert_client(session, client_id=client_b, name="B Co")
        await _insert_waiting(
            session, content_id=a1, client_id=client_a, updated_at=now - timedelta(days=1)
        )
        await _insert_waiting(
            session, content_id=a2, client_id=client_a, updated_at=now - timedelta(hours=2)
        )
        await _insert_waiting(
            session, content_id=b1, client_id=client_b, updated_at=now - timedelta(hours=5)
        )
        await session.commit()

        token = _auth_ctx.set(ApiAuthContext(kind="admin", tenant_id=None, client_ids=()))
        try:
            items: list = []
            await OperatorWorkspaceService._collect_waiting_client(session, None, items.append)
        finally:
            _auth_ctx.reset(token)

        assert len(items) == 2
        by_client = {i.client_id: i for i in items}
        assert by_client[client_a].metadata["count"] == 2
        assert by_client[client_a].content_id is None
        assert by_client[client_a].action_path == f"/content?client_id={client_a}"
        assert by_client[client_b].metadata["count"] == 1
        assert by_client[client_b].content_id == b1
        assert by_client[client_b].action_path == f"/content/{b1}"

        summary = OperatorWorkspaceService._build_summary(items)
        assert summary.waiting_for_client == 2
        assert summary.total == 2

    asyncio.run(_with_pg(_body))


def test_pg_uuid_waiting_tenant_client_scope_enforced():
    owned = uuid.uuid4()
    other = uuid.uuid4()
    owned_content = uuid.uuid4()
    other_content = uuid.uuid4()
    tenant_id = uuid.uuid4()
    now = _now()

    async def _body(session: AsyncSession):
        await _insert_client(session, client_id=owned, name="Owned")
        await _insert_client(session, client_id=other, name="Other")
        await _insert_waiting(
            session,
            content_id=owned_content,
            client_id=owned,
            updated_at=now - timedelta(hours=1),
        )
        await _insert_waiting(
            session,
            content_id=other_content,
            client_id=other,
            updated_at=now - timedelta(hours=1),
        )
        await session.commit()

        token = _auth_ctx.set(
            ApiAuthContext(kind="tenant", tenant_id=tenant_id, client_ids=(owned,))
        )
        try:
            items: list = []
            await OperatorWorkspaceService._collect_waiting_client(session, None, items.append)
        finally:
            _auth_ctx.reset(token)

        assert len(items) == 1
        assert items[0].client_id == owned
        assert items[0].content_id == owned_content
        assert items[0].action_path == f"/content/{owned_content}"
        assert items[0].content_id != other_content

    asyncio.run(_with_pg(_body))


def test_pg_uuid_waiting_compiled_sql_has_no_min_uuid():
    waiting_filter = or_(
        ContentItem.client_review_status == CLIENT_REVIEW_PENDING,
        ContentItem.client_review_status == CLIENT_REVIEW_CHANGES,
        ContentItem.status == "changes_requested",
    )
    changes_expr = case(
        (
            or_(
                ContentItem.client_review_status == CLIENT_REVIEW_CHANGES,
                ContentItem.status == "changes_requested",
            ),
            1,
        ),
        else_=0,
    )
    ranked = (
        select(
            ContentItem.client_id.label("client_id"),
            Client.company_name.label("company_name"),
            ContentItem.id.label("representative_id"),
            func.count(ContentItem.id).over(partition_by=ContentItem.client_id).label("cnt"),
            func.min(ContentItem.updated_at)
            .over(partition_by=ContentItem.client_id)
            .label("oldest"),
            func.max(changes_expr).over(partition_by=ContentItem.client_id).label("has_changes"),
            func.row_number()
            .over(
                partition_by=ContentItem.client_id,
                order_by=(ContentItem.updated_at.desc(), ContentItem.id.desc()),
            )
            .label("rn"),
        )
        .join(Client, Client.id == ContentItem.client_id)
        .where(waiting_filter)
    ).subquery("waiting_client_ranked")
    query = (
        select(
            ranked.c.client_id,
            ranked.c.company_name,
            ranked.c.cnt,
            ranked.c.oldest,
            ranked.c.representative_id,
            ranked.c.has_changes,
        )
        .where(ranked.c.rn == 1)
        .order_by(ranked.c.oldest.asc())
    )
    compiled = str(
        query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False})
    ).lower()
    assert "min(content_items.id)" not in compiled
    assert "max(content_items.id)" not in compiled
    assert "row_number()" in compiled

    async def _body(session: AsyncSession):
        # Must execute cleanly on real PostgreSQL UUID columns.
        await session.execute(query)

    asyncio.run(_with_pg(_body))
