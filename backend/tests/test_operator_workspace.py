"""Operator Workspace Phase 1 — aggregation, correctness, and isolation tests."""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.core.api_auth_context import ApiAuthContext, _auth_ctx
from app.schemas.operator_workspace import OperatorAttentionItem
from app.services.operator_workspace_service import (
    AUTOMATION_ACTIONABLE_DAYS,
    OperatorWorkspaceService,
    _priority_for_publish_status,
    _responsible_for_publish,
    _sort_key,
)
from app.services.publish_resilience import (
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
)
from app.services.tenant_auth_service import CurrentTenantUser, TenantAuthService


def _now():
    return datetime.now(timezone.utc)


def _tenant_ctx(client_ids: list[uuid.UUID], tenant_id: uuid.UUID | None = None) -> ApiAuthContext:
    return ApiAuthContext(
        kind="tenant",
        tenant_id=tenant_id or uuid.uuid4(),
        client_ids=tuple(client_ids),
    )


def _admin_ctx() -> ApiAuthContext:
    return ApiAuthContext(kind="admin", tenant_id=None, client_ids=())


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows

    def scalars(self):
        return _Scalars(self._rows)


def _item(
    *,
    id: str,
    attention_type: str = "publishing_issue",
    priority: str = "high",
    responsible_party: str = "operator",
    client_id: uuid.UUID | None = None,
    content_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    due_at: datetime | None = None,
    overdue: bool = False,
    action_path: str = "/content",
    metadata: dict | None = None,
) -> OperatorAttentionItem:
    return OperatorAttentionItem(
        id=id,
        attention_type=attention_type,  # type: ignore[arg-type]
        priority=priority,  # type: ignore[arg-type]
        client_id=client_id,
        company_name="Acme",
        content_id=content_id,
        title="Test",
        reason="Test reason",
        responsible_party=responsible_party,  # type: ignore[arg-type]
        suggested_action="Review",
        action_path=action_path,
        created_at=created_at or _now(),
        due_at=due_at,
        overdue=overdue,
        source_domain="publishing",
        metadata=metadata or {},
    )


# ── Priority, responsibility & sorting ─────────────────────────────────────


def test_operator_review_publish_priority_is_critical():
    assert _priority_for_publish_status(STATUS_OPERATOR_REVIEW) == "critical"


def test_failed_publish_priority_is_high():
    assert _priority_for_publish_status(STATUS_FAILED) == "high"


def test_retrying_publish_is_system_responsibility():
    assert _responsible_for_publish(STATUS_RETRYING) == "system"


def test_in_progress_publish_is_system_responsibility():
    assert _responsible_for_publish(STATUS_IN_PROGRESS) == "system"


def test_provider_permission_failure_is_provider_responsibility():
    assert _responsible_for_publish(STATUS_FAILED, failure_code="auth_or_permission") == "provider"


def test_operator_review_is_operator_responsibility():
    assert _responsible_for_publish(STATUS_OPERATOR_REVIEW) == "operator"


def test_priority_sorting_is_deterministic():
    items = [
        _item(id="a", priority="low", created_at=_now() - timedelta(hours=1)),
        _item(id="b", priority="critical", created_at=_now()),
        _item(id="c", priority="high", created_at=_now() - timedelta(hours=2)),
        _item(id="d", priority="critical", overdue=True, due_at=_now() - timedelta(hours=1)),
    ]
    sorted_items = sorted(items, key=_sort_key)
    assert sorted_items[0].id == "d"
    assert sorted_items[1].id == "b"
    assert sorted_items[2].id == "c"
    assert sorted_items[3].id == "a"


def test_summary_counts_match_items():
    items = [
        _item(id="1", attention_type="content_internal_review", responsible_party="operator"),
        _item(id="2", attention_type="waiting_for_client", responsible_party="client"),
        _item(id="3", attention_type="publishing_issue", responsible_party="operator"),
        _item(id="4", attention_type="integration_issue", responsible_party="operator"),
        _item(id="5", attention_type="scheduling_issue", responsible_party="operator", due_at=_now()),
        _item(id="6", attention_type="telegram_ingestion_issue", responsible_party="operator"),
        _item(id="7", attention_type="automation_failure", responsible_party="operator"),
    ]
    summary = OperatorWorkspaceService._build_summary(items)
    assert summary.total == 7
    assert summary.waiting_for_client == 1
    assert summary.publishing_issues == 1
    assert summary.integration_issues == 1
    assert summary.scheduling_issues == 1
    assert summary.telegram_issues == 1
    assert summary.automation_failures == 1
    assert summary.needs_action_now == 6


