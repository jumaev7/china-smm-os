"""Deterministic, offline mock advertising provider adapter.

Generates a stable, reproducible advertising account tree (campaigns → ad
groups → ads → creatives) plus insights, derived purely from ``hashlib`` hashes
of the provider identifiers. It performs **no network I/O** and stores nothing,
so it is safe for unit tests, demos, and local development.

Key properties for tests:
- Fully deterministic: the same ``provider_account_id`` always yields the same
  structure and metrics for a given date window.
- Multi-currency: an account's currency (USD or CNY) is derived from its id, so
  a tenant with several mock accounts naturally exercises mixed-currency code
  paths (spend must never be summed across currencies).
- Money is always integer *minor units* + an explicit currency.
- Conversions carry provider-native action types (e.g. ``purchase``, ``lead``).
- Read-only: there are no create/update/delete/pause/budget methods.
"""
from __future__ import annotations

import hashlib
from datetime import timedelta
from decimal import Decimal

from app.services.advertising_intelligence.schemas import (
    AdvertisingCapabilities,
    EntityInsightResult,
    InsightsFetchRequest,
    InsightsFetchResponse,
    Money,
    ProviderAccount,
    ProviderAd,
    ProviderAdGroup,
    ProviderCampaign,
    ProviderConversion,
    ProviderCreative,
    ProviderHealth,
    ProviderMetric,
    StructureFetchRequest,
    StructureFetchResponse,
)
from app.services.advertising_platform.interfaces import (
    AdvertisingProviderAdapter,
    utcnow,
)

_CURRENCIES = ("USD", "CNY")

# Provider-native metric keys the mock reports. These deliberately match the
# ``mock`` provider mappings declared in ``metric_catalog`` so the normalizer
# maps them 1:1 (plus derived metrics computed downstream).
_OBJECTIVES = ("OUTCOME_TRAFFIC", "OUTCOME_ENGAGEMENT", "OUTCOME_SALES", "OUTCOME_LEADS")
_CTA_TYPES = ("SHOP_NOW", "LEARN_MORE", "SIGN_UP", "BOOK_TRAVEL")
_CONVERSION_ACTIONS = ("purchase", "lead", "complete_registration", "add_to_cart")

_SUPPORTED_METRIC_KEYS = frozenset({
    "impressions", "reach", "clicks", "link_clicks", "video_views",
    "spend_minor", "conversions", "conversion_value_minor",
})
_SUPPORTED_BREAKDOWNS = frozenset({
    "age", "gender", "country", "region", "publisher_platform",
})


def _seed(*parts: str) -> int:
    raw = "|".join(parts)
    return int(hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12], 16)


def _pick(options: tuple, *parts: str):
    return options[_seed(*parts) % len(options)]


def _in_range(value: int, low: int, high: int) -> int:
    span = max(1, high - low + 1)
    return low + (value % span)


def account_currency(provider_account_id: str) -> str:
    return _CURRENCIES[_seed("currency", provider_account_id) % len(_CURRENCIES)]


# ---------------------------------------------------------------------------
# Structure generation (deterministic)
# ---------------------------------------------------------------------------


def _campaign_count(acct: str) -> int:
    return _in_range(_seed("ncamp", acct), 2, 3)


def _ad_group_count(acct: str, camp: str) -> int:
    return _in_range(_seed("nag", acct, camp), 1, 2)


def _ad_count(acct: str, ag: str) -> int:
    return _in_range(_seed("nad", acct, ag), 1, 2)


def _effective_status(seed_val: int) -> str:
    # Mostly active; a deterministic minority paused for diagnostics coverage.
    return "paused" if seed_val % 5 == 0 else "active"


def build_account(provider_account_id: str) -> ProviderAccount:
    currency = account_currency(provider_account_id)
    return ProviderAccount(
        provider_account_id=provider_account_id,
        name=f"Mock Ad Account {provider_account_id[-6:]}",
        currency=currency,
        timezone="UTC",
        account_status="active",
        provider_business_id=f"mockbiz-{_seed('biz', provider_account_id) % 100000}",
        capabilities={"read_only": True, "provider": "mock"},
        permission_summary={"scopes": ["ads_read"], "can_read_insights": True},
    )


