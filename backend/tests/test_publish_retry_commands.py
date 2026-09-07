"""Phase 3C.1B — durable publish retry command foundation.

No provider I/O, PublishService, resulting attempts, alerts, Telegram, or Meta.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from app.models.publish_retry_command import (
    RETRY_COMMAND_ACTIVE_STATUSES,
    PublishRetryCommand,
)
from app.services import publish_retry_command_service as cmd_mod
from app.services.manual_retry_eligibility import ManualRetryEligibility
from app.services.publish_retry_command_service import (
    PublishRetryCommandService,
    build_destination_key,
    build_retry_command_idempotency_key,
    serialize_retry_command,
)


def _now():
    return datetime.now(timezone.utc)


def _allow_eligibility(**kwargs):
    defaults = dict(
        allowed=True,
        reason_code="allowed",
        safety_class="CONDITIONAL_MANUAL_RETRY",
        confirmation_tier="medium",
        external_side_effect=True,
        operator_message="Allowed",
        mobile_eligible=False,
    )
    defaults.update(kwargs)
    return ManualRetryEligibility(**defaults)


def _deny_eligibility(**kwargs):
    defaults = dict(
        allowed=False,
        reason_code="not_on_allowlist",
        safety_class="OPERATOR_REVIEW",
        confirmation_tier="high",
        external_side_effect=True,
        operator_message="Manual retry unavailable",
        mobile_eligible=False,
    )
    defaults.update(kwargs)
    return ManualRetryEligibility(**defaults)


class FakeCommandDb:
    """In-memory session with active-idempotency uniqueness + savepoints."""

    def __init__(self):
        self.tenant_id = uuid.uuid4()
        self.other_tenant_id = uuid.uuid4()
        self.client_id = uuid.uuid4()
        self.content_id = uuid.uuid4()
        self.account_id = uuid.uuid4()
        self.attempt_id = uuid.uuid4()
        self.commands: list[PublishRetryCommand] = []
        self.audit_events: list = []
        self.flushed = 0
        self.committed = 0
        self.publish_version = "pv_abc"
        self.platform = "telegram"
        self.content_status = "failed"
        self.attempt_status = "failed"
        self.failure_code = "rate_limited"
        self._insert_gate = asyncio.Lock()
        self._pending_by_task: dict = {}
        self.bundle_tenant_id = None
        self.bundle_content_client_id = None
        self.bundle_miss = False

    def _attempt(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=self.attempt_id,
            content_id=self.content_id,
            platform=self.platform,
            account_id=self.account_id,
            status=self.attempt_status,
            failure_code=self.failure_code,
            publish_version=self.publish_version,
            attempt_number=1,
            external_post_id=None,
            next_retry_at=None,
            idempotency_key="idem-1",
            account=SimpleNamespace(status="connected", account_name="Bot A"),
        )

    def _content(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=self.content_id,
            client_id=self.bundle_content_client_id or self.client_id,
            status=self.content_status,
            updated_at=_now(),
        )

    def _client(self) -> SimpleNamespace:
        return SimpleNamespace(
            id=self.client_id,
            tenant_id=self.bundle_tenant_id or self.tenant_id,
            company_name="Acme",
        )

    def _active_key_taken(self, key: str) -> bool:
        return any(
            c.idempotency_key == key and c.status in RETRY_COMMAND_ACTIVE_STATUSES
            for c in self.commands
        )

    def _is_command_query(self, query) -> bool:
        try:
            cols = list(query.column_descriptions)
            if cols:
                entity = cols[0].get("entity")
                typ = cols[0].get("type")
                if entity is PublishRetryCommand or typ is PublishRetryCommand:
                    return True
        except Exception:
            pass
        return "publish_retry_commands" in str(query).lower()

    def _bound_filters(self, query) -> dict:
        """Extract equality / IN filters from SQLAlchemy where criteria."""
        filters: dict = {}
        for crit in getattr(query, "_where_criteria", ()):
            try:
                left = getattr(crit, "left", None)
                right = getattr(crit, "right", None)
                key = getattr(left, "key", None)
                if key is None:
                    continue
                # Equality bind
                if hasattr(right, "value"):
                    filters[key] = right.value
                    continue
                # IN (...) — ExpandingBindParameter or ClauseList
                if type(crit).__name__ in {"In", "in_op"} or getattr(
                    crit, "operator", None
                ) is not None and "in_op" in str(getattr(crit, "operator", "")):
                    values = getattr(right, "value", None)
                    if values is None and hasattr(right, "clauses"):
                        values = [
                            getattr(c, "value", c) for c in right.clauses
                        ]
                    if values is not None:
                        filters[f"{key}_in"] = set(values)
            except Exception:
                continue
        # Fallback via compiled params
        if not filters:
            try:
                compiled = query.compile(compile_kwargs={"literal_binds": False})
                for k, v in (compiled.params or {}).items():
                    base = k.rsplit("_", 1)[0] if "_" in k and k[-1].isdigit() else k
                    # sqlalchemy names like idempotency_key_1
                    for candidate in (
                        "idempotency_key",
                        "tenant_id",
                        "id",
                        "status",
                    ):
                        if k == candidate or k.startswith(f"{candidate}_"):
                            filters[candidate] = v
            except Exception:
                pass
        return filters

    async def execute(self, query):  # noqa: ARG002
        class _BundleResult:
            def __init__(self, outer: FakeCommandDb):
                self._outer = outer

            def one_or_none(self):
                if self._outer.bundle_miss:
                    return None
                return (
                    self._outer._attempt(),
                    self._outer._content(),
                    self._outer._client(),
                )

        class _Scalars:
            def __init__(self, items):
                self._items = items

            def first(self):
                return self._items[0] if self._items else None

            def all(self):
                return self._items

        class _Result:
            def __init__(self, items):
                self._items = items

            def scalar_one_or_none(self):
                return self._items[0] if self._items else None

            def scalars(self):
                return _Scalars(self._items)

        if self._is_command_query(query):
            filtered = list(self.commands)
            f = self._bound_filters(query)
            if "tenant_id" in f:
                filtered = [c for c in filtered if c.tenant_id == f["tenant_id"]]
            if "idempotency_key" in f:
                filtered = [
                    c for c in filtered if c.idempotency_key == f["idempotency_key"]
                ]
            if "id" in f:
                filtered = [c for c in filtered if c.id == f["id"]]
            if "status_in" in f:
                filtered = [c for c in filtered if c.status in f["status_in"]]
            elif "status" in f and isinstance(f["status"], (list, set, tuple)):
                filtered = [c for c in filtered if c.status in set(f["status"])]
            # Detect active-status IN via SQL text when bind expansion is opaque
            qtext = str(query)
            if (
                "status_in" not in f
                and "pending" in qtext
                and "claimed" in qtext
                and "provider_write_started" in qtext
            ):
                filtered = [
                    c for c in filtered if c.status in RETRY_COMMAND_ACTIVE_STATUSES
                ]
            return _Result(filtered)

        return _BundleResult(self)

    def add(self, obj):
        task = asyncio.current_task()
        self._pending_by_task.setdefault(task, []).append(obj)

    async def flush(self):
        self.flushed += 1
        task = asyncio.current_task()
        pending = list(self._pending_by_task.pop(task, []))
        async with self._insert_gate:
            for obj in pending:
                if isinstance(obj, PublishRetryCommand):
                    if self._active_key_taken(obj.idempotency_key):
                        raise IntegrityError(
                            "active idempotency",
                            params=None,
                            orig=Exception("uq"),
                        )
                    if obj.created_at is None:
                        obj.created_at = _now()
                    if obj.updated_at is None:
                        obj.updated_at = _now()
                    if obj not in self.commands:
                        self.commands.append(obj)
                else:
                    self.audit_events.append(obj)

    async def commit(self):
        await self.flush()
        self.committed += 1

    async def refresh(self, obj):  # noqa: ARG002
        return None

    def begin_nested(self):
        @asynccontextmanager
        async def _cm():
            yield self

        return _cm()

    async def get(self, model, pk):  # noqa: ARG002
        return SimpleNamespace(id=pk)


@pytest.fixture
def enable_commands(monkeypatch):
    monkeypatch.setattr(cmd_mod.settings, "PUBLISH_RETRY_COMMANDS_ENABLED", True)


@pytest.fixture
def disable_commands(monkeypatch):
    monkeypatch.setattr(cmd_mod.settings, "PUBLISH_RETRY_COMMANDS_ENABLED", False)


def _patch_eligibility(allowed: bool = True):
    elig = _allow_eligibility() if allowed else _deny_eligibility()
    return patch.multiple(
        cmd_mod,
        build_manual_retry_live_state=AsyncMock(return_value=SimpleNamespace()),
        evaluate_manual_retry_eligibility=MagicMock(return_value=elig),
        log_manual_retry_denied=MagicMock(),
        tenant_id_for_content_optional=AsyncMock(
            side_effect=lambda db, content: getattr(db, "tenant_id", None),
        ),
        PlatformAuditService=SimpleNamespace(
            record=AsyncMock(return_value=SimpleNamespace()),
        ),
    )


def test_idempotency_key_deterministic():
    tenant = uuid.uuid4()
    content = uuid.uuid4()
    account = uuid.uuid4()
    attempt = uuid.uuid4()
    a = build_retry_command_idempotency_key(
        tenant_id=tenant,
        content_id=content,
        platform="Telegram",
        publishing_account_id=account,
        publish_version="pv_1",
        original_attempt_id=attempt,
    )
    b = build_retry_command_idempotency_key(
        tenant_id=tenant,
        content_id=content,
        platform="telegram",
        publishing_account_id=account,
        publish_version="pv_1",
        original_attempt_id=attempt,
    )
    assert a == b
    assert str(attempt) in a
    assert build_destination_key(platform="telegram", publishing_account_id=account).startswith(
        "telegram:"
    )


def test_serialize_omits_lease_owner_and_secrets():
    cmd = PublishRetryCommand(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        client_id=uuid.uuid4(),
        content_id=uuid.uuid4(),
        original_attempt_id=uuid.uuid4(),
        platform="telegram",
        publishing_account_id=None,
        publish_version="pv_1",
        destination_key="telegram:none",
        requested_by=None,
        requested_source="admin",
        idempotency_key="k",
        status="pending",
        correlation_id=str(uuid.uuid4()),
        lease_owner="worker:abc",
        created_at=_now(),
        updated_at=_now(),
    )
    payload = serialize_retry_command(cmd)
    assert "lease_owner" not in payload
    assert "idempotency_key" not in payload
    assert payload["command_id"] == cmd.id
    assert payload["status"] == "pending"


def test_flag_off_creates_nothing(disable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(True):
            result = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert result.ok is False
        assert result.outcome == "disabled"
        assert result.created is False
        assert db.commands == []
        assert db.committed == 0

    asyncio.run(_run())


def test_eligibility_denied_creates_nothing(enable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(False):
            result = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="workspace",
            )
        assert result.ok is False
        assert result.outcome == "denied"
        assert result.created is False
        assert db.commands == []

    asyncio.run(_run())


def test_create_pending_command(enable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(True):
            result = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                actor_id=uuid.uuid4(),
                source="admin",
            )
        assert result.ok is True
        assert result.created is True
        assert result.outcome == "created"
        assert result.command is not None
        assert result.command.status == "pending"
        assert result.command.resulting_attempt_id is None
        assert result.command.provider_outcome is None
        assert result.command.correlation_id
        assert len(db.commands) == 1

    asyncio.run(_run())


def test_duplicate_after_commit_returns_same(enable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(True):
            first = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
            second = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert first.created is True
        assert second.created is False
        assert second.outcome == "active_reuse"
        assert second.command.id == first.command.id
        assert len(db.commands) == 1

    asyncio.run(_run())


def test_concurrent_create_one_row(enable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(True):
            results = await asyncio.gather(
                PublishRetryCommandService.create_or_get_command(
                    db,
                    tenant_id=db.tenant_id,
                    original_attempt_id=db.attempt_id,
                    source="admin",
                ),
                PublishRetryCommandService.create_or_get_command(
                    db,
                    tenant_id=db.tenant_id,
                    original_attempt_id=db.attempt_id,
                    source="admin",
                ),
            )
        assert len(db.commands) == 1
        assert results[0].command.id == results[1].command.id
        assert sum(1 for r in results if r.created) == 1
        assert sum(1 for r in results if r.outcome == "active_reuse") == 1

    asyncio.run(_run())


def test_lost_response_finds_same_active(enable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(True):
            first = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
            again = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert again.command.id == first.command.id
        assert again.outcome == "active_reuse"

    asyncio.run(_run())


def _seed_command(db: FakeCommandDb, *, status: str) -> PublishRetryCommand:
    key = build_retry_command_idempotency_key(
        tenant_id=db.tenant_id,
        content_id=db.content_id,
        platform=db.platform,
        publishing_account_id=db.account_id,
        publish_version=db.publish_version,
        original_attempt_id=db.attempt_id,
    )
    cmd = PublishRetryCommand(
        id=uuid.uuid4(),
        tenant_id=db.tenant_id,
        client_id=db.client_id,
        content_id=db.content_id,
        original_attempt_id=db.attempt_id,
        resulting_attempt_id=None,
        platform=db.platform,
        publishing_account_id=db.account_id,
        publish_version=db.publish_version,
        destination_key=build_destination_key(
            platform=db.platform, publishing_account_id=db.account_id,
        ),
        requested_by=None,
        requested_source="admin",
        idempotency_key=key,
        status=status,
        correlation_id=str(uuid.uuid4()),
        created_at=_now(),
        updated_at=_now(),
        finished_at=_now() if status not in RETRY_COMMAND_ACTIVE_STATUSES else None,
    )
    db.commands.append(cmd)
    return cmd


@pytest.mark.parametrize("status", ["claimed", "provider_write_started"])
def test_duplicate_while_active_non_pending(enable_commands, status):
    async def _run():
        db = FakeCommandDb()
        seeded = _seed_command(db, status=status)
        with _patch_eligibility(True):
            result = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert result.created is False
        assert result.outcome == "active_reuse"
        assert result.command.id == seeded.id
        assert len(db.commands) == 1

    asyncio.run(_run())


@pytest.mark.parametrize(
    "status,outcome,ok",
    [
        ("succeeded", "terminal_reuse", True),
        ("ambiguous", "terminal_reuse", True),
        ("blocked", "terminal_reuse", True),
        ("superseded", "terminal_reuse", True),
        ("failed", "terminal_failed_closed", False),
    ],
)
def test_terminal_duplicate_behavior(enable_commands, status, outcome, ok):
    async def _run():
        db = FakeCommandDb()
        seeded = _seed_command(db, status=status)
        with _patch_eligibility(True):
            result = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert result.ok is ok
        assert result.created is False
        assert result.outcome == outcome
        assert result.command.id == seeded.id
        assert len(db.commands) == 1

    asyncio.run(_run())


def test_different_publish_version_distinct_identity(enable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(True):
            first = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
            db.publish_version = "pv_other"
            second = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert first.created is True
        assert second.created is True
        assert first.command.id != second.command.id
        assert len(db.commands) == 2

    asyncio.run(_run())


def test_different_account_distinct_identity(enable_commands):
    async def _run():
        db = FakeCommandDb()
        with _patch_eligibility(True):
            first = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
            db.account_id = uuid.uuid4()
            second = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert first.command.id != second.command.id
        assert len(db.commands) == 2

    asyncio.run(_run())


def test_cross_tenant_denied(enable_commands):
    async def _run():
        db = FakeCommandDb()
        db.bundle_miss = True
        with _patch_eligibility(True):
            with pytest.raises(HTTPException) as exc:
                await PublishRetryCommandService.create_or_get_command(
                    db,
                    tenant_id=db.other_tenant_id,
                    original_attempt_id=db.attempt_id,
                    source="admin",
                )
        assert exc.value.status_code == 404
        assert db.commands == []

    asyncio.run(_run())


def test_tenant_client_mismatch_denied(enable_commands):
    async def _run():
        db = FakeCommandDb()
        db.bundle_content_client_id = uuid.uuid4()
        with _patch_eligibility(True):
            with pytest.raises(HTTPException) as exc:
                await PublishRetryCommandService.create_or_get_command(
                    db,
                    tenant_id=db.tenant_id,
                    original_attempt_id=db.attempt_id,
                    source="admin",
                )
        assert exc.value.status_code == 404
        assert db.commands == []

    asyncio.run(_run())


def test_create_has_zero_provider_side_effects(enable_commands):
    async def _run():
        db = FakeCommandDb()
        publish_content = AsyncMock()
        manual_retry = AsyncMock()
        upsert_alert = AsyncMock()
        deliver = AsyncMock()

        with _patch_eligibility(True):
            with patch(
                "app.services.publish_service.PublishService.publish_content",
                publish_content,
            ), patch(
                "app.services.publish_attempt_ops_service.PublishAttemptOpsService.manual_retry",
                manual_retry,
            ), patch(
                "app.services.publish_operator_alert_service."
                "PublishOperatorAlertService.upsert_failure_alert",
                upsert_alert,
            ), patch(
                "app.services.publish_alert_delivery.deliver_publish_alert",
                deliver,
            ):
                result = await PublishRetryCommandService.create_or_get_command(
                    db,
                    tenant_id=db.tenant_id,
                    original_attempt_id=db.attempt_id,
                    source="admin",
                )

        assert result.created is True
        publish_content.assert_not_called()
        manual_retry.assert_not_called()
        upsert_alert.assert_not_called()
        deliver.assert_not_called()
        assert result.command.resulting_attempt_id is None
        assert db._attempt().status == "failed"
        assert db._content().status == "failed"

    asyncio.run(_run())


def test_duplicate_collapse_does_not_recreate_audit(enable_commands):
    async def _run():
        db = FakeCommandDb()
        audit = AsyncMock(return_value=SimpleNamespace())
        with patch.multiple(
            cmd_mod,
            build_manual_retry_live_state=AsyncMock(return_value=SimpleNamespace()),
            evaluate_manual_retry_eligibility=MagicMock(return_value=_allow_eligibility()),
            log_manual_retry_denied=MagicMock(),
            tenant_id_for_content_optional=AsyncMock(
                side_effect=lambda db_inner, content: db_inner.tenant_id,
            ),
            PlatformAuditService=SimpleNamespace(record=audit),
        ):
            await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
            await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert audit.await_count == 1

    asyncio.run(_run())


def test_get_command_tenant_scoped(enable_commands):
    async def _run():
        db = FakeCommandDb()
        seeded = _seed_command(db, status="pending")
        got = await PublishRetryCommandService.get_command(
            db, seeded.id, tenant_id=db.tenant_id,
        )
        assert got.id == seeded.id
        with pytest.raises(HTTPException) as exc:
            await PublishRetryCommandService.get_command(
                db, seeded.id, tenant_id=db.other_tenant_id,
            )
        assert exc.value.status_code == 404

    asyncio.run(_run())


def test_statuses_preserve_provider_write_boundary():
    assert "provider_write_started" in RETRY_COMMAND_ACTIVE_STATUSES
    assert "claimed" in RETRY_COMMAND_ACTIVE_STATUSES
    assert "provider_write_started" != "claimed"


def test_empty_allowlist_still_blocks_without_monkeypatch(enable_commands):
    """Production allowlist empty → create denied when real eligibility is used."""
    async def _run():
        db = FakeCommandDb()
        with patch.object(
            cmd_mod,
            "build_manual_retry_live_state",
            AsyncMock(
                return_value=SimpleNamespace(
                    has_live_success=False,
                    content_status="failed",
                    current_publish_version="pv_abc",
                    account_status="connected",
                    now=_now(),
                ),
            ),
        ), patch.object(
            cmd_mod,
            "tenant_id_for_content_optional",
            AsyncMock(side_effect=lambda db_inner, content: db_inner.tenant_id),
        ), patch.object(
            cmd_mod,
            "PlatformAuditService",
            SimpleNamespace(record=AsyncMock()),
        ):
            # Real evaluate_manual_retry_eligibility — allowlist empty
            result = await PublishRetryCommandService.create_or_get_command(
                db,
                tenant_id=db.tenant_id,
                original_attempt_id=db.attempt_id,
                source="admin",
            )
        assert result.ok is False
        assert result.outcome == "denied"
        assert db.commands == []

    asyncio.run(_run())