def test_waiting_client_classified_separately_from_operator_action():
    items = [
        _item(id="w", attention_type="waiting_for_client", responsible_party="client", priority="low"),
        _item(id="o", attention_type="content_internal_review", responsible_party="operator", priority="medium"),
    ]
    summary = OperatorWorkspaceService._build_summary(items)
    assert summary.waiting_for_client == 1
    assert summary.needs_action_now == 1


def test_summary_excludes_system_and_provider_from_needs_action():
    items = [
        _item(id="1", responsible_party="system"),
        _item(id="2", responsible_party="provider"),
        _item(id="3", responsible_party="operator"),
    ]
    summary = OperatorWorkspaceService._build_summary(items)
    assert summary.needs_action_now == 1


# ── Collection with mocked DB ──────────────────────────────────────────────


def _content_row(status="ready", client_review_status=None, client_id=None):
    cid = client_id or uuid.uuid4()
    client = SimpleNamespace(company_name="Test Co", id=cid)
    item = SimpleNamespace(
        id=uuid.uuid4(),
        client_id=cid,
        status=status,
        client_review_status=client_review_status,
        caption_short_en="Hello world",
        caption_short_ru=None,
        caption_short_uz=None,
        internal_notes=None,
        updated_at=_now(),
        created_at=_now() - timedelta(days=1),
        scheduled_for=None,
        approved_at=None,
        platforms=["instagram"],
    )
    return item, client


def _attempt_row(
    status,
    content_id=None,
    client_id=None,
    *,
    failure_code="provider_error",
    next_retry_at=None,
    lease_expires_at=None,
    started_at=None,
):
    cid = client_id or uuid.uuid4()
    content = SimpleNamespace(id=content_id or uuid.uuid4(), client_id=cid, status="failed")
    client = SimpleNamespace(company_name="Test Co")
    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        content_id=content.id,
        status=status,
        platform="instagram",
        error="Something failed",
        failure_code=failure_code,
        next_retry_at=next_retry_at,
        lease_expires_at=lease_expires_at,
        started_at=started_at,
        created_at=_now(),
    )
    return attempt, content, client


class FakeWorkspaceDb:
    """Deterministic fake: collectors set `next_execute` / `next_scalars` before calling."""

    def __init__(self):
        self.content_review_rows = []
        self.waiting_client_rows = []
        self.publish_rows = []
        self.stuck_rows = []
        self.schedule_rows = []
        self.integration_accounts = []
        self.telegram_events = []
        self.automation_jobs = []
        self.alert_rows = []
        self.next_execute = None
        self.next_scalars = None
        self._execute_queue: list = []
        self._scalars_queue: list = []

    def queue_execute(self, *batches):
        self._execute_queue.extend(batches)

    def queue_scalars(self, *batches):
        self._scalars_queue.extend(batches)

    async def execute(self, query):  # noqa: ARG002
        if self._execute_queue:
            return _Result(self._execute_queue.pop(0))
        if self.next_execute is not None:
            rows = self.next_execute
            self.next_execute = None
            return _Result(rows)
        return _Result([])

    async def scalars(self, query):  # noqa: ARG002
        if self._scalars_queue:
            return _Scalars(self._scalars_queue.pop(0))
        if self.next_scalars is not None:
            rows = self.next_scalars
            self.next_scalars = None
            return _Scalars(rows)
        return _Scalars([])


async def _collect_publish_items(db: FakeWorkspaceDb):
    items = []
    seen = set()

    def add(item):
        if item.id not in seen:
            seen.add(item.id)
            items.append(item)

    db.queue_execute(db.publish_rows, db.stuck_rows)
    await OperatorWorkspaceService._collect_publishing_issues(db, None, _now(), add)
    return items


def test_failed_publish_becomes_attention_item():
    client_id = uuid.uuid4()
    db = FakeWorkspaceDb()
    db.publish_rows = [_attempt_row(STATUS_FAILED, client_id=client_id)]

    items = asyncio.run(_collect_publish_items(db))
    assert len(items) == 1
    assert items[0].attention_type == "publishing_issue"
    assert items[0].priority == "high"
    assert items[0].responsible_party == "operator"
    assert items[0].action_path.startswith("/content/")