def build_structure(provider_account_id: str) -> StructureFetchResponse:
    currency = account_currency(provider_account_id)
    account = build_account(provider_account_id)
    campaigns: list[ProviderCampaign] = []
    ad_groups: list[ProviderAdGroup] = []
    ads: list[ProviderAd] = []
    creatives: list[ProviderCreative] = []

    for ci in range(_campaign_count(provider_account_id)):
        camp_id = f"{provider_account_id}-camp-{ci + 1}"
        camp_seed = _seed("camp", camp_id)
        daily_budget_minor = _in_range(camp_seed, 5, 500) * 100  # 5.00 - 500.00
        campaigns.append(
            ProviderCampaign(
                provider_campaign_id=camp_id,
                name=f"Campaign {ci + 1}",
                objective=_pick(_OBJECTIVES, "obj", camp_id),
                buying_type="AUCTION",
                config_status="active",
                effective_status=_effective_status(camp_seed),
                bid_strategy="LOWEST_COST_WITHOUT_CAP",
                daily_budget=Money(daily_budget_minor, currency),
                created_time=None,
                updated_time=None,
            )
        )
        for gi in range(_ad_group_count(provider_account_id, camp_id)):
            ag_id = f"{camp_id}-adset-{gi + 1}"
            ag_seed = _seed("adset", ag_id)
            ad_groups.append(
                ProviderAdGroup(
                    provider_ad_group_id=ag_id,
                    provider_campaign_id=camp_id,
                    name=f"Ad Set {ci + 1}.{gi + 1}",
                    config_status="active",
                    effective_status=_effective_status(ag_seed),
                    optimization_goal="OFFSITE_CONVERSIONS",
                    billing_event="IMPRESSIONS",
                    daily_budget=Money(_in_range(ag_seed, 5, 200) * 100, currency),
                )
            )
            for ai in range(_ad_count(provider_account_id, ag_id)):
                ad_id = f"{ag_id}-ad-{ai + 1}"
                cre_id = f"{ag_id}-cre-{ai + 1}"
                ad_seed = _seed("ad", ad_id)
                creatives.append(
                    ProviderCreative(
                        provider_creative_id=cre_id,
                        name=f"Creative {ci + 1}.{gi + 1}.{ai + 1}",
                        title=f"Mock Headline {ai + 1}",
                        body="Deterministic mock creative body copy.",
                        call_to_action_type=_pick(_CTA_TYPES, "cta", cre_id),
                        object_type="SHARE",
                        thumbnail_url=f"https://mock.local/thumb/{cre_id}.jpg",
                        permalink_url=f"https://mock.local/ad/{cre_id}",
                    )
                )
                ads.append(
                    ProviderAd(
                        provider_ad_id=ad_id,
                        provider_ad_group_id=ag_id,
                        provider_creative_id=cre_id,
                        name=f"Ad {ci + 1}.{gi + 1}.{ai + 1}",
                        config_status="active",
                        effective_status=_effective_status(ad_seed),
                    )
                )

    return StructureFetchResponse(
        account=account,
        campaigns=campaigns,
        ad_groups=ad_groups,
        ads=ads,
        creatives=creatives,
        provider_request_count=1,
        status="ok",
    )


# ---------------------------------------------------------------------------
# Insights generation (deterministic)
# ---------------------------------------------------------------------------


