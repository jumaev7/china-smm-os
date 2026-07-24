"""Advertising account lifecycle (tenant-scoped, read-only toward providers).

Registers/mirrors advertising accounts, lists/gets them, disconnects them, and
reports capabilities/permissions via the provider adapter. No provider tokens
are ever stored here (credentials live on ``publishing_accounts``). Cross-tenant
access resolves to 404.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import TenantAdvertisingAccount
from app.services.advertising_intelligence.errors import (
    AdAccountDisconnectedError,
    AdAccountNotFoundError,
)
from app.services.advertising_intelligence.limits import (
    MAX_ACCOUNTS_PER_TENANT,
    enforce_child_count,
)
from app.services.advertising_intelligence.providers import get_adapter
from app.services.automation_domain_events import emit_domain_event

_READABLE_CONNECTION_STATUSES = frozenset({"connected"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def connection_status_for(account: TenantAdvertisingAccount) -> str:
    if account.is_mock or account.provider == "mock":
        return "mock"
    return account.connection_status or "unknown"


async def _account_count(db: AsyncSession, tenant_id: UUID) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(TenantAdvertisingAccount).where(
                    TenantAdvertisingAccount.tenant_id == tenant_id
                )
            )
        ).scalar_one()
        or 0
    )


async def register_account(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    provider: str,
    provider_account_id: str,
    name: str | None = None,
    currency: str | None = None,
    timezone: str | None = None,
    platform: str | None = None,
    is_mock: bool = False,
    integration_id: UUID | None = None,
    created_by: UUID | None = None,
) -> TenantAdvertisingAccount:
    """Idempotently register (or reactivate) an advertising account.

    Unique per ``(tenant, provider, provider_account_id)``. Emits
    ``advertising.account_connected`` on create or reactivation.
    """
    existing = (
        await db.execute(
            select(TenantAdvertisingAccount).where(
                TenantAdvertisingAccount.tenant_id == tenant_id,
                TenantAdvertisingAccount.provider == provider,
                TenantAdvertisingAccount.provider_account_id == provider_account_id,
            )
        )
    ).scalar_one_or_none()

    reactivated = False
    if existing is not None:
        account = existing
        if account.connection_status != "connected":
            account.connection_status = "connected"
            account.disconnected_at = None
            reactivated = True
        if name:
            account.name = name
        if currency:
            account.currency = currency.upper()
        if timezone:
            account.timezone = timezone
        await db.flush()
        if not reactivated:
            return account
    else:
        enforce_child_count(await _account_count(db, tenant_id), MAX_ACCOUNTS_PER_TENANT, "accounts_per_tenant")
        account = TenantAdvertisingAccount(
            tenant_id=tenant_id,
            provider=provider,
            platform=platform or ("mock" if is_mock else None),
            provider_account_id=provider_account_id,
            name=name,
            currency=(currency or "USD").upper() if (currency or is_mock) else currency,
            timezone=timezone,
            account_status="active",
            connection_status="connected",
            is_mock=is_mock,
            integration_id=integration_id,
        )
        db.add(account)
        await db.flush()

    await emit_domain_event(
        db,
        "advertising.account_connected",
        tenant_id,
        payload={
            "ad_account_id": str(account.id),
            "provider": provider,
            "is_mock": bool(account.is_mock),
            "status": account.connection_status,
        },
        actor_id=created_by,
        resource_type="advertising_account",
        resource_id=str(account.id),
        title="Advertising account connected",
    )
    return account


async def register_mock_accounts(
    db: AsyncSession,
    tenant_id: UUID,
    specs: list[dict],
    *,
    created_by: UUID | None = None,
) -> list[TenantAdvertisingAccount]:
    """Convenience: register several mock accounts from ``{provider_account_id, name, currency}`` specs."""
    accounts: list[TenantAdvertisingAccount] = []
    for spec in specs:
        accounts.append(
            await register_account(
                db, tenant_id,
                provider=spec.get("provider", "mock"),
                provider_account_id=spec["provider_account_id"],
                name=spec.get("name"),
                currency=spec.get("currency"),
                timezone=spec.get("timezone"),
                is_mock=True,
                created_by=created_by,
            )
        )
    return accounts


async def get_account(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> TenantAdvertisingAccount:
    account = (
        await db.execute(
            select(TenantAdvertisingAccount).where(
                TenantAdvertisingAccount.id == account_id,
                TenantAdvertisingAccount.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise AdAccountNotFoundError("advertising account not found")
    return account


async def list_accounts(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    provider: str | None = None,
    status: str | None = None,
) -> list[TenantAdvertisingAccount]:
    filters = [TenantAdvertisingAccount.tenant_id == tenant_id]
    if provider:
        filters.append(TenantAdvertisingAccount.provider == provider)
    if status:
        filters.append(TenantAdvertisingAccount.connection_status == status)
    return list(
        (
            await db.execute(
                select(TenantAdvertisingAccount)
                .where(*filters)
                .order_by(TenantAdvertisingAccount.created_at.desc())
            )
        ).scalars().all()
    )


async def disconnect_account(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    *,
    actor_id: UUID | None = None,
) -> TenantAdvertisingAccount:
    account = await get_account(db, tenant_id, account_id)
    if account.connection_status == "disconnected":
        return account
    account.connection_status = "disconnected"
    account.disconnected_at = _utcnow()
    await db.flush()
    await emit_domain_event(
        db,
        "advertising.account_disconnected",
        tenant_id,
        payload={
            "ad_account_id": str(account.id),
            "provider": account.provider,
            "status": "disconnected",
        },
        actor_id=actor_id,
        resource_type="advertising_account",
        resource_id=str(account.id),
        title="Advertising account disconnected",
    )
    return account


async def account_capabilities(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> dict:
    account = await get_account(db, tenant_id, account_id)
    adapter = get_adapter(account.provider)
    caps = adapter.capabilities(connection_status=connection_status_for(account))
    return {
        "provider": caps.provider,
        "capability_status": caps.capability_status,
        "supports_structure_import": caps.supports_structure_import,
        "supports_insights": caps.supports_insights,
        "supports_conversions": caps.supports_conversions,
        "supports_breakdowns": caps.supports_breakdowns,
        "supported_metric_keys": sorted(caps.supported_metric_keys),
        "supported_breakdowns": sorted(caps.supported_breakdowns),
        "unsupported_reason": caps.unsupported_reason,
        "notes": caps.notes,
        "read_only": True,
    }


async def permission_summary(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> dict:
    account = await get_account(db, tenant_id, account_id)
    return {
        "account_id": account_id,
        "provider": account.provider,
        "connection_status": account.connection_status,
        "readable": is_readable(account),
        "permission_summary": account.permission_summary or {},
        "read_only": True,
    }


def is_readable(account: TenantAdvertisingAccount) -> bool:
    return bool(account.is_mock) or account.connection_status in _READABLE_CONNECTION_STATUSES


def require_readable(account: TenantAdvertisingAccount) -> None:
    if not is_readable(account):
        raise AdAccountDisconnectedError(
            "advertising account is not connected",
            details={"connection_status": account.connection_status},
        )


__all__ = [
    "connection_status_for",
    "register_account",
    "register_mock_accounts",
    "get_account",
    "list_accounts",
    "disconnect_account",
    "account_capabilities",
    "permission_summary",
    "is_readable",
    "require_readable",
]