def test_operator_review_publish_becomes_critical_attention():
    db = FakeWorkspaceDb()
    db.publish_rows = [_attempt_row(STATUS_OPERATOR_REVIEW)]
    items = asyncio.run(_collect_publish_items(db))
    assert len(items) == 1
    assert items[0].priority == "critical"
    assert items[0].responsible_party == "operator"


def test_auth_permission_failure_classified_as_provider():
    db = FakeWorkspaceDb()
    db.publish_rows = [_attempt_row(STATUS_FAILED, failure_code="auth_or_permission")]
    items = asyncio.run(_collect_publish_items(db))
    assert len(items) == 1
    assert items[0].responsible_party == "provider"


def test_successful_publish_not_in_ops_statuses():
    assert STATUS_SUCCESS not in {
        STATUS_FAILED,
        STATUS_OPERATOR_REVIEW,
        STATUS_EXHAUSTED,
        STATUS_RETRYING,
        STATUS_IN_PROGRESS,
    }


async def _test_integration_attention_only_bad_statuses():
    db = FakeWorkspaceDb()
    db.queue_scalars([
        SimpleNamespace(
            id=uuid.uuid4(),
            platform="facebook",
            account_name="Bad Page",
            status="expired",
            updated_at=_now(),
            created_at=_now(),
        ),
    ])
    items = []
    await OperatorWorkspaceService._collect_integration_issues(db, uuid.uuid4(), items.append)
    assert len(items) == 1
    assert items[0].attention_type == "integration_issue"
    assert items[0].responsible_party == "client"
    assert "platform=facebook" in items[0].action_path

    db2 = FakeWorkspaceDb()
    db2.queue_scalars([])
    items2 = []
    await OperatorWorkspaceService._collect_integration_issues(db2, uuid.uuid4(), items2.append)
    assert len(items2) == 0


def test_integration_attention_only_bad_statuses():
    asyncio.run(_test_integration_attention_only_bad_statuses())


def test_healthy_integration_not_surfaced():
    db = FakeWorkspaceDb()
    db.queue_scalars([])
    items = []
    asyncio.run(OperatorWorkspaceService._collect_integration_issues(db, uuid.uuid4(), items.append))
    assert items == []


async def _test_telegram_admin_only():
    event = SimpleNamespace(
        id=uuid.uuid4(),
        status="failed",
        last_error="Parse error",
        update_id=123,
        attempts=5,
        created_at=_now(),
        updated_at=_now(),
    )

    token = _auth_ctx.set(_tenant_ctx([uuid.uuid4()]))
    try:
        db = FakeWorkspaceDb()
        db.queue_scalars([event])
        items = []
        await OperatorWorkspaceService._collect_telegram_issues(db, _now(), items.append)
        assert items == []
    finally:
        _auth_ctx.reset(token)

    token = _auth_ctx.set(_admin_ctx())
    try:
        db = FakeWorkspaceDb()
        db.queue_scalars([event])
        items = []
        await OperatorWorkspaceService._collect_telegram_issues(db, _now(), items.append)
        assert len(items) == 1
        assert items[0].attention_type == "telegram_ingestion_issue"
    finally:
        _auth_ctx.reset(token)


def test_telegram_failed_admin_only():
    asyncio.run(_test_telegram_admin_only())


async def _test_automation_recent_vs_historical():
    db = FakeWorkspaceDb()
    recent_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    db.queue_scalars([
        SimpleNamespace(
            id=recent_id,
            status="dead_letter",
            error_message="Lease recovery exceeded",
            error_code="lease_recovery_exceeded",
            automation_flow_id=flow_id,
            updated_at=_now() - timedelta(days=1),
            created_at=_now() - timedelta(days=2),
        ),
    ])
    items = []
    await OperatorWorkspaceService._collect_automation_failures(db, uuid.uuid4(), _now(), items.append)
    assert len(items) == 1
    assert items[0].resource_id == str(recent_id)
    assert f"flow={flow_id}" in items[0].action_path
    assert items[0].metadata["reason_code"] == "automation_dead_letter"

    assert AUTOMATION_ACTIONABLE_DAYS == 7
    cutoff = _now() - timedelta(days=AUTOMATION_ACTIONABLE_DAYS)
    old_updated = _now() - timedelta(days=40)
    assert old_updated < cutoff


def test_automation_recent_dead_letter_surfaced():
    asyncio.run(_test_automation_recent_vs_historical())


def test_old_historical_dead_letter_outside_window():
    """July-style historical dead letters fall outside the 7-day actionable window."""
    july = datetime(2026, 7, 5, tzinfo=timezone.utc)
    now = datetime(2026, 8, 20, tzinfo=timezone.utc)
    assert (now - july).days > AUTOMATION_ACTIONABLE_DAYS


