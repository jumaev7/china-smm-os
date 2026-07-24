"""Structural import lifecycle for advertising entities (read-only).

Reads account structure (campaigns → ad groups → ads → creatives) from a
provider adapter and mirrors it into the canonical per-type tables via
``identity_registry`` (which also appends immutable history). Never writes to
the provider. Idempotent: re-running only records changes.

Emits ``advertising.import_requested`` / ``advertising.entities_imported`` /
``advertising.import_failed`` domain events.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAdImportRun,
    TenantAdvertisingAccount,
)
from app.services.advertising_intelligence import identity_registry
from app.services.advertising_intelligence.errors import (
    AdAccountNotFoundError,
    AdImportFailedError,
    AdProviderUnsupportedError,
)
from app.services.advertising_intelligence.limits import (
    MAX_ENTITIES_PER_IMPORT_RUN,
    enforce,
)
from app.services.advertising_intelligence.providers import get_adapter
from app.services.advertising_intelligence.schemas import StructureFetchRequest
from app.services.automation_domain_events import emit_domain_event


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _connection_status(account: TenantAdvertisingAccount) -> str:
    if account.is_mock or account.provider == "mock":
        return "mock"
    return account.connection_status or "unknown"


async def _load_account(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> TenantAdvertisingAccount:
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


async def import_account(
    db: AsyncSession,
    tenant_id: UUID,
    account_id: UUID,
    *,
    requested_by: UUID | None = None,
    scope: str = "full",
) -> TenantAdImportRun:
    """Import provider structure for one account. Returns the import run."""
    account = await _load_account(db, tenant_id, account_id)
    connection_status = _connection_status(account)
    adapter = get_adapter(account.provider)
    capabilities = adapter.capabilities(connection_status=connection_status)

    run = TenantAdImportRun(
        tenant_id=tenant_id,
        advertising_account_id=account_id,
        provider=account.provider,
        scope=scope,
        status="running",
        started_at=_utcnow(),
    )
    db.add(run)
    await db.flush()

    await emit_domain_event(
        db,
        "advertising.import_requested",
        tenant_id,
        payload={
            "ad_account_id": str(account_id),
            "provider": account.provider,
            "import_run_id": str(run.id),
            "is_mock": bool(account.is_mock),
        },
        actor_id=requested_by,
        resource_type="advertising_import_run",
        resource_id=str(run.id),
        title="Advertising import requested",
    )

    if not capabilities.supports_structure_import:
        run.status = "failed"
        run.failure_code = "provider_unsupported"
        run.failure_metadata = {"capability_status": capabilities.capability_status}
        run.completed_at = _utcnow()
        await db.flush()
        await emit_domain_event(
            db, "advertising.import_failed", tenant_id,
            payload={
                "ad_account_id": str(account_id), "provider": account.provider,
                "import_run_id": str(run.id), "failure_code": "provider_unsupported",
                "capability_status": capabilities.capability_status,
            },
            resource_type="advertising_import_run", resource_id=str(run.id),
            title="Advertising import failed",
        )
        raise AdProviderUnsupportedError(
            capabilities.unsupported_reason or "Structure import is not supported for this account.",
            details={"provider": account.provider, "capability_status": capabilities.capability_status},
        )

    response = await adapter.fetch_structure(
        StructureFetchRequest(
            tenant_id=tenant_id,
            provider=account.provider,
            connection_status=connection_status,
            provider_account_id=account.provider_account_id,
            scope=scope,
        )
    )

    if response.status != "ok":
        run.status = "failed"
        run.failure_code = response.status
        run.failure_metadata = {"message": response.message}
        run.completed_at = _utcnow()
        run.provider_request_count = response.provider_request_count
        await db.flush()
        await emit_domain_event(
            db, "advertising.import_failed", tenant_id,
            payload={
                "ad_account_id": str(account_id), "provider": account.provider,
                "import_run_id": str(run.id), "failure_code": response.status,
            },
            resource_type="advertising_import_run", resource_id=str(run.id),
            title="Advertising import failed",
        )
        raise AdImportFailedError(
            response.message or "Provider structure fetch failed.",
            details={"status": response.status},
        )

    total_entities = (
        len(response.campaigns) + len(response.ad_groups)
        + len(response.ads) + len(response.creatives)
    )
    enforce(total_entities, MAX_ENTITIES_PER_IMPORT_RUN, "entities_per_import_run")

    observed_at = _utcnow()
    created = updated = unchanged = failed = 0

    def _tally(change: str) -> None:
        nonlocal created, updated, unchanged
        if change == "created":
            created += 1
        elif change == "updated":
            updated += 1
        else:
            unchanged += 1

    # Account currency defaults from provider account payload if available.
    if response.account is not None:
        if response.account.currency and not account.currency:
            account.currency = response.account.currency
        if response.account.timezone and not account.timezone:
            account.timezone = response.account.timezone

    campaign_by_provider: dict[str, UUID] = {}
    for campaign in response.campaigns:
        try:
            row, change = await identity_registry.upsert_campaign(
                db, tenant_id=tenant_id, account_id=account_id, provider=account.provider,
                campaign=campaign, observed_at=observed_at, import_run_id=run.id,
                source="mock" if account.is_mock else "provider",
            )
            campaign_by_provider[campaign.provider_campaign_id] = row.id
            _tally(change)
        except Exception:  # noqa: BLE001 - isolate a single entity failure
            failed += 1

    ad_group_by_provider: dict[str, UUID] = {}
    ad_group_campaign: dict[str, UUID | None] = {}
    for ad_group in response.ad_groups:
        campaign_id = campaign_by_provider.get(ad_group.provider_campaign_id or "")
        try:
            row, change = await identity_registry.upsert_ad_group(
                db, tenant_id=tenant_id, account_id=account_id, provider=account.provider,
                ad_group=ad_group, campaign_id=campaign_id, observed_at=observed_at,
                import_run_id=run.id, source="mock" if account.is_mock else "provider",
            )
            ad_group_by_provider[ad_group.provider_ad_group_id] = row.id
            ad_group_campaign[ad_group.provider_ad_group_id] = campaign_id
            _tally(change)
        except Exception:  # noqa: BLE001
            failed += 1

    creative_by_provider: dict[str, UUID] = {}
    for creative in response.creatives:
        try:
            row, change = await identity_registry.upsert_creative(
                db, tenant_id=tenant_id, account_id=account_id, provider=account.provider,
                creative=creative, observed_at=observed_at, import_run_id=run.id,
                source="mock" if account.is_mock else "provider",
            )
            creative_by_provider[creative.provider_creative_id] = row.id
            _tally(change)
        except Exception:  # noqa: BLE001
            failed += 1

    for ad in response.ads:
        ad_group_id = ad_group_by_provider.get(ad.provider_ad_group_id or "")
        campaign_id = ad_group_campaign.get(ad.provider_ad_group_id or "")
        creative_id = creative_by_provider.get(ad.provider_creative_id or "")
        try:
            _, change = await identity_registry.upsert_ad(
                db, tenant_id=tenant_id, account_id=account_id, provider=account.provider,
                ad=ad, campaign_id=campaign_id, ad_group_id=ad_group_id,
                creative_id=creative_id, observed_at=observed_at, import_run_id=run.id,
                source="mock" if account.is_mock else "provider",
            )
            _tally(change)
        except Exception:  # noqa: BLE001
            failed += 1

    account.last_import_at = observed_at
    account.last_successful_sync_at = observed_at

    run.status = "partial" if failed else "succeeded"
    run.completed_at = _utcnow()
    run.entities_requested = total_entities
    run.entities_created = created
    run.entities_updated = updated
    run.entities_unchanged = unchanged
    run.entities_failed = failed
    run.provider_request_count = response.provider_request_count
    await db.flush()

    await emit_domain_event(
        db,
        "advertising.entities_imported",
        tenant_id,
        payload={
            "ad_account_id": str(account_id),
            "provider": account.provider,
            "import_run_id": str(run.id),
            "entity_count": total_entities,
            "entities_upserted": created + updated,
            "entities_failed": failed,
            "status": run.status,
            "is_mock": bool(account.is_mock),
        },
        actor_id=requested_by,
        resource_type="advertising_import_run",
        resource_id=str(run.id),
        title="Advertising entities imported",
    )
    return run


# Backwards-compatible alias used by some callers.
import_account_entities = import_account


__all__ = ["import_account", "import_account_entities"]
