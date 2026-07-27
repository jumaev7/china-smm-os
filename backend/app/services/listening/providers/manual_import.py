"""Manual import adapter — honest non-live observation source.

Accepts operator-supplied JSON observation rows. Never contacts external
providers and never labels data as live provider observations.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.services.listening.providers.base import ListeningSourceAdapter
from app.services.listening.schemas import ObservationPage, RawObservation, SourceCapabilities

_ALLOWED_KEYS = frozenset({
    "provider_external_id",
    "canonical_url",
    "author_display",
    "author_external_id",
    "content_text",
    "content_type",
    "language",
    "published_at",
    "source_updated_at",
    "engagement",
    "provider_account_ref",
})


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _row_to_observation(row: Any, index: int) -> RawObservation:
    if not isinstance(row, dict):
        return RawObservation(malformed=True, reject_reason=f"item[{index}] is not an object")

    # Ignore unknown keys so operators cannot smuggle credentials/tokens into provenance.
    known = {k: row[k] for k in row.keys() if k in _ALLOWED_KEYS}

    content = known.get("content_text")
    url = known.get("canonical_url")
    external_id = known.get("provider_external_id")
    if not content and not url and not external_id:
        return RawObservation(
            malformed=True,
            reject_reason=f"item[{index}] requires content_text, canonical_url, or provider_external_id",
        )

    engagement = known.get("engagement")
    if engagement is not None and not isinstance(engagement, dict):
        return RawObservation(malformed=True, reject_reason=f"item[{index}].engagement must be an object")

    return RawObservation(
        provider_external_id=str(external_id).strip() if external_id else None,
        canonical_url=str(url).strip() if url else None,
        author_display=str(known["author_display"]).strip() if known.get("author_display") else None,
        author_external_id=(
            str(known["author_external_id"]).strip() if known.get("author_external_id") else None
        ),
        content_text=str(content) if content is not None else None,
        content_type=str(known.get("content_type") or "post"),
        language=str(known["language"]).strip().lower() if known.get("language") else None,
        published_at=_parse_dt(known.get("published_at")),
        source_updated_at=_parse_dt(known.get("source_updated_at")),
        engagement=engagement if isinstance(engagement, dict) else None,
        provider_account_ref=str(known.get("provider_account_ref") or "manual").strip(),
        raw_safe_summary={
            "import_index": index,
            "keys": sorted(str(k) for k in known.keys())[:32],
        },
    )


class ManualImportAdapter(ListeningSourceAdapter):
    source_type = "manual_import"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            source_type=self.source_type,
            capability_status="import_only",
            supports_keyword_search=False,
            supports_account_feed=False,
            supports_historical_window=True,
            pagination_type="none",
            engagement_fields_available=True,
            author_fields_available=True,
            deletion_signals_available=False,
            notes=(
                "Manual import only. Observations are operator-supplied and are "
                "never labeled as live provider data. No external network calls."
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
        rows = items or []
        if not isinstance(rows, list):
            return ObservationPage(
                items=[],
                fetched_count=0,
                rejected_count=1,
                error_summary="import payload must be a list of observation objects",
            )

        clipped = rows[: max(0, limit)]
        observations: list[RawObservation] = []
        rejected = 0
        for idx, row in enumerate(clipped):
            obs = _row_to_observation(row, idx)
            if obs.malformed:
                rejected += 1
            observations.append(obs)

        return ObservationPage(
            items=observations,
            next_cursor=None,
            provider_request_id=None,
            fetched_count=len(clipped),
            rejected_count=rejected,
            error_summary=None if rejected == 0 else f"{rejected} malformed item(s) skipped",
        )


__all__ = ["ManualImportAdapter"]