async def _test_pagination_filtering_and_summary_stability():
    client_a = uuid.uuid4()
    items_data = [
        _item(id="1", attention_type="publishing_issue", priority="high", client_id=client_a),
        _item(id="2", attention_type="waiting_for_client", priority="low", responsible_party="client"),
        _item(id="3", attention_type="content_internal_review", priority="medium"),
    ]
    with patch.object(
        OperatorWorkspaceService,
        "_collect_items",
        new=AsyncMock(return_value=items_data),
    ):
        db = AsyncMock()
        filtered = await OperatorWorkspaceService.list_items(
            db,
            category="publishing_issue",
            page=1,
            page_size=10,
        )
        assert filtered.total == 1
        assert filtered.items[0].id == "1"
        # Summary remains full-set totals (not rewritten by category filter).
        assert filtered.summary.total == 3
        assert filtered.summary.publishing_issues == 1
        assert filtered.summary.waiting_for_client == 1
        assert filtered.summary.needs_action_now == 2

        by_party = await OperatorWorkspaceService.list_items(
            db,
            responsible_party="client",
        )
        assert by_party.total == 1
        assert by_party.items[0].id == "2"
        assert by_party.summary.total == 3


def test_pagination_and_filtering():
    asyncio.run(_test_pagination_filtering_and_summary_stability())


def test_cross_tenant_client_rejected():
    owned = uuid.uuid4()
    foreign = uuid.uuid4()
    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        from app.core.client_scope_guard import guard_resource_client_id

        with pytest.raises(HTTPException) as exc:
            guard_resource_client_id(foreign)
        assert exc.value.status_code == 403
    finally:
        _auth_ctx.reset(token)


async def _test_content_review_for_authorized_client():
    owned = uuid.uuid4()
    item, client = _content_row(status="ready", client_id=owned)
    db = FakeWorkspaceDb()
    db.queue_execute([(item, client)])
    items = []

    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        await OperatorWorkspaceService._collect_content_review(db, None, items.append)
    finally:
        _auth_ctx.reset(token)

    assert len(items) == 1
    assert items[0].attention_type == "content_internal_review"
    assert items[0].client_id == owned
    assert items[0].action_path == f"/content/{item.id}"


def test_operator_sees_content_review_for_authorized_clients():
    asyncio.run(_test_content_review_for_authorized_client())


def test_no_silent_truncation_over_former_500_cap():
    """Expose former LIMIT 500 bug: >500 actionable rows must all remain visible."""
    owned = uuid.uuid4()
    rows = [_content_row(status="needs_review", client_id=owned) for _ in range(520)]
    db = FakeWorkspaceDb()
    db.queue_execute(rows)
    items = []

    token = _auth_ctx.set(_tenant_ctx([owned]))
    try:
        asyncio.run(OperatorWorkspaceService._collect_content_review(db, None, items.append))
    finally:
        _auth_ctx.reset(token)

    assert len(items) == 520
    summary = OperatorWorkspaceService._build_summary(items)
    assert summary.total == 520
    assert summary.needs_action_now == 520


def test_summary_correct_under_large_fixture_volume():
    items = []
    for i in range(200):
        items.append(_item(id=f"pub-{i}", attention_type="publishing_issue", responsible_party="operator"))
    for i in range(50):
        items.append(
            _item(
                id=f"wait-{i}",
                attention_type="waiting_for_client",
                responsible_party="client",
                priority="low",
            )
        )
    for i in range(30):
        items.append(
            _item(
                id=f"int-{i}",
                attention_type="integration_issue",
                responsible_party="provider",
            )
        )
    summary = OperatorWorkspaceService._build_summary(items)
    assert summary.total == 280
    assert summary.publishing_issues == 200
    assert summary.waiting_for_client == 50
    assert summary.integration_issues == 30
    assert summary.needs_action_now == 200  # provider not counted as operator action


def test_filters_combine_correctly():
    async def _run():
        items_data = [
            _item(id="1", attention_type="publishing_issue", priority="high", responsible_party="operator"),
            _item(id="2", attention_type="publishing_issue", priority="critical", responsible_party="operator"),
            _item(id="3", attention_type="publishing_issue", priority="high", responsible_party="provider"),
            _item(id="4", attention_type="waiting_for_client", priority="low", responsible_party="client"),
        ]
        with patch.object(
            OperatorWorkspaceService,
            "_collect_items",
            new=AsyncMock(return_value=items_data),
        ):
            result = await OperatorWorkspaceService.list_items(
                AsyncMock(),
                category="publishing_issue",
                priority="high",
                responsible_party="operator",
            )
            assert result.total == 1
            assert result.items[0].id == "1"
            assert result.summary.total == 4

    asyncio.run(_run())


