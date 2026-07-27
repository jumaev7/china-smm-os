"""Fixture adapter — deterministic demo observations for QA.

Explicitly labeled as fixture/demo. Never presented as live provider data.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.services.listening.providers.base import ListeningSourceAdapter
from app.services.listening.schemas import ObservationPage, RawObservation, SourceCapabilities


def build_fixture_observations(*, seed: str = "default") -> list[RawObservation]:
    now = datetime.now(timezone.utc)
    brand = (seed or "default").strip() or "default"
    return [
        RawObservation(
            provider_external_id=f"fixture-{brand}-1",
            canonical_url=f"https://example.com/posts/{brand}-1",
            author_display="market_watcher",
            author_external_id="fixture-author-1",
            content_text=(
                f"Interesting discussion about {brand} expansion into Central Asia retail. "
                "Competitors are watching closely."
            ),
            content_type="post",
            language="en",
            published_at=now - timedelta(days=2),
            source_updated_at=None,
            engagement={"likes": 12, "comments": 3, "shares": 1},
            provider_account_ref="fixture",
            raw_safe_summary={"fixture": True, "seed": brand, "index": 1},
        ),
        RawObservation(
            provider_external_id=f"fixture-{brand}-2",
            canonical_url=f"https://news.example.com/articles/{brand}-launch",
            author_display="trade_news_uz",
            content_text=(
                f"Local buyers mention {brand} quality and delivery timelines. "
                "Some prefer alternative suppliers."
            ),
            content_type="article",
            language="en",
            published_at=now - timedelta(days=1),
            engagement={"likes": 4},
            provider_account_ref="fixture",
            raw_safe_summary={"fixture": True, "seed": brand, "index": 2},
        ),
        RawObservation(
            provider_external_id=f"fixture-{brand}-3",
            canonical_url=None,
            author_display="@competitor_voice",
            content_text="Short note without a URL — fingerprint fallback path.",
            content_type="comment",
            language="en",
            published_at=None,  # unknown stays unknown
            engagement=None,
            provider_account_ref="fixture",
            raw_safe_summary={"fixture": True, "seed": brand, "index": 3},
        ),
        # Deliberately malformed item — ingestion must skip without failing the page.
        RawObservation(
            malformed=True,
            reject_reason="fixture malformed sentinel",
            provider_account_ref="fixture",
        ),
    ]


class FixtureAdapter(ListeningSourceAdapter):
    source_type = "fixture"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            source_type=self.source_type,
            capability_status="fixture_only",
            supports_keyword_search=False,
            supports_account_feed=False,
            supports_historical_window=False,
            pagination_type="none",
            engagement_fields_available=True,
            author_fields_available=True,
            deletion_signals_available=False,
            notes=(
                "Deterministic fixture/demo observations only. "
                "Not live social listening. Never labeled as live provider data."
            ),
        )

    async def validate_configuration(self, config: dict[str, Any] | None) -> list[str]:
        return []

    async def fetch_observations(
        self,
        *,
        config: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 50,
        items: list[dict[str, Any]] | None = None,
    ) -> ObservationPage:
        seed = "default"
        if config and isinstance(config.get("seed"), str):
            seed = config["seed"]
        observations = build_fixture_observations(seed=seed)
        # Allow optional overlay items for tests.
        if items:
            from app.services.listening.providers.manual_import import ManualImportAdapter
            overlay = await ManualImportAdapter().fetch_observations(items=items, limit=limit)
            observations = overlay.items + observations

        clipped = observations[: max(0, limit)]
        rejected = sum(1 for o in clipped if o.malformed)
        return ObservationPage(
            items=clipped,
            next_cursor=None,
            provider_request_id=f"fixture:{seed}",
            fetched_count=len(clipped),
            rejected_count=rejected,
            error_summary=None if rejected == 0 else f"{rejected} malformed fixture item(s) skipped",
        )


__all__ = ["FixtureAdapter", "build_fixture_observations"]