def _entity_metrics(provider_entity_id: str, currency: str, window_key: str) -> list[ProviderMetric]:
    s = _seed("insights", provider_entity_id, window_key)
    impressions = _in_range(s, 1000, 100000)
    # Reach <= impressions; frequency emerges as impressions/reach downstream.
    reach = max(1, int(impressions / (1 + (s % 400) / 100.0)))
    clicks = max(0, int(impressions * (0.4 + (s % 30) / 10.0) / 100.0))
    link_clicks = int(clicks * (0.5 + (s % 40) / 100.0))
    video_views = int(impressions * (s % 25) / 100.0)
    # Spend in minor units, currency-specific.
    spend_minor = _in_range(_seed("spend", provider_entity_id, window_key), 500, 5_000_00)
    conversions = int(clicks * (s % 12) / 100.0)
    conversion_value_minor = conversions * _in_range(_seed("cv", provider_entity_id), 800, 25000)

    return [
        ProviderMetric("impressions", Decimal(impressions), value_type="count"),
        ProviderMetric("reach", Decimal(reach), value_type="count"),
        ProviderMetric("clicks", Decimal(clicks), value_type="count"),
        ProviderMetric("link_clicks", Decimal(link_clicks), value_type="count"),
        ProviderMetric("video_views", Decimal(video_views), value_type="count"),
        ProviderMetric("spend_minor", Decimal(spend_minor), value_type="currency_minor", currency=currency),
        ProviderMetric("conversions", Decimal(conversions), value_type="count"),
        ProviderMetric(
            "conversion_value_minor",
            Decimal(conversion_value_minor),
            value_type="currency_minor",
            currency=currency,
        ),
    ]


def _entity_conversions(provider_entity_id: str, currency: str, total_conversions: int) -> list[ProviderConversion]:
    if total_conversions <= 0:
        return []
    conversions: list[ProviderConversion] = []
    remaining = total_conversions
    actions = _CONVERSION_ACTIONS[: 1 + (_seed("nact", provider_entity_id) % len(_CONVERSION_ACTIONS))]
    for idx, action in enumerate(actions):
        is_last = idx == len(actions) - 1
        share = remaining if is_last else max(0, int(remaining / (len(actions) - idx)))
        remaining -= share
        conversions.append(
            ProviderConversion(
                action_type=action,
                value=Decimal(share),
                action_destination="website",
                attribution_setting="7d_click_1d_view",
                conversion_window="7d_click",
                value_type="count",
            )
        )
    return conversions


def build_insights(request: InsightsFetchRequest) -> InsightsFetchResponse:
    currency = account_currency(request.provider_account_id)
    window_key = f"{request.date_start}:{request.date_stop}"
    entity_ids = request.provider_entity_ids or [f"{request.provider_account_id}-camp-1"]
    results: list[EntityInsightResult] = []
    for provider_entity_id in entity_ids:
        metrics = _entity_metrics(provider_entity_id, currency, window_key)
        total_conversions = int(next((m.value for m in metrics if m.provider_metric_key == "conversions"), Decimal(0)))
        results.append(
            EntityInsightResult(
                provider_entity_id=provider_entity_id,
                entity_type=request.level,
                level=request.level,
                status="ok",
                metrics=metrics,
                conversions=_entity_conversions(provider_entity_id, currency, total_conversions),
                currency=currency,
                date_start=request.date_start,
                date_stop=request.date_stop,
                provider_data_timestamp=utcnow() - timedelta(hours=1),
            )
        )
    return InsightsFetchResponse(results=results, provider_request_count=1, status="ok")


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class MockAdvertisingAdapter(AdvertisingProviderAdapter):
    """Deterministic, offline read-only advertising adapter."""

    provider = "mock"

    def capabilities(self, *, connection_status: str) -> AdvertisingCapabilities:
        return AdvertisingCapabilities(
            provider=self.provider,
            capability_status="mock_only",
            supports_structure_import=True,
            supports_insights=True,
            supports_conversions=True,
            supports_breakdowns=True,
            supported_metric_keys=_SUPPORTED_METRIC_KEYS,
            supported_breakdowns=_SUPPORTED_BREAKDOWNS,
            notes="Deterministic offline mock advertising data (no network).",
        )

    async def health_check(self, *, connection_status: str) -> ProviderHealth:
        return ProviderHealth(
            provider=self.provider,
            status="ok",
            connection_status=connection_status,
            capability_status="mock_only",
            checked_at=utcnow(),
        )

    async def fetch_structure(self, request: StructureFetchRequest) -> StructureFetchResponse:
        return build_structure(request.provider_account_id)

    async def fetch_insights(self, request: InsightsFetchRequest) -> InsightsFetchResponse:
        return build_insights(request)


__all__ = [
    "MockAdvertisingAdapter",
    "account_currency",
    "build_account",
    "build_structure",
    "build_insights",
]
