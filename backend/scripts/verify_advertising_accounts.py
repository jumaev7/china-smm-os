"""Verify Advertising account lifecycle (tenant-scoped, read-only toward providers).

Covers: registering a mock account, idempotent unique identity, currency
normalization, timezone capture, cross-tenant access resolving to 404, and
disconnect. Uses the real DB via ``ensure_advertising_schema``.

Run from backend/:  python scripts/verify_advertising_accounts.py
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


def main() -> int:
    import asyncio
    return asyncio.run(_run())


async def _run() -> int:
    from app.core.database import (
        AsyncSessionLocal,
        engine,
        ensure_campaign_planner_schema,
        ensure_measurement_schema,
        ensure_platform_event_bus_schema,
        reset_advertising_schema,
    )
    from app.models.tenant import Tenant
    from app.services.advertising_intelligence import account_service
    from app.services.advertising_intelligence.errors import AdAccountNotFoundError

    engine.echo = False
    await ensure_platform_event_bus_schema()
    await ensure_campaign_planner_schema()
    await reset_advertising_schema()
    await ensure_measurement_schema()

    stamp = int(datetime.now(timezone.utc).timestamp())
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    async with AsyncSessionLocal() as db:
        tenant = Tenant(id=uuid4(), company_name=f"Ad Accts {stamp}", status="active", plan="trial")
        tenant_b = Tenant(id=uuid4(), company_name=f"Ad Accts B {stamp}", status="active", plan="trial")
        db.add_all([tenant, tenant_b])
        await db.commit()

        provider_account_id = f"mockacct-{stamp}"
        account = await account_service.register_account(
            db, tenant.id,
            provider="mock", provider_account_id=provider_account_id,
            name="Primary Mock Account", currency="eur", timezone="Europe/Berlin",
            is_mock=True,
        )
        await db.commit()
        record("register_mock", account.is_mock and account.connection_status == "connected")
        record("currency_normalized_upper", account.currency == "EUR", str(account.currency))
        record("timezone_captured", account.timezone == "Europe/Berlin", str(account.timezone))
        record("mock_platform_default", account.platform in ("mock", None), str(account.platform))

        # Idempotent unique identity — same (tenant, provider, provider_account_id).
        again = await account_service.register_account(
            db, tenant.id,
            provider="mock", provider_account_id=provider_account_id,
            name="Primary Mock Account", is_mock=True,
        )
        await db.commit()
        record("unique_identity_idempotent", again.id == account.id, f"{again.id} vs {account.id}")

        accounts = await account_service.list_accounts(db, tenant.id)
        record("single_account_after_reregister", len(accounts) == 1, str(len(accounts)))

        # Same provider_account_id under a DIFFERENT tenant is a distinct row.
        other = await account_service.register_account(
            db, tenant_b.id,
            provider="mock", provider_account_id=provider_account_id, is_mock=True,
        )
        await db.commit()
        record("distinct_per_tenant", other.id != account.id)

        # Cross-tenant access resolves to not-found (404 mapping).
        cross_tenant_404 = False
        try:
            await account_service.get_account(db, tenant_b.id, account.id)
        except AdAccountNotFoundError:
            cross_tenant_404 = True
        record("cross_tenant_404", cross_tenant_404)
        record("cross_tenant_error_status", AdAccountNotFoundError.http_status == 404)

        # Capabilities / permission surface (read-only).
        caps = await account_service.account_capabilities(db, tenant.id, account.id)
        record("capabilities_read_only", caps.get("read_only") is True and caps.get("supports_insights"))
        perms = await account_service.permission_summary(db, tenant.id, account.id)
        record("permission_summary_read_only", perms.get("read_only") is True and perms.get("readable") is True)

        # Disconnect (mock account: status flips, but mock stays readable).
        disconnected = await account_service.disconnect_account(db, tenant.id, account.id)
        await db.commit()
        record("disconnect_status", disconnected.connection_status == "disconnected")
        record("disconnect_timestamp", disconnected.disconnected_at is not None)

        # Disconnect is idempotent.
        disconnected_again = await account_service.disconnect_account(db, tenant.id, account.id)
        record("disconnect_idempotent", disconnected_again.connection_status == "disconnected")

        # A non-mock (live) account becomes unreadable once disconnected.
        live = await account_service.register_account(
            db, tenant.id, provider="meta",
            provider_account_id=f"liveacct-{stamp}", is_mock=False,
        )
        await db.commit()
        record("live_connected_readable", account_service.is_readable(live) is True)
        live_off = await account_service.disconnect_account(db, tenant.id, live.id)
        await db.commit()
        record("live_disconnect_not_readable", account_service.is_readable(live_off) is False)

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
