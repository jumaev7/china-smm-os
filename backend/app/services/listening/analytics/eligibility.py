"""Eligibility policy for Listening Phase 2 production intelligence.

Policy version: ``listening_eligibility_v1``

Rules
-----
Production intelligence includes:
- tenant-scoped observations
- non-fixture origins (manual_import / live_provider / webhook when present)
- observations inside the requested analysis window (when a window applies)
- valid project scope when a project filter is provided

Review policy (default ``default_exclude_irrelevant``):
- exclude ``irrelevant``
- include ``unreviewed``, ``relevant``, ``needs_follow_up``, ``resolved``
- expose unreviewed proportion in coverage

Timestamp policy:
- time-series / windowed metrics use ``published_at`` when present
- if ``published_at`` is null, the mention is excluded from time-series buckets
  but retained in total-data-quality / eligibility totals as
  ``missing_timestamp``
- ``published_at`` is NEVER invented as ``now``

Fixture policy:
- excluded from production intelligence mode
- may be included only when ``include_fixture=True`` (dev/demo displays)
- never silently blended into production executive insights
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable
from uuid import UUID

from app.services.listening.analytics.contracts import (
    ELIGIBILITY_POLICY_VERSION,
    FIXTURE_ORIGINS,
    PRODUCTION_ORIGINS,
    ReviewPolicy,
)

DEFAULT_INCLUDED_REVIEW_STATES = frozenset({
    "unreviewed",
    "relevant",
    "needs_follow_up",
    "resolved",
})
RELEVANT_ONLY_STATES = frozenset({"relevant", "needs_follow_up", "resolved"})
ALL_REVIEW_STATES = frozenset({
    "unreviewed",
    "relevant",
    "irrelevant",
    "needs_follow_up",
    "resolved",
})


@dataclass(frozen=True)
class EligibilityFilter:
    tenant_id: UUID
    project_id: UUID | None = None
    subject_ids: frozenset[UUID] | None = None
    query_ids: frozenset[UUID] | None = None
    source_types: frozenset[str] | None = None
    content_types: frozenset[str] | None = None
    languages: frozenset[str] | None = None
    review_policy: ReviewPolicy = "default_exclude_irrelevant"
    include_fixture: bool = False
    window_start: datetime | None = None
    window_end: datetime | None = None
    require_published_at_for_timeseries: bool = False

    @property
    def policy_version(self) -> str:
        return ELIGIBILITY_POLICY_VERSION

    def allowed_review_states(self) -> frozenset[str]:
        if self.review_policy == "include_all":
            return ALL_REVIEW_STATES
        if self.review_policy == "relevant_only":
            return RELEVANT_ONLY_STATES
        return DEFAULT_INCLUDED_REVIEW_STATES

    def allowed_origins(self) -> frozenset[str]:
        if self.include_fixture:
            return PRODUCTION_ORIGINS | FIXTURE_ORIGINS
        return PRODUCTION_ORIGINS


def analytical_timestamp(mention: Any) -> datetime | None:
    """Return the timestamp used for time-series placement, or None if unknown."""
    published = getattr(mention, "published_at", None)
    if published is not None:
        return published
    return None


def is_origin_eligible(origin: str | None, *, include_fixture: bool) -> bool:
    if not origin:
        return False
    if origin in FIXTURE_ORIGINS:
        return include_fixture
    return origin in PRODUCTION_ORIGINS


def is_review_eligible(review_state: str | None, policy: ReviewPolicy) -> bool:
    states = DEFAULT_INCLUDED_REVIEW_STATES
    if policy == "include_all":
        states = ALL_REVIEW_STATES
    elif policy == "relevant_only":
        states = RELEVANT_ONLY_STATES
    return (review_state or "unreviewed") in states


def mention_eligible_for_intelligence(
    mention: Any,
    filt: EligibilityFilter,
    *,
    for_timeseries: bool = False,
) -> tuple[bool, str | None]:
    """Return (eligible, exclusion_reason)."""
    if getattr(mention, "tenant_id", None) != filt.tenant_id:
        return False, "cross_tenant"
    if filt.project_id is not None and getattr(mention, "project_id", None) != filt.project_id:
        return False, "project_filter"
    origin = getattr(mention, "observation_origin", None) or getattr(mention, "source_type", None)
    if not is_origin_eligible(origin, include_fixture=filt.include_fixture):
        return False, "fixture_excluded" if origin in FIXTURE_ORIGINS else "origin_ineligible"
    if not is_review_eligible(getattr(mention, "review_state", None), filt.review_policy):
        return False, "review_excluded"
    if filt.source_types and getattr(mention, "source_type", None) not in filt.source_types:
        return False, "source_filter"
    if filt.content_types and getattr(mention, "content_type", None) not in filt.content_types:
        return False, "content_type_filter"
    if filt.languages:
        lang = (getattr(mention, "language", None) or "").split("-")[0].lower()
        if lang not in {x.lower() for x in filt.languages}:
            return False, "language_filter"

    if for_timeseries or filt.require_published_at_for_timeseries:
        ts = analytical_timestamp(mention)
        if ts is None:
            return False, "missing_published_at"
        if filt.window_start is not None and ts < filt.window_start:
            return False, "before_window"
        if filt.window_end is not None and ts >= filt.window_end:
            return False, "after_window"
    elif filt.window_start is not None or filt.window_end is not None:
        # Non-timeseries window filter: use published_at when present, else observed_at
        # only for quality inventory — but still require published_at for intelligence
        # window membership when counting "in-window eligible".
        ts = analytical_timestamp(mention)
        if ts is None:
            return False, "missing_published_at"
        if filt.window_start is not None and ts < filt.window_start:
            return False, "before_window"
        if filt.window_end is not None and ts >= filt.window_end:
            return False, "after_window"

    return True, None


def filter_mentions(
    mentions: Iterable[Any],
    filt: EligibilityFilter,
    *,
    for_timeseries: bool = False,
) -> list[Any]:
    return [
        m for m in mentions
        if mention_eligible_for_intelligence(m, filt, for_timeseries=for_timeseries)[0]
    ]
