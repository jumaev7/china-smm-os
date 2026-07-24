"""Read + light-serialization layer for the Advertising Intelligence HTTP APIs.

Owns structural list/get serialization plus tenant overview, freshness,
anomalies, attribution coverage, provider capabilities, static configuration,
and the internal linkage writes (link/unlink a provider campaign to an internal
marketing campaign, or a creative to internal content).

READ-ONLY toward providers: nothing here ever mutates provider state. The only
writes are to OUR linkage tables (``tenant_ad_campaign_links`` /
``tenant_ad_creative_links``).

Design:
- Structural fields come from the canonical ORM mirror tables.
- Metric values (spend/impressions/clicks/conversions and derived ratios) are
  composed from ``tenant_ad_metric_aggregates`` (best available window), never
  fabricated. Missing data stays ``None``.
- Money is always minor units + an explicit currency and is NEVER summed across
  currencies.
- Provider-reported conversions are kept separate from CRM-confirmed
  conversions (the latter requires the reconciliation service and is otherwise
  reported as ``None``).

Only the stable ORM models and ``errors`` are imported eagerly; every other
sibling service module is optional and imported defensively so the app boots
even while the services layer is still being authored.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.advertising import (
    AD_CALCULATION_VERSION,
    AD_METRIC_SEMANTICS_VERSION,
    ADVERTISING_PROVIDERS,
    ADVERTISING_VERSION,
    BUDGET_TYPES,
    CONNECTION_STATUSES,
    FRESHNESS_STATUSES,
    PACING_STATUSES,
    TenantAd,
    TenantAdBudgetSnapshot,
    TenantAdCampaign,
    TenantAdCampaignLink,
    TenantAdCreative,
    TenantAdCreativeLink,
    TenantAdDeliveryAnomaly,
    TenantAdGroup,
    TenantAdMetricAggregate,
    TenantAdvertisingAccount,
)
from app.services.advertising_intelligence.errors import (
    AdAccountNotFoundError,
    AdCrossTenantReferenceError,
    AdProviderUnsupportedError,
    AdvertisingError,
)

# ---------------------------------------------------------------------------
# Optional (in-flux) sibling modules — imported defensively.
# ---------------------------------------------------------------------------

try:  # metric catalog can be temporarily un-importable during parallel authoring
    from app.services.advertising_intelligence.metric_catalog import (  # type: ignore
        ALL_METRIC_KEYS as _CATALOG_METRIC_KEYS,
        CATALOG_VERSION as _CATALOG_VERSION,
        METRIC_SEMANTICS_VERSION as _METRIC_SEMANTICS_VERSION,
    )
    _ALL_METRIC_KEYS = sorted(_CATALOG_METRIC_KEYS)
except Exception:  # noqa: BLE001
    _CATALOG_VERSION = "1.0.0"
    _METRIC_SEMANTICS_VERSION = AD_METRIC_SEMANTICS_VERSION
    _ALL_METRIC_KEYS = [
        "spend_minor", "impressions", "reach", "clicks", "link_clicks",
        "video_views", "conversions", "conversion_value_minor",
        "ctr", "link_ctr", "frequency", "cpc_minor", "cpm_minor", "cpa_minor", "roas",
    ]

try:
    from app.services.advertising_intelligence.limits import (  # type: ignore
        AGING_MAX_AGE_SECONDS as _AGING_MAX_AGE_SECONDS,
        FRESH_MAX_AGE_SECONDS as _FRESH_MAX_AGE_SECONDS,
        MAX_ACCOUNTS_PER_TENANT as _MAX_ACCOUNTS_PER_TENANT,
        MAX_ANALYTICS_DATE_RANGE_DAYS as _MAX_ANALYTICS_DATE_RANGE_DAYS,
        MAX_REFRESH_REQUESTS_PER_TENANT_PER_HOUR as _MAX_REFRESH_PER_HOUR,
    )
except Exception:  # noqa: BLE001
    _FRESH_MAX_AGE_SECONDS = 6 * 3600
    _AGING_MAX_AGE_SECONDS = 24 * 3600
    _MAX_ACCOUNTS_PER_TENANT = 25
    _MAX_ANALYTICS_DATE_RANGE_DAYS = 366
    _MAX_REFRESH_PER_HOUR = 20


# ---------------------------------------------------------------------------
# Versions / vocab surfaced by the configuration endpoint
# ---------------------------------------------------------------------------

ADVERTISING_CATALOG_VERSION = _CATALOG_VERSION
ADVERTISING_SERVICE_VERSION = ADVERTISING_VERSION

# Metric keys decorated onto structural entities (subset of the catalog).
ENTITY_METRIC_KEYS = (
    "spend_minor",
    "impressions",
    "reach",
    "clicks",
    "link_clicks",
    "conversions",
    "conversion_value_minor",
    "ctr",
    "cpc_minor",
    "cpm_minor",
    "frequency",
)

# Window preference when picking the "current" value of a metric.
_WINDOW_PRIORITY = ("lifetime", "30d", "14d", "7d", "72h", "24h")
_WINDOW_RANK = {w: i for i, w in enumerate(_WINDOW_PRIORITY)}

FATIGUE_STATUSES = ("healthy", "watch", "fatigued", "insufficient_data")
DELIVERY_STATUSES = ("delivering", "limited", "not_delivering", "unknown")


# Provider capability catalog (read-only declaration; static, not a live check).
PROVIDER_CATALOG: dict[str, dict[str, Any]] = {
    "meta": {
        "display_name": "Meta Ads",
        "supports_campaign_metrics": True,
        "supports_ad_level_metrics": True,
        "supports_creative_metrics": True,
        "supports_conversions": True,
        "supported_metric_keys": [
            "spend_minor", "impressions", "reach", "clicks", "link_clicks",
            "video_views", "conversions", "conversion_value_minor",
            "ctr", "cpc_minor", "cpm_minor", "frequency",
        ],
        "notes": "Read-only Insights reporting for Facebook/Instagram. No ad edits.",
    },
    "mock": {
        "display_name": "Mock provider",
        "supports_campaign_metrics": True,
        "supports_ad_level_metrics": True,
        "supports_creative_metrics": True,
        "supports_conversions": True,
        "supported_metric_keys": list(ENTITY_METRIC_KEYS),
        "notes": "Local/dev deterministic mock account. Not a live provider.",
    },
}

SUPPORTED_PROVIDERS = tuple(sorted(ADVERTISING_PROVIDERS))

LIMITS = {
    "max_accounts_per_tenant": _MAX_ACCOUNTS_PER_TENANT,
    "max_analytics_date_range_days": _MAX_ANALYTICS_DATE_RANGE_DAYS,
    "max_refresh_requests_per_tenant_per_hour": _MAX_REFRESH_PER_HOUR,
    "max_page_size": 200,
}


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError, InvalidOperation):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError, InvalidOperation):
        return None


def _upper_currency(value: Any) -> str | None:
    if not value:
        return None
    return str(value).upper()


def _account_freshness(account: TenantAdvertisingAccount) -> str:
    last = account.last_metrics_sync_at or account.last_successful_sync_at
    if last is None:
        return "unavailable"
    now = datetime.now(timezone.utc)
    ref = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
    age = (now - ref).total_seconds()
    if age <= _FRESH_MAX_AGE_SECONDS:
        return "fresh"
    if age <= _AGING_MAX_AGE_SECONDS:
        return "aging"
    return "stale"


async def _lifetime_metrics(
    db: AsyncSession,
    tenant_id: UUID,
    entity_type: str,
    entity_ids: Iterable[UUID],
) -> dict[UUID, dict[str, Any]]:
    """Return {entity_id: {metric_key: {"value", "currency"}}} using the best
    available window per (entity, metric). Never fabricates values."""
    ids = [e for e in entity_ids if e is not None]
    if not ids:
        return {}
    rows = list(
        (
            await db.execute(
                select(TenantAdMetricAggregate).where(
                    TenantAdMetricAggregate.tenant_id == tenant_id,
                    TenantAdMetricAggregate.entity_type == entity_type,
                    TenantAdMetricAggregate.entity_id.in_(ids),
                    TenantAdMetricAggregate.metric_key.in_(ENTITY_METRIC_KEYS),
                    TenantAdMetricAggregate.calculation_version == AD_CALCULATION_VERSION,
                )
            )
        ).scalars().all()
    )
    best: dict[UUID, dict[str, tuple[int, TenantAdMetricAggregate]]] = defaultdict(dict)
    for row in rows:
        rank = _WINDOW_RANK.get(row.window_key, len(_WINDOW_PRIORITY))
        current = best[row.entity_id].get(row.metric_key)
        if current is None or rank < current[0]:
            best[row.entity_id][row.metric_key] = (rank, row)
    out: dict[UUID, dict[str, Any]] = {}
    for entity_id, metric_map in best.items():
        decorated: dict[str, Any] = {}
        for metric_key, (_rank, row) in metric_map.items():
            decorated[metric_key] = {
                "value": row.metric_value,
                "currency": _upper_currency(row.currency),
                "value_type": row.value_type,
                "window_key": row.window_key,
                "freshness_status": row.freshness_status,
            }
        out[entity_id] = decorated
    return out


def _metric_int(metrics: dict[str, Any], key: str) -> int | None:
    entry = metrics.get(key)
    return _to_int(entry["value"]) if entry else None


def _metric_currency(metrics: dict[str, Any], key: str) -> str | None:
    entry = metrics.get(key)
    return entry.get("currency") if entry else None


def _derive_ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _entity_metric_freshness(metrics: dict[str, Any]) -> str | None:
    statuses = {m.get("freshness_status") for m in metrics.values() if m.get("freshness_status")}
    if not statuses:
        return None
    for status in ("stale", "aging", "unavailable", "unsupported", "fresh"):
        if status in statuses:
            return status
    return next(iter(statuses))


# ---------------------------------------------------------------------------
# Linkage lookups
# ---------------------------------------------------------------------------


async def _campaign_links(db: AsyncSession, tenant_id: UUID, campaign_ids: Iterable[UUID]) -> dict[UUID, UUID]:
    ids = [c for c in campaign_ids if c is not None]
    if not ids:
        return {}
    rows = list(
        (
            await db.execute(
                select(TenantAdCampaignLink).where(
                    TenantAdCampaignLink.tenant_id == tenant_id,
                    TenantAdCampaignLink.ad_campaign_id.in_(ids),
                    TenantAdCampaignLink.status == "active",
                )
            )
        ).scalars().all()
    )
    return {r.ad_campaign_id: r.marketing_campaign_id for r in rows}


async def _creative_links(db: AsyncSession, tenant_id: UUID, creative_ids: Iterable[UUID]) -> dict[UUID, UUID | str]:
    ids = [c for c in creative_ids if c is not None]
    if not ids:
        return {}
    rows = list(
        (
            await db.execute(
                select(TenantAdCreativeLink).where(
                    TenantAdCreativeLink.tenant_id == tenant_id,
                    TenantAdCreativeLink.creative_id.in_(ids),
                    TenantAdCreativeLink.status == "active",
                )
            )
        ).scalars().all()
    )
    out: dict[UUID, UUID | str] = {}
    for r in rows:
        out[r.creative_id] = r.content_id or r.target_id
    return out


async def _latest_budget_snapshot(db: AsyncSession, tenant_id: UUID, entity_type: str, entity_id: UUID):
    return (
        await db.execute(
            select(TenantAdBudgetSnapshot)
            .where(
                TenantAdBudgetSnapshot.tenant_id == tenant_id,
                TenantAdBudgetSnapshot.entity_type == entity_type,
                TenantAdBudgetSnapshot.entity_id == entity_id,
            )
            .order_by(TenantAdBudgetSnapshot.observed_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Serializers (ORM -> HTTP-ready dict)
# ---------------------------------------------------------------------------


def _serialize_account(a: TenantAdvertisingAccount) -> dict[str, Any]:
    return {
        "id": a.id,
        "provider": a.provider,
        "platform": a.platform,
        "external_account_id": a.provider_account_id,
        "name": a.name or a.provider_account_id,
        "currency": _upper_currency(a.currency),
        "timezone": a.timezone,
        "status": a.connection_status,
        "account_status": a.account_status,
        "is_mock": bool(a.is_mock),
        "read_only": True,
        "last_import_at": a.last_import_at,
        "last_metric_refresh_at": a.last_metrics_sync_at,
        "freshness_status": _account_freshness(a),
        "created_at": a.created_at,
        "updated_at": a.updated_at,
    }


def _budget(campaign: TenantAdCampaign) -> tuple[int | None, str | None, str | None]:
    """Return (budget_amount_minor, budget_type, budget_currency)."""
    if campaign.daily_budget_minor is not None:
        return campaign.daily_budget_minor, "daily", _upper_currency(campaign.budget_currency)
    if campaign.lifetime_budget_minor is not None:
        return campaign.lifetime_budget_minor, "lifetime", _upper_currency(campaign.budget_currency)
    return None, None, _upper_currency(campaign.budget_currency)


def _serialize_campaign(
    c: TenantAdCampaign,
    metrics: dict[str, Any],
    linked_internal: UUID | None,
    pacing_status: str | None,
) -> dict[str, Any]:
    budget_minor, budget_type, budget_currency = _budget(c)
    spend = _metric_int(metrics, "spend_minor")
    impressions = _metric_int(metrics, "impressions")
    clicks = _metric_int(metrics, "clicks")
    currency = _metric_currency(metrics, "spend_minor") or budget_currency
    return {
        "id": c.id,
        "account_id": c.advertising_account_id,
        "provider": c.provider,
        "external_campaign_id": c.provider_campaign_id,
        "name": c.name or c.provider_campaign_id,
        "status": c.effective_status,
        "config_status": c.config_status,
        "objective": c.objective,
        "currency": currency,
        "budget_amount_minor": budget_minor,
        "budget_type": budget_type,
        "start_date": c.provider_start_time,
        "end_date": c.provider_stop_time,
        "spend_minor": spend,
        "impressions": impressions,
        "clicks": clicks,
        "conversions_reported": _metric_int(metrics, "conversions"),
        "conversions_crm_confirmed": None,
        "pacing_status": pacing_status,
        "freshness_status": _entity_metric_freshness(metrics),
        "last_metric_at": None,
        "linked_internal_campaign_id": linked_internal,
        "read_only": True,
    }


def _serialize_ad_group(g: TenantAdGroup, metrics: dict[str, Any], pacing_status: str | None) -> dict[str, Any]:
    return {
        "id": g.id,
        "account_id": g.advertising_account_id,
        "campaign_id": g.campaign_id,
        "external_ad_group_id": g.provider_ad_group_id,
        "name": g.name or g.provider_ad_group_id,
        "status": g.effective_status,
        "currency": _metric_currency(metrics, "spend_minor") or _upper_currency(g.budget_currency),
        "spend_minor": _metric_int(metrics, "spend_minor"),
        "impressions": _metric_int(metrics, "impressions"),
        "clicks": _metric_int(metrics, "clicks"),
        "conversions_reported": _metric_int(metrics, "conversions"),
        "delivery_status": _delivery_from_status(g.effective_status),
        "freshness_status": _entity_metric_freshness(metrics),
        "read_only": True,
    }


def _serialize_ad(ad: TenantAd, metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": ad.id,
        "account_id": ad.advertising_account_id,
        "campaign_id": ad.campaign_id,
        "ad_group_id": ad.ad_group_id,
        "external_ad_id": ad.provider_ad_id,
        "name": ad.name or ad.provider_ad_id,
        "status": ad.effective_status,
        "creative_id": ad.creative_id,
        "currency": _metric_currency(metrics, "spend_minor"),
        "spend_minor": _metric_int(metrics, "spend_minor"),
        "impressions": _metric_int(metrics, "impressions"),
        "clicks": _metric_int(metrics, "clicks"),
        "conversions_reported": _metric_int(metrics, "conversions"),
        "freshness_status": _entity_metric_freshness(metrics),
        "read_only": True,
    }


def _fatigue_from_frequency(frequency: float | None) -> str:
    if frequency is None:
        return "insufficient_data"
    if frequency < 2.0:
        return "healthy"
    if frequency < 3.5:
        return "watch"
    return "fatigued"


def _serialize_creative(cr: TenantAdCreative, metrics: dict[str, Any], linked_content: Any) -> dict[str, Any]:
    frequency_entry = metrics.get("frequency")
    frequency = _to_float(frequency_entry["value"]) if frequency_entry else None
    impressions = _metric_int(metrics, "impressions")
    clicks = _metric_int(metrics, "clicks")
    return {
        "id": cr.id,
        "account_id": cr.advertising_account_id,
        "external_creative_id": cr.provider_creative_id,
        "name": cr.name or cr.title or cr.provider_creative_id,
        "format": cr.object_type,
        "preview_url": cr.permalink_url,
        "thumbnail_url": cr.thumbnail_url,
        "status": None,
        "fatigue_status": _fatigue_from_frequency(frequency),
        "currency": _metric_currency(metrics, "spend_minor"),
        "spend_minor": _metric_int(metrics, "spend_minor"),
        "impressions": impressions,
        "clicks": clicks,
        "frequency": frequency,
        "first_seen_at": cr.created_at,
        "last_seen_at": cr.updated_at,
        "linked_content_id": linked_content,
        "read_only": True,
    }


def _delivery_from_status(effective_status: str | None) -> str:
    if effective_status == "active":
        return "delivering"
    if effective_status in {"paused", "campaign_paused", "adset_paused"}:
        return "not_delivering"
    if effective_status in {"with_issues", "pending_review", "in_process", "pending_billing_info"}:
        return "limited"
    if effective_status in {"disapproved", "deleted", "archived", "completed"}:
        return "not_delivering"
    return "unknown"


def _serialize_anomaly(a: TenantAdDeliveryAnomaly) -> dict[str, Any]:
    return {
        "id": a.id,
        "account_id": a.advertising_account_id,
        "campaign_id": None,
        "entity_type": a.entity_type,
        "entity_id": a.entity_id,
        "anomaly_key": a.anomaly_key,
        "severity": a.severity,
        "metric_key": a.metric_key,
        "currency": None,
        "evidence": a.evidence or {},
        "status": a.status,
        "created_at": a.created_at,
        "resolved_at": a.resolved_at,
    }


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------


async def list_accounts(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    provider: str | None = None,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [TenantAdvertisingAccount.tenant_id == tenant_id]
    if provider:
        filters.append(TenantAdvertisingAccount.provider == provider)
    if status:
        filters.append(TenantAdvertisingAccount.connection_status == status)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(TenantAdvertisingAccount).where(*filters)
            )
        ).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantAdvertisingAccount)
                .where(*filters)
                .order_by(TenantAdvertisingAccount.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return [_serialize_account(a) for a in rows], total


async def _get_account_row(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> TenantAdvertisingAccount:
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


async def get_account(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
    return _serialize_account(await _get_account_row(db, tenant_id, account_id))


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


async def list_campaigns(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
    status: str | None = None,
    linked: bool | None = None,
    marketing_campaign_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [TenantAdCampaign.tenant_id == tenant_id]
    if account_id:
        filters.append(TenantAdCampaign.advertising_account_id == account_id)
    if status:
        filters.append(TenantAdCampaign.effective_status == status)
    if marketing_campaign_id is not None:
        linked_ids = list(
            (
                await db.execute(
                    select(TenantAdCampaignLink.ad_campaign_id).where(
                        TenantAdCampaignLink.tenant_id == tenant_id,
                        TenantAdCampaignLink.marketing_campaign_id == marketing_campaign_id,
                        TenantAdCampaignLink.status == "active",
                    )
                )
            ).scalars().all()
        )
        if not linked_ids:
            return [], 0
        filters.append(TenantAdCampaign.id.in_(linked_ids))
    total = int(
        (
            await db.execute(select(func.count()).select_from(TenantAdCampaign).where(*filters))
        ).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantAdCampaign)
                .where(*filters)
                .order_by(TenantAdCampaign.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    metrics = await _lifetime_metrics(db, tenant_id, "campaign", [c.id for c in rows])
    links = await _campaign_links(db, tenant_id, [c.id for c in rows])
    items: list[dict[str, Any]] = []
    for c in rows:
        if linked is True and c.id not in links:
            continue
        if linked is False and c.id in links:
            continue
        items.append(
            _serialize_campaign(c, metrics.get(c.id, {}), links.get(c.id), None)
        )
    if linked is not None:
        total = len(items)
    return items, total


async def _get_campaign_row(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> TenantAdCampaign:
    campaign = (
        await db.execute(
            select(TenantAdCampaign).where(
                TenantAdCampaign.id == campaign_id,
                TenantAdCampaign.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if campaign is None:
        raise AdCrossTenantReferenceError("advertising campaign not found")
    return campaign


async def get_campaign(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> dict[str, Any]:
    campaign = await _get_campaign_row(db, tenant_id, campaign_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "campaign", [campaign.id])).get(campaign.id, {})
    links = await _campaign_links(db, tenant_id, [campaign.id])
    budget = await _latest_budget_snapshot(db, tenant_id, "campaign", campaign.id)
    pacing = budget.pacing_status if budget else None
    return _serialize_campaign(campaign, metrics, links.get(campaign.id), pacing)


async def campaign_performance(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> dict[str, Any]:
    campaign = await _get_campaign_row(db, tenant_id, campaign_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "campaign", [campaign.id])).get(campaign.id, {})
    spend = _metric_int(metrics, "spend_minor")
    impressions = _metric_int(metrics, "impressions")
    clicks = _metric_int(metrics, "clicks")
    conversions = _metric_int(metrics, "conversions")
    currency = _metric_currency(metrics, "spend_minor") or _upper_currency(campaign.budget_currency)
    ctr = _to_float((metrics.get("ctr") or {}).get("value")) or _derive_ratio(clicks, impressions)
    cpc = _metric_int(metrics, "cpc_minor")
    if cpc is None:
        cpc = _to_int(_derive_ratio(spend, clicks)) if (spend is not None and clicks) else None
    cpm = _metric_int(metrics, "cpm_minor")
    if cpm is None and spend is not None and impressions:
        cpm = _to_int(spend / impressions * 1000)
    cost_per_conv = _to_int(spend / conversions) if (spend is not None and conversions) else None
    pacing = await campaign_pacing(db, tenant_id, campaign_id)
    return {
        "campaign_id": campaign.id,
        "currency": currency,
        "spend_minor": spend,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "cpc_minor": cpc,
        "cpm_minor": cpm,
        "conversions_reported": conversions,
        "conversions_crm_confirmed": None,
        "cost_per_conversion_minor": cost_per_conv,
        "pacing": pacing,
        "time_series": [],
        "freshness_status": _entity_metric_freshness(metrics),
        "read_only": True,
    }


async def campaign_pacing(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> dict[str, Any]:
    campaign = await _get_campaign_row(db, tenant_id, campaign_id)
    budget = await _latest_budget_snapshot(db, tenant_id, "campaign", campaign.id)
    budget_minor, budget_type, budget_currency = _budget(campaign)
    if budget is None:
        return {
            "campaign_id": campaign.id,
            "status": "unknown",
            "currency": budget_currency,
            "budget_amount_minor": budget_minor,
            "budget_type": budget_type,
            "spend_minor": None,
            "expected_spend_minor": None,
            "pace_ratio": None,
            "days_elapsed": None,
            "days_total": None,
            "read_only": True,
        }
    return {
        "campaign_id": campaign.id,
        "status": budget.pacing_status,
        "currency": _upper_currency(budget.currency) or budget_currency,
        "budget_amount_minor": budget.budget_minor if budget.budget_minor is not None else budget_minor,
        "budget_type": budget.budget_type or budget_type,
        "spend_minor": budget.spend_minor,
        "expected_spend_minor": None,
        "pace_ratio": _to_float(budget.utilization_ratio),
        "days_elapsed": None,
        "days_total": None,
        "read_only": True,
    }


# ---------------------------------------------------------------------------
# Ad groups
# ---------------------------------------------------------------------------


async def list_ad_groups(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    campaign_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [
        TenantAdGroup.tenant_id == tenant_id,
        TenantAdGroup.campaign_id == campaign_id,
    ]
    total = int(
        (await db.execute(select(func.count()).select_from(TenantAdGroup).where(*filters))).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantAdGroup)
                .where(*filters)
                .order_by(TenantAdGroup.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    metrics = await _lifetime_metrics(db, tenant_id, "ad_group", [g.id for g in rows])
    return [_serialize_ad_group(g, metrics.get(g.id, {}), None) for g in rows], total


async def _get_ad_group_row(db: AsyncSession, tenant_id: UUID, ad_group_id: UUID) -> TenantAdGroup:
    row = (
        await db.execute(
            select(TenantAdGroup).where(
                TenantAdGroup.id == ad_group_id,
                TenantAdGroup.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AdCrossTenantReferenceError("ad group not found")
    return row


async def get_ad_group(db: AsyncSession, tenant_id: UUID, ad_group_id: UUID) -> dict[str, Any]:
    g = await _get_ad_group_row(db, tenant_id, ad_group_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "ad_group", [g.id])).get(g.id, {})
    budget = await _latest_budget_snapshot(db, tenant_id, "ad_group", g.id)
    return _serialize_ad_group(g, metrics, budget.pacing_status if budget else None)


async def ad_group_delivery(db: AsyncSession, tenant_id: UUID, ad_group_id: UUID) -> dict[str, Any]:
    g = await _get_ad_group_row(db, tenant_id, ad_group_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "ad_group", [g.id])).get(g.id, {})
    anomalies = list(
        (
            await db.execute(
                select(TenantAdDeliveryAnomaly).where(
                    TenantAdDeliveryAnomaly.tenant_id == tenant_id,
                    TenantAdDeliveryAnomaly.entity_type == "ad_group",
                    TenantAdDeliveryAnomaly.entity_id == g.id,
                    TenantAdDeliveryAnomaly.status == "open",
                )
            )
        ).scalars().all()
    )
    return {
        "ad_group_id": g.id,
        "delivery_status": _delivery_from_status(g.effective_status),
        "currency": _metric_currency(metrics, "spend_minor"),
        "spend_minor": _metric_int(metrics, "spend_minor"),
        "impressions": _metric_int(metrics, "impressions"),
        "reasons": [a.anomaly_key for a in anomalies],
        "evidence": {"open_anomalies": len(anomalies), "effective_status": g.effective_status},
        "freshness_status": _entity_metric_freshness(metrics),
        "read_only": True,
    }


# ---------------------------------------------------------------------------
# Ads
# ---------------------------------------------------------------------------


async def list_ads(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    ad_group_id: UUID,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [TenantAd.tenant_id == tenant_id, TenantAd.ad_group_id == ad_group_id]
    total = int(
        (await db.execute(select(func.count()).select_from(TenantAd).where(*filters))).scalar_one() or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantAd)
                .where(*filters)
                .order_by(TenantAd.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    metrics = await _lifetime_metrics(db, tenant_id, "ad", [ad.id for ad in rows])
    return [_serialize_ad(ad, metrics.get(ad.id, {})) for ad in rows], total


async def _get_ad_row(db: AsyncSession, tenant_id: UUID, ad_id: UUID) -> TenantAd:
    row = (
        await db.execute(
            select(TenantAd).where(TenantAd.id == ad_id, TenantAd.tenant_id == tenant_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AdCrossTenantReferenceError("ad not found")
    return row


async def get_ad(db: AsyncSession, tenant_id: UUID, ad_id: UUID) -> dict[str, Any]:
    ad = await _get_ad_row(db, tenant_id, ad_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "ad", [ad.id])).get(ad.id, {})
    return _serialize_ad(ad, metrics)


async def get_creative_for_ad(db: AsyncSession, tenant_id: UUID, ad_id: UUID) -> dict[str, Any]:
    ad = await _get_ad_row(db, tenant_id, ad_id)
    if ad.creative_id is None:
        raise AdCrossTenantReferenceError("ad has no linked creative")
    return await get_creative(db, tenant_id, ad.creative_id)


# ---------------------------------------------------------------------------
# Creatives
# ---------------------------------------------------------------------------


async def list_creatives(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    account_id: UUID | None = None,
    fatigue_status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [TenantAdCreative.tenant_id == tenant_id]
    if account_id:
        filters.append(TenantAdCreative.advertising_account_id == account_id)
    total = int(
        (await db.execute(select(func.count()).select_from(TenantAdCreative).where(*filters))).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantAdCreative)
                .where(*filters)
                .order_by(TenantAdCreative.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    metrics = await _lifetime_metrics(db, tenant_id, "creative", [c.id for c in rows])
    links = await _creative_links(db, tenant_id, [c.id for c in rows])
    items = [_serialize_creative(c, metrics.get(c.id, {}), links.get(c.id)) for c in rows]
    if fatigue_status:
        items = [i for i in items if i["fatigue_status"] == fatigue_status]
        total = len(items)
    return items, total


async def _get_creative_row(db: AsyncSession, tenant_id: UUID, creative_id: UUID) -> TenantAdCreative:
    row = (
        await db.execute(
            select(TenantAdCreative).where(
                TenantAdCreative.id == creative_id,
                TenantAdCreative.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise AdCrossTenantReferenceError("creative not found")
    return row


async def get_creative(db: AsyncSession, tenant_id: UUID, creative_id: UUID) -> dict[str, Any]:
    cr = await _get_creative_row(db, tenant_id, creative_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "creative", [cr.id])).get(cr.id, {})
    links = await _creative_links(db, tenant_id, [cr.id])
    return _serialize_creative(cr, metrics, links.get(cr.id))


async def creative_diagnostics(db: AsyncSession, tenant_id: UUID, creative_id: UUID) -> dict[str, Any]:
    cr = await _get_creative_row(db, tenant_id, creative_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "creative", [cr.id])).get(cr.id, {})
    frequency_entry = metrics.get("frequency")
    frequency = _to_float(frequency_entry["value"]) if frequency_entry else None
    impressions = _metric_int(metrics, "impressions")
    clicks = _metric_int(metrics, "clicks")
    ctr = _to_float((metrics.get("ctr") or {}).get("value")) or _derive_ratio(clicks, impressions)
    return {
        "creative_id": cr.id,
        "fatigue_status": _fatigue_from_frequency(frequency),
        "frequency": frequency,
        "impressions": impressions,
        "clicks": clicks,
        "ctr": ctr,
        "ctr_trend": None,
        "evidence": {"heuristic": "frequency-based advisory; not a provider signal"},
        "freshness_status": _entity_metric_freshness(metrics),
        "read_only": True,
    }


# ---------------------------------------------------------------------------
# Anomalies
# ---------------------------------------------------------------------------


async def list_anomalies(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    status: str | None = "open",
    account_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    filters = [TenantAdDeliveryAnomaly.tenant_id == tenant_id]
    if status:
        filters.append(TenantAdDeliveryAnomaly.status == status)
    if account_id:
        filters.append(TenantAdDeliveryAnomaly.advertising_account_id == account_id)
    total = int(
        (
            await db.execute(select(func.count()).select_from(TenantAdDeliveryAnomaly).where(*filters))
        ).scalar_one()
        or 0
    )
    rows = list(
        (
            await db.execute(
                select(TenantAdDeliveryAnomaly)
                .where(*filters)
                .order_by(TenantAdDeliveryAnomaly.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars().all()
    )
    return [_serialize_anomaly(a) for a in rows], total


# ---------------------------------------------------------------------------
# Overview / freshness / attribution
# ---------------------------------------------------------------------------


async def advertising_overview(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    accounts = list(
        (
            await db.execute(
                select(TenantAdvertisingAccount).where(TenantAdvertisingAccount.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    campaigns = list(
        (
            await db.execute(
                select(TenantAdCampaign).where(TenantAdCampaign.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    campaign_ids = [c.id for c in campaigns]
    metrics = await _lifetime_metrics(db, tenant_id, "campaign", campaign_ids)
    links = await _campaign_links(db, tenant_id, campaign_ids)

    connected = sum(1 for a in accounts if a.connection_status == "connected")
    mock = sum(1 for a in accounts if a.is_mock)
    active_campaigns = [c for c in campaigns if c.effective_status == "active"]

    # Spend grouped strictly by currency — never mixed.
    spend_by_currency: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"currency": None, "spend_minor": 0, "campaign_count": 0}
    )
    reported_conversions = 0
    for c in campaigns:
        m = metrics.get(c.id, {})
        spend = _metric_int(m, "spend_minor")
        currency = _metric_currency(m, "spend_minor") or _upper_currency(c.budget_currency) or "UNKNOWN"
        bucket = spend_by_currency[currency]
        bucket["currency"] = currency
        bucket["spend_minor"] += spend or 0
        bucket["campaign_count"] += 1
        reported_conversions += _metric_int(m, "conversions") or 0

    # Pacing warnings from latest budget snapshots.
    budget_rows = list(
        (
            await db.execute(
                select(TenantAdBudgetSnapshot)
                .where(
                    TenantAdBudgetSnapshot.tenant_id == tenant_id,
                    TenantAdBudgetSnapshot.entity_type == "campaign",
                    TenantAdBudgetSnapshot.pacing_status.in_(
                        ["underspending", "overspending", "budget_exhausted"]
                    ),
                )
                .order_by(TenantAdBudgetSnapshot.observed_at.desc())
            )
        ).scalars().all()
    )
    seen: set[UUID] = set()
    campaign_by_id = {c.id: c for c in campaigns}
    pacing_warnings: list[dict[str, Any]] = []
    for b in budget_rows:
        if b.entity_id in seen or b.entity_id not in campaign_by_id:
            continue
        seen.add(b.entity_id)
        c = campaign_by_id[b.entity_id]
        pacing_warnings.append({
            "campaign_id": str(c.id),
            "campaign_name": c.name or c.provider_campaign_id,
            "pacing_status": b.pacing_status,
            "currency": _upper_currency(b.currency),
            "spend_minor": b.spend_minor,
            "budget_amount_minor": b.budget_minor,
        })

    # Fatigue warnings — creatives with elevated lifetime frequency (advisory).
    creative_ids = list(
        (
            await db.execute(
                select(TenantAdCreative.id).where(TenantAdCreative.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    creative_metrics = await _lifetime_metrics(db, tenant_id, "creative", creative_ids)
    fatigue_warning_count = 0
    for _cid, m in creative_metrics.items():
        entry = m.get("frequency")
        freq = _to_float(entry["value"]) if entry else None
        if _fatigue_from_frequency(freq) in {"watch", "fatigued"}:
            fatigue_warning_count += 1

    open_anomalies = int(
        (
            await db.execute(
                select(func.count())
                .select_from(TenantAdDeliveryAnomaly)
                .where(
                    TenantAdDeliveryAnomaly.tenant_id == tenant_id,
                    TenantAdDeliveryAnomaly.status == "open",
                )
            )
        ).scalar_one()
        or 0
    )

    freshness = Counter(_entity_metric_freshness(metrics.get(c.id, {})) or "unavailable" for c in campaigns)
    linked = sum(1 for c in campaigns if c.id in links)

    return {
        "read_only": True,
        "account_count": len(accounts),
        "connected_account_count": connected,
        "mock_account_count": mock,
        "active_campaign_count": len(active_campaigns),
        "campaign_count": len(campaigns),
        "spend_by_currency": sorted(
            spend_by_currency.values(), key=lambda r: r["spend_minor"], reverse=True
        ),
        "pacing_warnings": pacing_warnings,
        "fatigue_warning_count": fatigue_warning_count,
        "attribution_coverage": {
            "linked_campaign_count": linked,
            "unlinked_campaign_count": len(campaigns) - linked,
            "coverage_ratio": (linked / len(campaigns)) if campaigns else None,
            "reported_conversions": reported_conversions,
            "crm_confirmed_conversions": 0,
        },
        "open_anomaly_count": open_anomalies,
        "freshness": {
            "fresh": freshness.get("fresh", 0),
            "aging": freshness.get("aging", 0),
            "stale": freshness.get("stale", 0),
            "unavailable": freshness.get("unavailable", 0),
            "unsupported": freshness.get("unsupported", 0),
        },
        "providers": sorted({a.provider for a in accounts}),
        "catalog_version": ADVERTISING_CATALOG_VERSION,
        "notes": [
            "Read-only mirror of provider reporting. This platform never edits, "
            "pauses, or deletes provider campaigns, budgets, or creatives.",
            "Spend is reported per currency and never converted or summed across "
            "currencies.",
            "Provider-reported conversions are shown separately from "
            "CRM-confirmed conversions (CRM confirmation requires reconciliation).",
        ],
    }


async def freshness_overview(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    accounts = list(
        (
            await db.execute(
                select(TenantAdvertisingAccount).where(TenantAdvertisingAccount.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    per_account = [(a, _account_freshness(a)) for a in accounts]
    counts = Counter(status for _a, status in per_account)
    dominant = counts.most_common(1)[0][0] if counts else "unavailable"
    last_import = max((a.last_import_at for a in accounts if a.last_import_at), default=None)
    last_refresh = max((a.last_metrics_sync_at for a in accounts if a.last_metrics_sync_at), default=None)
    return {
        "status": dominant,
        "last_import_at": last_import,
        "last_metric_refresh_at": last_refresh,
        "counts_by_status": {k: int(v) for k, v in sorted(counts.items())},
        "accounts": [
            {
                "account_id": str(a.id),
                "name": a.name or a.provider_account_id,
                "provider": a.provider,
                "freshness_status": status,
                "last_import_at": a.last_import_at,
                "last_metric_refresh_at": a.last_metrics_sync_at,
            }
            for a, status in per_account
        ],
        "read_only": True,
    }


async def attribution_coverage(db: AsyncSession, tenant_id: UUID) -> dict[str, Any]:
    campaigns = list(
        (
            await db.execute(
                select(TenantAdCampaign).where(TenantAdCampaign.tenant_id == tenant_id)
            )
        ).scalars().all()
    )
    campaign_ids = [c.id for c in campaigns]
    metrics = await _lifetime_metrics(db, tenant_id, "campaign", campaign_ids)
    links = await _campaign_links(db, tenant_id, campaign_ids)
    reported = sum(_metric_int(metrics.get(c.id, {}), "conversions") or 0 for c in campaigns)
    by_campaign = [
        {
            "campaign_id": str(c.id),
            "campaign_name": c.name or c.provider_campaign_id,
            "provider": c.provider,
            "linked_internal_campaign_id": str(links[c.id]) if c.id in links else None,
            "conversions_reported": _metric_int(metrics.get(c.id, {}), "conversions"),
            "conversions_crm_confirmed": None,
            "currency": _metric_currency(metrics.get(c.id, {}), "spend_minor"),
        }
        for c in campaigns
    ]
    linked = sum(1 for c in campaigns if c.id in links)
    return {
        "read_only": True,
        "linked_campaign_count": linked,
        "unlinked_campaign_count": len(campaigns) - linked,
        "coverage_ratio": (linked / len(campaigns)) if campaigns else None,
        "reported_conversions": reported,
        "crm_confirmed_conversions": 0,
        "by_campaign": by_campaign,
        "note": (
            "Provider-reported conversions are the provider's own attribution. "
            "CRM-confirmed conversions require the reconciliation service and are "
            "never inferred from provider data."
        ),
    }


async def campaign_attribution(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> dict[str, Any]:
    campaign = await _get_campaign_row(db, tenant_id, campaign_id)
    metrics = (await _lifetime_metrics(db, tenant_id, "campaign", [campaign.id])).get(campaign.id, {})
    links = await _campaign_links(db, tenant_id, [campaign.id])
    return {
        "campaign_id": campaign.id,
        "linked_internal_campaign_id": links.get(campaign.id),
        "conversions_reported": _metric_int(metrics, "conversions"),
        "conversions_crm_confirmed": None,
        "coverage_ratio": 1.0 if campaign.id in links else 0.0,
        "currency": _metric_currency(metrics, "spend_minor"),
        "methods": [{"method": "manual_link", "linked": campaign.id in links}],
        "evidence": {
            "note": "Provider-reported conversions only; CRM confirmation requires reconciliation.",
        },
        "read_only": True,
    }


# ---------------------------------------------------------------------------
# Mock account registration (local/dev only — never contacts a provider)
# ---------------------------------------------------------------------------


async def register_mock_account(
    db: AsyncSession,
    tenant_id: UUID,
    *,
    name: str,
    currency: str,
    provider: str = "mock",
    timezone: str | None = None,
    external_account_id: str | None = None,
    created_by: UUID | None = None,
) -> dict[str, Any]:
    """Create a tenant-scoped mock advertising account for local/dev.

    Never contacts a live provider. Only ``mock`` is accepted here.
    """
    import uuid as _uuid

    if provider != "mock":
        raise AdProviderUnsupportedError(
            "Only the 'mock' provider can be registered directly; live providers "
            "connect through Integrations.",
            details={"provider": provider},
        )
    provider_account_id = external_account_id or f"mock-{_uuid.uuid4().hex[:16]}"
    existing = (
        await db.execute(
            select(TenantAdvertisingAccount).where(
                TenantAdvertisingAccount.tenant_id == tenant_id,
                TenantAdvertisingAccount.provider == provider,
                TenantAdvertisingAccount.provider_account_id == provider_account_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise AdvertisingError(
            "A mock account with this identifier already exists.",
            details={"provider_account_id": provider_account_id},
        )
    account = TenantAdvertisingAccount(
        tenant_id=tenant_id,
        provider=provider,
        platform="mock",
        provider_account_id=provider_account_id,
        name=name,
        currency=(currency or "USD").upper(),
        timezone=timezone,
        account_status="active",
        connection_status="connected",
        is_mock=True,
    )
    db.add(account)
    await db.flush()
    return _serialize_account(account)


# ---------------------------------------------------------------------------
# Internal linkage (writes to OUR tables only — never the provider)
# ---------------------------------------------------------------------------


async def link_campaign(
    db: AsyncSession,
    tenant_id: UUID,
    campaign_id: UUID,
    marketing_campaign_id: UUID,
    *,
    created_by: UUID | None = None,
) -> dict[str, Any]:
    campaign = await _get_campaign_row(db, tenant_id, campaign_id)
    existing = (
        await db.execute(
            select(TenantAdCampaignLink).where(
                TenantAdCampaignLink.tenant_id == tenant_id,
                TenantAdCampaignLink.ad_campaign_id == campaign_id,
                TenantAdCampaignLink.marketing_campaign_id == marketing_campaign_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = "active"
    else:
        db.add(
            TenantAdCampaignLink(
                tenant_id=tenant_id,
                advertising_account_id=campaign.advertising_account_id,
                ad_campaign_id=campaign_id,
                marketing_campaign_id=marketing_campaign_id,
                link_method="manual_link",
                confidence=Decimal("1.000"),
                status="active",
                created_by=created_by,
            )
        )
    return {
        "entity_type": "campaign",
        "entity_id": campaign_id,
        "linked_internal_id": marketing_campaign_id,
        "linked": True,
        "read_only": True,
    }


async def unlink_campaign(db: AsyncSession, tenant_id: UUID, campaign_id: UUID) -> dict[str, Any]:
    await _get_campaign_row(db, tenant_id, campaign_id)
    rows = list(
        (
            await db.execute(
                select(TenantAdCampaignLink).where(
                    TenantAdCampaignLink.tenant_id == tenant_id,
                    TenantAdCampaignLink.ad_campaign_id == campaign_id,
                    TenantAdCampaignLink.status == "active",
                )
            )
        ).scalars().all()
    )
    for row in rows:
        row.status = "revoked"
    return {
        "entity_type": "campaign",
        "entity_id": campaign_id,
        "linked_internal_id": None,
        "linked": False,
        "read_only": True,
    }


async def link_creative_content(
    db: AsyncSession,
    tenant_id: UUID,
    creative_id: UUID,
    content_id: UUID,
    *,
    created_by: UUID | None = None,
) -> dict[str, Any]:
    creative = await _get_creative_row(db, tenant_id, creative_id)
    existing = (
        await db.execute(
            select(TenantAdCreativeLink).where(
                TenantAdCreativeLink.tenant_id == tenant_id,
                TenantAdCreativeLink.creative_id == creative_id,
                TenantAdCreativeLink.target_type == "content_item",
                TenantAdCreativeLink.target_id == str(content_id),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.status = "active"
    else:
        db.add(
            TenantAdCreativeLink(
                tenant_id=tenant_id,
                advertising_account_id=creative.advertising_account_id,
                creative_id=creative_id,
                target_type="content_item",
                target_id=str(content_id),
                content_id=content_id,
                link_method="manual_link",
                confidence=Decimal("1.000"),
                status="active",
                created_by=created_by,
            )
        )
    return {
        "entity_type": "creative",
        "entity_id": creative_id,
        "linked_internal_id": content_id,
        "linked": True,
        "read_only": True,
    }


async def unlink_creative_content(db: AsyncSession, tenant_id: UUID, creative_id: UUID) -> dict[str, Any]:
    await _get_creative_row(db, tenant_id, creative_id)
    rows = list(
        (
            await db.execute(
                select(TenantAdCreativeLink).where(
                    TenantAdCreativeLink.tenant_id == tenant_id,
                    TenantAdCreativeLink.creative_id == creative_id,
                    TenantAdCreativeLink.status == "active",
                )
            )
        ).scalars().all()
    )
    for row in rows:
        row.status = "revoked"
    return {
        "entity_type": "creative",
        "entity_id": creative_id,
        "linked_internal_id": None,
        "linked": False,
        "read_only": True,
    }


# ---------------------------------------------------------------------------
# Provider capabilities / configuration
# ---------------------------------------------------------------------------


def provider_capabilities() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for provider in SUPPORTED_PROVIDERS:
        spec = PROVIDER_CATALOG.get(provider)
        if spec is None:
            items.append({
                "provider": provider,
                "display_name": provider,
                "capability_status": "supported",
                "read_only": True,
                "supports_campaign_metrics": True,
                "supports_ad_level_metrics": True,
                "supports_creative_metrics": False,
                "supports_conversions": True,
                "supported_metric_keys": [],
                "unsupported_reason": None,
                "notes": None,
            })
            continue
        items.append({
            "provider": provider,
            "display_name": spec["display_name"],
            "capability_status": "supported",
            "read_only": True,
            "supports_campaign_metrics": spec["supports_campaign_metrics"],
            "supports_ad_level_metrics": spec["supports_ad_level_metrics"],
            "supports_creative_metrics": spec["supports_creative_metrics"],
            "supports_conversions": spec["supports_conversions"],
            "supported_metric_keys": list(spec["supported_metric_keys"]),
            "unsupported_reason": None,
            "notes": spec.get("notes"),
        })
    return items


async def account_capabilities(db: AsyncSession, tenant_id: UUID, account_id: UUID) -> dict[str, Any]:
    account = await _get_account_row(db, tenant_id, account_id)
    spec = PROVIDER_CATALOG.get(account.provider)
    disconnected = account.connection_status != "connected"
    if spec is None:
        return {
            "provider": account.provider,
            "display_name": account.provider,
            "capability_status": "unsupported",
            "read_only": True,
            "supports_campaign_metrics": False,
            "supports_ad_level_metrics": False,
            "supports_creative_metrics": False,
            "supports_conversions": False,
            "supported_metric_keys": [],
            "unsupported_reason": "No adapter registered for this provider.",
            "notes": None,
        }
    return {
        "provider": account.provider,
        "display_name": spec["display_name"],
        "capability_status": "disconnected" if disconnected else "supported",
        "read_only": True,
        "supports_campaign_metrics": spec["supports_campaign_metrics"],
        "supports_ad_level_metrics": spec["supports_ad_level_metrics"],
        "supports_creative_metrics": spec["supports_creative_metrics"],
        "supports_conversions": spec["supports_conversions"],
        "supported_metric_keys": list(spec["supported_metric_keys"]),
        "unsupported_reason": (
            "Account is disconnected — reconnect via Integrations to refresh metrics."
            if disconnected
            else None
        ),
        "notes": spec.get("notes"),
    }


def configuration_payload() -> dict[str, Any]:
    return {
        "read_only": True,
        "catalog_version": ADVERTISING_CATALOG_VERSION,
        "service_version": ADVERTISING_SERVICE_VERSION,
        "providers": provider_capabilities(),
        "metric_keys": list(_ALL_METRIC_KEYS),
        "objective_types": [
            "awareness", "traffic", "engagement", "leads", "app_promotion",
            "sales", "conversions", "unknown",
        ],
        "account_statuses": sorted(CONNECTION_STATUSES),
        "campaign_statuses": ["active", "paused", "deleted", "archived", "unknown"],
        "pacing_statuses": sorted(PACING_STATUSES),
        "fatigue_statuses": list(FATIGUE_STATUSES),
        "delivery_statuses": list(DELIVERY_STATUSES),
        "freshness_statuses": sorted(FRESHNESS_STATUSES),
        "creative_formats": ["image", "video", "carousel", "text", "collection", "unknown"],
        "budget_types": sorted(BUDGET_TYPES),
        "metric_semantics_version": _METRIC_SEMANTICS_VERSION,
        "limits": LIMITS,
        "notes": [
            "Advertising Intelligence is strictly read-only toward ad providers.",
            "No create, edit, pause, delete, or budget-change operations are "
            "exposed for provider campaigns, ad groups, ads, or creatives.",
            "The only writes are to internal linkage tables (linking provider "
            "campaigns/creatives to internal campaigns/content) and mock account "
            "registration for local/dev.",
        ],
    }


__all__ = [
    "ADVERTISING_CATALOG_VERSION",
    "ADVERTISING_SERVICE_VERSION",
    "PROVIDER_CATALOG",
    "SUPPORTED_PROVIDERS",
    "list_accounts",
    "get_account",
    "register_mock_account",
    "list_campaigns",
    "get_campaign",
    "campaign_performance",
    "campaign_pacing",
    "campaign_attribution",
    "list_ad_groups",
    "get_ad_group",
    "ad_group_delivery",
    "list_ads",
    "get_ad",
    "get_creative_for_ad",
    "list_creatives",
    "get_creative",
    "creative_diagnostics",
    "list_anomalies",
    "advertising_overview",
    "freshness_overview",
    "attribution_coverage",
    "link_campaign",
    "unlink_campaign",
    "link_creative_content",
    "unlink_creative_content",
    "provider_capabilities",
    "account_capabilities",
    "configuration_payload",
]
