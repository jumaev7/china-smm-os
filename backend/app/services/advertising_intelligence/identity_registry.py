"""Identity registry: maintain current mirrors + immutable change history.

Upserts provider campaigns/ad groups/ads/creatives into their per-type mirror
tables and appends an immutable ``TenantAdEntityHistory`` row whenever content
changes (detected via a stable content fingerprint). Mirrors are the "current"
view; history is append-only and never mutated.

Parent references are resolved by the caller (``import_service``) into internal
UUIDs and passed in, so this module performs no cross-entity lookups.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    TenantAd,
    TenantAdCampaign,
    TenantAdCreative,
    TenantAdEntityHistory,
    TenantAdGroup,
)
from app.services.advertising_intelligence.schemas import (
    Money,
    ProviderAd,
    ProviderAdGroup,
    ProviderCampaign,
    ProviderCreative,
)


def _fingerprint(fields: dict[str, Any]) -> str:
    payload = json.dumps(fields, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _money_parts(money: Money | None) -> tuple[int | None, str | None]:
    if money is None:
        return None, None
    return money.minor_units, money.currency


def _diff(previous: dict[str, Any] | None, current: dict[str, Any]) -> dict[str, Any]:
    if not previous:
        return {}
    changes: dict[str, Any] = {}
    for key, new_value in current.items():
        old_value = previous.get(key)
        if old_value != new_value:
            changes[key] = {"from": old_value, "to": new_value}
    return changes


async def _append_history(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    advertising_account_id: UUID,
    entity_type: str,
    entity_id: UUID,
    provider_entity_id: str,
    change_type: str,
    field_changes: dict[str, Any],
    previous_fingerprint: str | None,
    fingerprint: str,
    observed_at: datetime,
    import_run_id: UUID | None,
    source: str,
) -> None:
    db.add(
        TenantAdEntityHistory(
            tenant_id=tenant_id,
            advertising_account_id=advertising_account_id,
            entity_type=entity_type,
            entity_id=entity_id,
            provider_entity_id=provider_entity_id,
            change_type=change_type,
            field_changes=field_changes or None,
            previous_fingerprint=previous_fingerprint,
            fingerprint=fingerprint,
            observed_at=observed_at,
            import_run_id=import_run_id,
            source=source,
        )
    )


async def upsert_campaign(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    provider: str,
    campaign: ProviderCampaign,
    observed_at: datetime,
    import_run_id: UUID | None = None,
    source: str = "provider",
) -> tuple[TenantAdCampaign, str]:
    daily_minor, daily_cur = _money_parts(campaign.daily_budget)
    lifetime_minor, lifetime_cur = _money_parts(campaign.lifetime_budget)
    spend_cap_minor, _ = _money_parts(campaign.spend_cap)
    budget_currency = daily_cur or lifetime_cur
    content = {
        "name": campaign.name,
        "objective": campaign.objective,
        "buying_type": campaign.buying_type,
        "config_status": campaign.config_status,
        "effective_status": campaign.effective_status,
        "bid_strategy": campaign.bid_strategy,
        "daily_budget_minor": daily_minor,
        "lifetime_budget_minor": lifetime_minor,
        "budget_currency": budget_currency,
        "spend_cap_minor": spend_cap_minor,
    }
    fingerprint = _fingerprint(content)

    row = (
        await db.execute(
            select(TenantAdCampaign).where(
                TenantAdCampaign.tenant_id == tenant_id,
                TenantAdCampaign.advertising_account_id == account_id,
                TenantAdCampaign.provider_campaign_id == campaign.provider_campaign_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = TenantAdCampaign(
            tenant_id=tenant_id,
            advertising_account_id=account_id,
            provider=provider,
            provider_campaign_id=campaign.provider_campaign_id,
            special_ad_categories=campaign.special_ad_categories or None,
            attribution_spec=campaign.attribution_spec or None,
            provider_start_time=campaign.start_time,
            provider_stop_time=campaign.stop_time,
            provider_created_time=campaign.created_time,
            provider_updated_time=campaign.updated_time,
            source_fingerprint=fingerprint,
            is_mock=(provider == "mock"),
            **content,
        )
        db.add(row)
        await db.flush()
        await _append_history(
            db, tenant_id=tenant_id, advertising_account_id=account_id,
            entity_type="campaign", entity_id=row.id,
            provider_entity_id=campaign.provider_campaign_id,
            change_type="created", field_changes={}, previous_fingerprint=None,
            fingerprint=fingerprint, observed_at=observed_at,
            import_run_id=import_run_id, source=source,
        )
        return row, "created"

    if row.source_fingerprint == fingerprint:
        return row, "unchanged"

    previous = {k: getattr(row, k) for k in content}
    for key, value in content.items():
        setattr(row, key, value)
    row.provider_start_time = campaign.start_time or row.provider_start_time
    row.provider_stop_time = campaign.stop_time or row.provider_stop_time
    row.source_fingerprint = fingerprint
    await db.flush()
    await _append_history(
        db, tenant_id=tenant_id, advertising_account_id=account_id,
        entity_type="campaign", entity_id=row.id,
        provider_entity_id=campaign.provider_campaign_id,
        change_type="updated", field_changes=_diff(previous, content),
        previous_fingerprint=None, fingerprint=fingerprint,
        observed_at=observed_at, import_run_id=import_run_id, source=source,
    )
    return row, "updated"


async def upsert_ad_group(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    provider: str,
    ad_group: ProviderAdGroup,
    campaign_id: UUID | None,
    observed_at: datetime,
    import_run_id: UUID | None = None,
    source: str = "provider",
) -> tuple[TenantAdGroup, str]:
    bid_minor, bid_cur = _money_parts(ad_group.bid_amount)
    daily_minor, daily_cur = _money_parts(ad_group.daily_budget)
    lifetime_minor, lifetime_cur = _money_parts(ad_group.lifetime_budget)
    content = {
        "campaign_id": campaign_id,
        "name": ad_group.name,
        "config_status": ad_group.config_status,
        "effective_status": ad_group.effective_status,
        "optimization_goal": ad_group.optimization_goal,
        "billing_event": ad_group.billing_event,
        "bid_amount_minor": bid_minor,
        "bid_currency": bid_cur,
        "daily_budget_minor": daily_minor,
        "lifetime_budget_minor": lifetime_minor,
        "budget_currency": daily_cur or lifetime_cur,
    }
    fingerprint = _fingerprint({k: v for k, v in content.items() if k != "campaign_id"} | {"campaign_id": str(campaign_id)})

    row = (
        await db.execute(
            select(TenantAdGroup).where(
                TenantAdGroup.tenant_id == tenant_id,
                TenantAdGroup.advertising_account_id == account_id,
                TenantAdGroup.provider_ad_group_id == ad_group.provider_ad_group_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = TenantAdGroup(
            tenant_id=tenant_id,
            advertising_account_id=account_id,
            provider=provider,
            provider_ad_group_id=ad_group.provider_ad_group_id,
            provider_campaign_id=ad_group.provider_campaign_id,
            targeting_summary=ad_group.targeting_summary or None,
            source_fingerprint=fingerprint,
            is_mock=(provider == "mock"),
            **content,
        )
        db.add(row)
        await db.flush()
        await _append_history(
            db, tenant_id=tenant_id, advertising_account_id=account_id,
            entity_type="ad_group", entity_id=row.id,
            provider_entity_id=ad_group.provider_ad_group_id,
            change_type="created", field_changes={}, previous_fingerprint=None,
            fingerprint=fingerprint, observed_at=observed_at,
            import_run_id=import_run_id, source=source,
        )
        return row, "created"

    if row.source_fingerprint == fingerprint:
        return row, "unchanged"

    previous = {k: getattr(row, k) for k in content}
    for key, value in content.items():
        setattr(row, key, value)
    row.source_fingerprint = fingerprint
    await db.flush()
    await _append_history(
        db, tenant_id=tenant_id, advertising_account_id=account_id,
        entity_type="ad_group", entity_id=row.id,
        provider_entity_id=ad_group.provider_ad_group_id,
        change_type="updated", field_changes=_diff(previous, content),
        previous_fingerprint=None, fingerprint=fingerprint,
        observed_at=observed_at, import_run_id=import_run_id, source=source,
    )
    return row, "updated"


async def upsert_creative(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    provider: str,
    creative: ProviderCreative,
    observed_at: datetime,
    import_run_id: UUID | None = None,
    source: str = "provider",
) -> tuple[TenantAdCreative, str]:
    content = {
        "name": creative.name,
        "title": creative.title,
        "body": creative.body,
        "call_to_action_type": creative.call_to_action_type,
        "object_type": creative.object_type,
        "thumbnail_url": creative.thumbnail_url,
        "permalink_url": creative.permalink_url,
        "object_story_id": creative.object_story_id,
    }
    fingerprint = _fingerprint(content)

    row = (
        await db.execute(
            select(TenantAdCreative).where(
                TenantAdCreative.tenant_id == tenant_id,
                TenantAdCreative.advertising_account_id == account_id,
                TenantAdCreative.provider_creative_id == creative.provider_creative_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = TenantAdCreative(
            tenant_id=tenant_id,
            advertising_account_id=account_id,
            provider=provider,
            provider_creative_id=creative.provider_creative_id,
            asset_summary=creative.asset_summary or None,
            source_fingerprint=fingerprint,
            is_mock=(provider == "mock"),
            **content,
        )
        db.add(row)
        await db.flush()
        await _append_history(
            db, tenant_id=tenant_id, advertising_account_id=account_id,
            entity_type="creative", entity_id=row.id,
            provider_entity_id=creative.provider_creative_id,
            change_type="created", field_changes={}, previous_fingerprint=None,
            fingerprint=fingerprint, observed_at=observed_at,
            import_run_id=import_run_id, source=source,
        )
        return row, "created"

    if row.source_fingerprint == fingerprint:
        return row, "unchanged"

    previous = {k: getattr(row, k) for k in content}
    for key, value in content.items():
        setattr(row, key, value)
    row.source_fingerprint = fingerprint
    await db.flush()
    await _append_history(
        db, tenant_id=tenant_id, advertising_account_id=account_id,
        entity_type="creative", entity_id=row.id,
        provider_entity_id=creative.provider_creative_id,
        change_type="updated", field_changes=_diff(previous, content),
        previous_fingerprint=None, fingerprint=fingerprint,
        observed_at=observed_at, import_run_id=import_run_id, source=source,
    )
    return row, "updated"


async def upsert_ad(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    account_id: UUID,
    provider: str,
    ad: ProviderAd,
    campaign_id: UUID | None,
    ad_group_id: UUID | None,
    creative_id: UUID | None,
    observed_at: datetime,
    import_run_id: UUID | None = None,
    source: str = "provider",
) -> tuple[TenantAd, str]:
    content = {
        "campaign_id": campaign_id,
        "ad_group_id": ad_group_id,
        "creative_id": creative_id,
        "name": ad.name,
        "config_status": ad.config_status,
        "effective_status": ad.effective_status,
    }
    fingerprint = _fingerprint({
        "name": ad.name,
        "config_status": ad.config_status,
        "effective_status": ad.effective_status,
        "ad_group_id": str(ad_group_id),
        "creative_id": str(creative_id),
    })

    row = (
        await db.execute(
            select(TenantAd).where(
                TenantAd.tenant_id == tenant_id,
                TenantAd.advertising_account_id == account_id,
                TenantAd.provider_ad_id == ad.provider_ad_id,
            )
        )
    ).scalar_one_or_none()

    if row is None:
        row = TenantAd(
            tenant_id=tenant_id,
            advertising_account_id=account_id,
            provider=provider,
            provider_ad_id=ad.provider_ad_id,
            provider_ad_group_id=ad.provider_ad_group_id,
            provider_creative_id=ad.provider_creative_id,
            tracking_specs=ad.tracking_specs or None,
            source_fingerprint=fingerprint,
            is_mock=(provider == "mock"),
            **content,
        )
        db.add(row)
        await db.flush()
        await _append_history(
            db, tenant_id=tenant_id, advertising_account_id=account_id,
            entity_type="ad", entity_id=row.id,
            provider_entity_id=ad.provider_ad_id,
            change_type="created", field_changes={}, previous_fingerprint=None,
            fingerprint=fingerprint, observed_at=observed_at,
            import_run_id=import_run_id, source=source,
        )
        return row, "created"

    if row.source_fingerprint == fingerprint:
        return row, "unchanged"

    previous = {k: getattr(row, k) for k in content}
    for key, value in content.items():
        setattr(row, key, value)
    row.source_fingerprint = fingerprint
    await db.flush()
    await _append_history(
        db, tenant_id=tenant_id, advertising_account_id=account_id,
        entity_type="ad", entity_id=row.id,
        provider_entity_id=ad.provider_ad_id,
        change_type="updated", field_changes=_diff(previous, content),
        previous_fingerprint=None, fingerprint=fingerprint,
        observed_at=observed_at, import_run_id=import_run_id, source=source,
    )
    return row, "updated"


__all__ = [
    "upsert_campaign",
    "upsert_ad_group",
    "upsert_creative",
    "upsert_ad",
]
