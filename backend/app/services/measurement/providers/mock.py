"""Deterministic mock metric provider.

Used for tenants/accounts with ``status == "mock"`` and as a delegate target
for platforms without a live integration. Metrics are derived from a stable
hash of ``provider_publication_id`` so repeated fetches for the same
publication return internally-consistent, monotonically non-decreasing
"cumulative" style counts once a synthetic elapsed-time factor is folded in.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.services.measurement.metric_catalog import RAW_METRIC_KEYS
from app.services.measurement.providers.base import MetricProviderAdapter, utcnow
from app.services.measurement.schemas import (
    AdapterCapabilities,
    MetricFetchRequest,
    MetricFetchResponse,
    PublicationMetricResult,
)

# Raw counters the mock provider can produce directly (identity-mapped in the
# catalog's provider_mappings["mock"]). Derived metrics (engagements, rates,
# averages) are intentionally NOT produced here — the normalizer computes
# them from these contributors, exactly like it would for a real provider.
_MOCK_BASE_KEYS = tuple(sorted(RAW_METRIC_KEYS))


def _seed(*parts: str) -> int:
    digest = hashlib.sha256("::".join(parts).encode("utf-8")).hexdigest()
    return int(digest[:16], 16)


def _growth_factor(provider_publication_id: str, *, reference_time: datetime) -> Decimal:
    """A deterministic pseudo-age factor so metrics grow smoothly over time
    without requiring persisted state. Purely a demo/QA convenience — never
    used for anything but the mock provider.
    """
    seed = _seed(provider_publication_id, "epoch")
    # Deterministic synthetic "publish" instant within the last 30 days.
    synthetic_age_seconds = (seed % (30 * 24 * 3600)) + 3600
    synthetic_published_at = reference_time - timedelta(seconds=synthetic_age_seconds)
    elapsed = max((reference_time - synthetic_published_at).total_seconds(), 0)
    # Logarithmic-ish saturating growth curve, capped at 1.0.
    factor = Decimal(1) - Decimal(1) / (Decimal(1) + Decimal(elapsed) / Decimal(3600 * 6))
    return min(factor, Decimal("0.98"))


def generate_mock_metrics(
    provider_publication_id: str,
    *,
    reference_time: datetime | None = None,
) -> dict[str, Decimal]:
    """Deterministic mock provider-native metrics for one publication.

    Stable relationships are enforced so downstream anomaly checks behave
    sensibly against mock data too: reach <= impressions, engagement
    components are a fraction of reach, etc.
    """
    now = reference_time or utcnow()
    growth = _growth_factor(provider_publication_id, reference_time=now)

    base_seed = _seed(provider_publication_id, "impressions")
    impressions_ceiling = Decimal(500 + (base_seed % 48_500))
    impressions = (impressions_ceiling * growth).to_integral_value()

    reach_ratio = Decimal("0.55") + (Decimal(_seed(provider_publication_id, "reach") % 30) / Decimal(100))
    reach = (impressions * min(reach_ratio, Decimal("0.95"))).to_integral_value()

    views_ratio = Decimal("0.85") + (Decimal(_seed(provider_publication_id, "views") % 10) / Decimal(100))
    views = (impressions * min(views_ratio, Decimal("0.99"))).to_integral_value()

    video_ratio = Decimal(_seed(provider_publication_id, "video") % 40) / Decimal(100)
    video_views = (views * video_ratio).to_integral_value()

    engagement_pool_ratio = Decimal("0.02") + (Decimal(_seed(provider_publication_id, "engage") % 12) / Decimal(1000))
    engagement_pool = (reach * engagement_pool_ratio).to_integral_value()

    def _split(pool: Decimal, key: str, weight_pct: int) -> Decimal:
        share = Decimal(_seed(provider_publication_id, key) % weight_pct + 5) / Decimal(100)
        return (pool * min(share, Decimal("0.9"))).to_integral_value()

    likes = _split(engagement_pool, "likes", 70)
    comments = _split(engagement_pool, "comments", 20)
    shares = _split(engagement_pool, "shares", 15)
    saves = _split(engagement_pool, "saves", 10)
    reactions = likes + Decimal(_seed(provider_publication_id, "reactions_extra") % max(int(likes) // 4 + 1, 1))

    clicks_ratio = Decimal("0.01") + (Decimal(_seed(provider_publication_id, "clicks") % 8) / Decimal(1000))
    clicks = (impressions * clicks_ratio).to_integral_value()
    link_clicks = (clicks * Decimal("0.7")).to_integral_value()

    profile_visits = Decimal(_seed(provider_publication_id, "visits") % 200)
    follows = Decimal(_seed(provider_publication_id, "follows") % 40)

    avg_watch_seconds = Decimal(5 + (_seed(provider_publication_id, "watch") % 55))
    watch_time_seconds = (views * avg_watch_seconds).to_integral_value()
    completion_ratio = Decimal("0.1") + (Decimal(_seed(provider_publication_id, "completion") % 30) / Decimal(100))
    completion_count = (video_views * completion_ratio).to_integral_value()

    values: dict[str, Decimal] = {
        "impressions": impressions,
        "reach": reach,
        "views": views,
        "video_views": video_views,
        "reactions": reactions,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "saves": saves,
        "clicks": clicks,
        "link_clicks": link_clicks,
        "profile_visits": profile_visits,
        "follows": follows,
        "watch_time_seconds": watch_time_seconds,
        "completion_count": completion_count,
    }
    # Only ever emit keys that are in the raw catalog, defensively.
    return {k: v for k, v in values.items() if k in _MOCK_BASE_KEYS}


class MockAdapter(MetricProviderAdapter):
    """Deterministic mock adapter — full support for every catalog metric."""

    platform = "mock"

    def capabilities(self, *, account_status: str) -> AdapterCapabilities:
        return AdapterCapabilities(
            platform=self.platform,
            capability_status="full",
            supports_post_level_metrics=True,
            supported_metric_keys=frozenset(_MOCK_BASE_KEYS),
            notes="Deterministic mock data derived from provider_publication_id.",
        )

    async def fetch_publication_metrics(self, request: MetricFetchRequest) -> MetricFetchResponse:
        now = utcnow()
        results: dict[str, PublicationMetricResult] = {}
        for provider_publication_id in request.publication_ids:
            metrics = generate_mock_metrics(provider_publication_id, reference_time=now)
            results[provider_publication_id] = PublicationMetricResult(
                provider_publication_id=provider_publication_id,
                status="ok",
                provider_metrics=metrics,
                provider_data_timestamp=now,
                raw_summary={"mock": True, "keys": sorted(metrics.keys())},
            )
        return MetricFetchResponse(
            results=results,
            provider_request_count=len(request.publication_ids),
        )

    async def fetch_account_publications(
        self,
        *,
        account_status: str,
        provider_account_id: str | None,
        cursor: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None]:
        # Discovery/backfill listing is out of scope for mock accounts —
        # publications are registered from actual publish results instead.
        return [], None

    async def health_check(self, *, account_status: str) -> dict[str, Any]:
        return {"status": "ok", "capability_status": "full", "platform": self.platform}


__all__ = ["MockAdapter", "generate_mock_metrics"]
