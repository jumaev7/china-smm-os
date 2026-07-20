"""Cadence engine — separates hard constraints, preferences, and recommendations.

Three distinct layers, never conflated:

* HARD CONSTRAINTS — always enforced by the deterministic planner (max posts/day
  per platform, minimum spacing, blackout dates, date range, no exact duplicate
  platform/time).
* PREFERENCES — desired posting frequency and rule-based *suggested* posting times.
  These shape the plan but never violate a hard constraint. Suggested times are
  fixed rule-based defaults, explicitly NOT "optimal" times.
* RECOMMENDATIONS — advisory-only hints surfaced to the user; they never change
  the generated plan.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.services.campaign_planner import limits
from app.services.campaign_planner.errors import ValidationError

# Rule-based default suggested times per platform (24h "HH:MM"), with a short
# label. These are deterministic conventions, NOT engagement-optimal predictions.
_DEFAULT_SUGGESTED_TIMES: dict[str, list[tuple[str, str]]] = {
    "telegram": [("09:00", "morning"), ("13:00", "midday"), ("18:00", "evening")],
    "facebook": [("10:00", "morning"), ("15:00", "afternoon"), ("19:00", "evening")],
    "instagram": [("11:00", "late_morning"), ("17:00", "afternoon"), ("20:00", "evening")],
    "tiktok": [("12:00", "midday"), ("16:00", "afternoon"), ("21:00", "night")],
    "linkedin": [("08:00", "early_morning"), ("12:00", "midday"), ("17:00", "afternoon")],
}
_FALLBACK_TIMES = [("09:00", "morning"), ("14:00", "afternoon"), ("19:00", "evening")]

# Default desired posts-per-week per platform (preference layer).
_DEFAULT_POSTS_PER_WEEK = 3


@dataclass(frozen=True)
class HardConstraints:
    max_posts_per_day_per_platform: int
    min_spacing_minutes: int
    include_weekends: bool


@dataclass(frozen=True)
class PlatformPreference:
    platform: str
    posts_per_week: int
    suggested_times: list[tuple[str, str]]


@dataclass
class ResolvedCadence:
    hard: HardConstraints
    preferences: dict[str, PlatformPreference]
    recommendations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "hard_constraints": {
                "max_posts_per_day_per_platform": self.hard.max_posts_per_day_per_platform,
                "min_spacing_minutes": self.hard.min_spacing_minutes,
                "include_weekends": self.hard.include_weekends,
            },
            "preferences": {
                p: {
                    "posts_per_week": pref.posts_per_week,
                    "suggested_times": [t for t, _ in pref.suggested_times],
                }
                for p, pref in self.preferences.items()
            },
            "recommendations": list(self.recommendations),
        }


def _suggested_times_for(platform: str, requested: list | None) -> list[tuple[str, str]]:
    if requested:
        out: list[tuple[str, str]] = []
        for item in requested:
            t = str(item).strip()
            if len(t) == 5 and t[2] == ":" and t[:2].isdigit() and t[3:].isdigit():
                hh, mm = int(t[:2]), int(t[3:])
                if 0 <= hh <= 23 and 0 <= mm <= 59:
                    out.append((f"{hh:02d}:{mm:02d}", "custom"))
        if out:
            # Deterministic ordering by time.
            return sorted(set(out), key=lambda x: x[0])
    return list(_DEFAULT_SUGGESTED_TIMES.get(platform, _FALLBACK_TIMES))


def resolve_cadence(platforms: list[str], cadence: dict | None) -> ResolvedCadence:
    """Normalize a cadence config into hard/preferences/recommendations layers."""
    cadence = cadence or {}

    max_per_day = int(cadence.get("max_posts_per_day_per_platform", 2))
    if max_per_day < 1:
        raise ValidationError("max_posts_per_day_per_platform must be >= 1", details={"field": "cadence.max_posts_per_day_per_platform"}).to_http()
    if max_per_day > limits.MAX_POSTS_PER_DAY_PER_PLATFORM:
        max_per_day = limits.MAX_POSTS_PER_DAY_PER_PLATFORM

    min_spacing = int(cadence.get("min_spacing_minutes", 120))
    if min_spacing < limits.MIN_SPACING_MINUTES:
        min_spacing = limits.MIN_SPACING_MINUTES

    include_weekends = bool(cadence.get("include_weekends", True))

    hard = HardConstraints(
        max_posts_per_day_per_platform=max_per_day,
        min_spacing_minutes=min_spacing,
        include_weekends=include_weekends,
    )

    per_platform_cfg = cadence.get("platforms") or {}
    default_ppw = int(cadence.get("posts_per_week", _DEFAULT_POSTS_PER_WEEK))
    preferences: dict[str, PlatformPreference] = {}
    for platform in platforms:
        pcfg = per_platform_cfg.get(platform) or {}
        ppw = int(pcfg.get("posts_per_week", default_ppw))
        ppw = max(1, min(ppw, max_per_day * 7))
        preferences[platform] = PlatformPreference(
            platform=platform,
            posts_per_week=ppw,
            suggested_times=_suggested_times_for(platform, pcfg.get("suggested_times")),
        )

    recommendations: list[str] = []
    if not include_weekends:
        recommendations.append("Weekends are excluded; consider enabling weekend posting for broader reach.")
    if min_spacing > 240:
        recommendations.append("Large minimum spacing may reduce total posting volume.")

    return ResolvedCadence(hard=hard, preferences=preferences, recommendations=recommendations)
