"""Unit tests for the platform event bus (registry, dispatcher, tenant isolation)."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal, ensure_platform_event_bus_schema
from app.core.events import (
    EventBus,
    EventRegistry,
    PlatformEvent,
    SubscriberError,
    TenantIsolationError,
    UnknownEventTypeError,
    build_tenant_event,
    event_registry,
)
from app.core.events.types import EventDefinition, EventIntegrations, SubscriberResult
from app.models.platform_event import TenantActivityEvent
from app.models.tenant import Tenant
from app.services.event_handlers.activity_handler import ActivityEventHandler
from app.services.event_handlers.registration import register_event_bus_subscribers, reset_event_bus_registration
from app.services.platform_event_service import PlatformEventService


def test_registry_contains_core_event_types():
    types = {d.event_type for d in event_registry.list_all()}
    assert "tenant.user.login" in types
    assert "tenant.crm.deal_stage_changed" in types
    assert "tenant.onboarding.platform_ready" in types


def test_registry_integration_flags():
    definition = event_registry.require("tenant.crm.deal_stage_changed")
    assert definition.integrations.audit is True
    assert definition.integrations.notification is True
    assert definition.integrations.automation is True


def test_build_tenant_event_requires_tenant_id():
    tenant_id = uuid4()
    event = build_tenant_event("tenant.user.login", tenant_id, title="Login")
    assert event.tenant_id == tenant_id
    assert event.title == "Login"


def test_bus_rejects_unknown_event_type():
    bus = EventBus()
    bus.freeze()
    event = PlatformEvent(event_type="tenant.unknown.event", tenant_id=uuid4())

    async def _run() -> bool:
        try:
            async with AsyncSessionLocal() as db:
                await bus.publish(db, event)
            return False
        except UnknownEventTypeError:
            return True

    assert asyncio.run(_run())


def test_bus_rejects_missing_tenant_id():
    bus = EventBus()
    bus.freeze()
    event = PlatformEvent(event_type="tenant.user.login", tenant_id=None)

    async def _run() -> bool:
        try:
            async with AsyncSessionLocal() as db:
                await bus.publish(db, event)
            return False
        except TenantIsolationError:
            return True

    assert asyncio.run(_run())


def test_subscriber_pattern_matching():
    bus = EventBus(registry=EventRegistry((
        EventDefinition(
            event_type="tenant.test.event",
            category="test",
            description="Test",
            integrations=EventIntegrations(),
        ),
    )))
    handled: list[str] = []

    class _Handler:
        name = "test_handler"

        async def handle(self, db, event):
            handled.append(event.event_type)
            return SubscriberResult(subscriber=self.name, handled=True)

    bus.subscribe(_Handler(), event_types="tenant.test.*")
    bus.freeze()
    event = PlatformEvent(event_type="tenant.test.event", tenant_id=uuid4())

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await bus.publish(db, event, require_registered=True)

    asyncio.run(_run())
    assert handled == ["tenant.test.event"]


def test_registration_freezes_bus():
    reset_event_bus_registration()
    bus = EventBus()
    register_event_bus_subscribers(bus)
    try:
        bus.subscribe(ActivityEventHandler())
        assert False, "expected RuntimeError"
    except RuntimeError:
        pass
    reset_event_bus_registration()


def test_subscriber_priority_order():
    bus = EventBus(registry=EventRegistry((
        EventDefinition(
            event_type="tenant.test.priority",
            category="test",
            description="Priority test",
            integrations=EventIntegrations(),
        ),
    )))
    order: list[str] = []

    class _High:
        name = "high"

        async def handle(self, db, event):
            order.append(self.name)
            return SubscriberResult(subscriber=self.name, handled=True)

    class _Low:
        name = "low"

        async def handle(self, db, event):
            order.append(self.name)
            return SubscriberResult(subscriber=self.name, handled=True)

    bus.subscribe(_Low(), event_types="tenant.test.priority", priority=200)
    bus.subscribe(_High(), event_types="tenant.test.priority", priority=10)
    bus.freeze()

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await bus.publish(
                db,
                PlatformEvent(event_type="tenant.test.priority", tenant_id=uuid4()),
            )

    asyncio.run(_run())
    assert order == ["high", "low"]


def test_duplicate_subscriber_name_deduped():
    bus = EventBus(registry=EventRegistry((
        EventDefinition(
            event_type="tenant.test.dedupe",
            category="test",
            description="Dedupe test",
            integrations=EventIntegrations(),
        ),
    )))
    calls = 0

    class _Handler:
        name = "dup_handler"

        async def handle(self, db, event):
            nonlocal calls
            calls += 1
            return SubscriberResult(subscriber=self.name, handled=True)

    handler = _Handler()
    bus.subscribe(handler, event_types="tenant.test.dedupe")
    bus.subscribe(handler, event_types="tenant.test.*")
    bus.freeze()

    async def _run() -> None:
        async with AsyncSessionLocal() as db:
            await bus.publish(
                db,
                PlatformEvent(event_type="tenant.test.dedupe", tenant_id=uuid4()),
            )

    asyncio.run(_run())
    assert calls == 1


def test_publish_result_aggregation():
    bus = EventBus(registry=EventRegistry((
        EventDefinition(
            event_type="tenant.test.aggregate",
            category="test",
            description="Aggregate test",
            integrations=EventIntegrations(),
        ),
    )))

    class _A:
        name = "a"

        async def handle(self, db, event):
            return SubscriberResult(subscriber=self.name, handled=True)

    class _B:
        name = "b"

        async def handle(self, db, event):
            return SubscriberResult(subscriber=self.name, handled=False, detail="skipped")

    bus.subscribe(_A())
    bus.subscribe(_B())
    bus.freeze()

    async def _run():
        async with AsyncSessionLocal() as db:
            return await bus.publish(
                db,
                PlatformEvent(event_type="tenant.test.aggregate", tenant_id=uuid4()),
            )

    result = asyncio.run(_run())
    assert result.handled_count == 1
    assert len(result.subscriber_results) == 2
    assert {r.subscriber for r in result.subscriber_results} == {"a", "b"}


def test_event_context_and_payload_fields():
    tenant_id = uuid4()
    actor_id = uuid4()
    occurred = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
    event = PlatformEvent(
        event_type="tenant.user.login",
        tenant_id=tenant_id,
        payload={"ip": "127.0.0.1", "nested": {"k": 1}},
        event_id=uuid4(),
        actor_type="tenant_user",
        actor_id=actor_id,
        resource_type="session",
        resource_id="sess-1",
        title="Login",
        description="User signed in",
        occurred_at=occurred,
        metadata={"source": "test"},
    )
    assert event.require_tenant_id() == tenant_id
    serialized = json.loads(json.dumps(event.payload, default=str))
    assert serialized["nested"]["k"] == 1
    assert event.actor_type == "tenant_user"
    assert event.metadata["source"] == "test"


def test_duplicate_startup_registration_idempotent():
    reset_event_bus_registration()
    bus1 = register_event_bus_subscribers()
    bus2 = register_event_bus_subscribers()
    assert bus1 is bus2
    reset_event_bus_registration()


def test_transaction_commit_and_rollback():
    async def _run() -> None:
        await ensure_platform_event_bus_schema()
        reset_event_bus_registration()
        register_event_bus_subscribers()

        rollback_tenant = uuid4()
        async with AsyncSessionLocal() as db:
            db.add(Tenant(id=rollback_tenant, company_name="Tx Rollback Test", status="active", plan="trial"))
            await db.flush()
            await PlatformEventService.emit(
                db,
                "tenant.content.created",
                rollback_tenant,
                payload={"content_id": str(uuid4())},
                title="Rollback test",
                commit=False,
            )
            count_before = (
                await db.execute(
                    select(func.count())
                    .select_from(TenantActivityEvent)
                    .where(TenantActivityEvent.tenant_id == rollback_tenant),
                )
            ).scalar_one()
            assert int(count_before) >= 1
            await db.rollback()

        async with AsyncSessionLocal() as db:
            count_after = (
                await db.execute(
                    select(func.count())
                    .select_from(TenantActivityEvent)
                    .where(TenantActivityEvent.tenant_id == rollback_tenant),
                )
            ).scalar_one()
            assert int(count_after) == 0

        commit_tenant = uuid4()
        async with AsyncSessionLocal() as db:
            db.add(Tenant(id=commit_tenant, company_name="Tx Commit Test", status="active", plan="trial"))
            await db.commit()
            await PlatformEventService.emit(
                db,
                "tenant.content.created",
                commit_tenant,
                payload={"content_id": str(uuid4())},
                title="Commit test",
                commit=True,
            )

        async with AsyncSessionLocal() as db:
            count = (
                await db.execute(
                    select(func.count())
                    .select_from(TenantActivityEvent)
                    .where(TenantActivityEvent.tenant_id == commit_tenant),
                )
            ).scalar_one()
            assert int(count) >= 1

        reset_event_bus_registration()

    asyncio.run(_run())


def test_subscriber_failure_default_does_not_abort_publish():
    """Default stop_on_error=False: failed subscriber is recorded; caller txn still open."""
    bus = EventBus(registry=EventRegistry((
        EventDefinition(
            event_type="tenant.test.fail",
            category="test",
            description="Failure test",
            integrations=EventIntegrations(),
        ),
    )))

    class _Fail:
        name = "failer"

        async def handle(self, db, event):
            raise RuntimeError("subscriber blew up")

    class _After:
        name = "after"

        async def handle(self, db, event):
            return SubscriberResult(subscriber=self.name, handled=True)

    bus.subscribe(_Fail(), priority=10)
    bus.subscribe(_After(), priority=20)
    bus.freeze()

    async def _run():
        async with AsyncSessionLocal() as db:
            return await bus.publish(
                db,
                PlatformEvent(event_type="tenant.test.fail", tenant_id=uuid4()),
            )

    result = asyncio.run(_run())
    fail = next(r for r in result.subscriber_results if r.subscriber == "failer")
    after = next(r for r in result.subscriber_results if r.subscriber == "after")
    assert fail.handled is False
    assert "blew up" in (fail.detail or "")
    assert after.handled is True


def test_subscriber_failure_stop_on_error_raises():
    bus = EventBus(registry=EventRegistry((
        EventDefinition(
            event_type="tenant.test.stop",
            category="test",
            description="Stop on error",
            integrations=EventIntegrations(),
        ),
    )))

    class _Fail:
        name = "failer"

        async def handle(self, db, event):
            raise ValueError("stop here")

    bus.subscribe(_Fail())
    bus.freeze()

    async def _run() -> bool:
        try:
            async with AsyncSessionLocal() as db:
                await bus.publish(
                    db,
                    PlatformEvent(event_type="tenant.test.stop", tenant_id=uuid4()),
                    stop_on_error=True,
                )
            return False
        except SubscriberError as exc:
            return exc.subscriber_name == "failer"

    assert asyncio.run(_run())


def main() -> int:
    tests = [
        test_registry_contains_core_event_types,
        test_registry_integration_flags,
        test_build_tenant_event_requires_tenant_id,
        test_bus_rejects_unknown_event_type,
        test_bus_rejects_missing_tenant_id,
        test_subscriber_pattern_matching,
        test_registration_freezes_bus,
        test_subscriber_priority_order,
        test_duplicate_subscriber_name_deduped,
        test_publish_result_aggregation,
        test_event_context_and_payload_fields,
        test_duplicate_startup_registration_idempotent,
        test_transaction_commit_and_rollback,
        test_subscriber_failure_default_does_not_abort_publish,
        test_subscriber_failure_stop_on_error_raises,
    ]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"OK {test.__name__}")
        except Exception as exc:
            failures += 1
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