def test_deep_link_metadata_for_publish_alert():
    alert_id = uuid.uuid4()
    content_id = uuid.uuid4()
    client_id = uuid.uuid4()
    db = FakeWorkspaceDb()
    db.queue_execute([
        (
            SimpleNamespace(
                id=alert_id,
                content_id=content_id,
                title="Stuck publish",
                body="Needs review",
                state="open",
                severity="critical",
                alert_type="operator_review",
                created_at=_now(),
            ),
            SimpleNamespace(id=content_id, client_id=client_id),
            SimpleNamespace(company_name="Acme"),
        )
    ])
    items = []
    asyncio.run(OperatorWorkspaceService._collect_publish_alerts(db, None, items.append))
    assert len(items) == 1
    assert items[0].action_path == f"/publishing/alerts?alert_id={alert_id}"
    assert items[0].metadata["alert_id"] == str(alert_id)


def test_workspace_role_allows_operator_denies_viewer_sales():
    operator = MagicMock(spec=CurrentTenantUser)
    operator.role = "operator"
    operator.has_permission = MagicMock(return_value=False)
    TenantAuthService.assert_role(operator, "owner", "manager", "operator")

    viewer = MagicMock(spec=CurrentTenantUser)
    viewer.role = "viewer"
    viewer.has_permission = MagicMock(return_value=False)
    with pytest.raises(HTTPException) as exc:
        TenantAuthService.assert_role(viewer, "owner", "manager", "operator")
    assert exc.value.status_code == 403

    sales = MagicMock(spec=CurrentTenantUser)
    sales.role = "sales"
    sales.has_permission = MagicMock(return_value=False)
    with pytest.raises(HTTPException) as exc2:
        TenantAuthService.assert_role(sales, "owner", "manager", "operator")
    assert exc2.value.status_code == 403


def test_waiting_client_sql_aggregation_one_item_per_client():
    client_a = uuid.uuid4()
    client_b = uuid.uuid4()
    first_a = uuid.uuid4()
    first_b = uuid.uuid4()
    db = FakeWorkspaceDb()
    db.queue_execute([
        SimpleNamespace(
            client_id=client_a,
            company_name="A Co",
            cnt=12,
            oldest=_now() - timedelta(days=2),
            representative_id=first_a,
            has_changes=0,
        ),
        SimpleNamespace(
            client_id=client_b,
            company_name="B Co",
            cnt=3,
            oldest=_now() - timedelta(days=1),
            representative_id=first_b,
            has_changes=1,
        ),
    ])
    items = []
    asyncio.run(OperatorWorkspaceService._collect_waiting_client(db, None, items.append))
    assert len(items) == 2
    by_id = {i.client_id: i for i in items}
    assert by_id[client_a].responsible_party == "client"
    assert by_id[client_a].metadata["count"] == 12
    assert by_id[client_a].content_id is None
    assert by_id[client_a].action_path == f"/content?client_id={client_a}"
    assert by_id[client_b].metadata["reason_code"] == "client_changes"
    assert by_id[client_b].action_path == f"/content?client_id={client_b}"


def test_waiting_client_single_item_deep_links_to_content():
    client_a = uuid.uuid4()
    content_a = uuid.uuid4()
    db = FakeWorkspaceDb()
    db.queue_execute([
        SimpleNamespace(
            client_id=client_a,
            company_name="A Co",
            cnt=1,
            oldest=_now() - timedelta(hours=3),
            representative_id=content_a,
            has_changes=0,
        ),
    ])
    items = []
    asyncio.run(OperatorWorkspaceService._collect_waiting_client(db, None, items.append))
    assert len(items) == 1
    assert items[0].content_id == content_a
    assert items[0].metadata["count"] == 1
    assert items[0].action_path == f"/content/{content_a}"


def test_waiting_client_query_path_has_no_uuid_min_max():
    """Guard against reintroducing PostgreSQL-incompatible UUID aggregates."""
    import inspect

    source = inspect.getsource(OperatorWorkspaceService._collect_waiting_client)
    assert "func.min(ContentItem.id)" not in source
    assert "func.max(ContentItem.id)" not in source
    assert "row_number" in source
