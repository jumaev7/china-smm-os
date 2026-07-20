"""Deterministic conflict detection for a campaign plan.

Detects, without any side effects:
- exact duplicate (platform, date, time) slots
- same-platform slots too close together (below minimum spacing)
- excessive posts for one platform on a single day (above max/day)
- the same content assigned to more than one slot on the same day

Pure function; identical inputs always yield identical, stably-ordered output.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

CONFLICT_ENGINE_VERSION = "1.0.0"


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def detect_conflicts(
    *,
    slots: list[dict[str, Any]],
    assignments_by_slot: dict[str, dict[str, Any]],
    max_posts_per_day_per_platform: int,
    min_spacing_minutes: int,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []

    # Group by (platform, date).
    by_platform_day: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for s in slots:
        by_platform_day[(s["platform"], s["date"])].append(s)

    for (platform, d), group in by_platform_day.items():
        ordered = sorted(group, key=lambda x: (x["time"], str(x["slot_id"])))
        # Duplicate exact time.
        times_seen: dict[str, str] = {}
        for s in ordered:
            if s["time"] in times_seen:
                conflicts.append({
                    "conflict_type": "duplicate_platform_time",
                    "severity": "high",
                    "platform": platform,
                    "date": d,
                    "time": s["time"],
                    "slot_ids": [times_seen[s["time"]], str(s["slot_id"])],
                })
            else:
                times_seen[s["time"]] = str(s["slot_id"])

        # Too many per day.
        if len(ordered) > max_posts_per_day_per_platform:
            conflicts.append({
                "conflict_type": "max_posts_per_day_exceeded",
                "severity": "medium",
                "platform": platform,
                "date": d,
                "count": len(ordered),
                "max": max_posts_per_day_per_platform,
                "slot_ids": [str(s["slot_id"]) for s in ordered],
            })

        # Spacing violations between consecutive slots.
        for i in range(1, len(ordered)):
            prev_t = _to_minutes(ordered[i - 1]["time"])
            cur_t = _to_minutes(ordered[i]["time"])
            if 0 <= (cur_t - prev_t) < min_spacing_minutes:
                conflicts.append({
                    "conflict_type": "min_spacing_violation",
                    "severity": "low",
                    "platform": platform,
                    "date": d,
                    "gap_minutes": cur_t - prev_t,
                    "min_spacing_minutes": min_spacing_minutes,
                    "slot_ids": [str(ordered[i - 1]["slot_id"]), str(ordered[i]["slot_id"])],
                })

    # Same content assigned twice on the same day.
    by_content_day: dict[tuple[str, str], list[str]] = defaultdict(list)
    for s in slots:
        a = assignments_by_slot.get(str(s["slot_id"]))
        if a and a.get("content_id"):
            by_content_day[(str(a["content_id"]), s["date"])].append(str(s["slot_id"]))
    for (content_id, d), slot_ids in by_content_day.items():
        if len(slot_ids) > 1:
            conflicts.append({
                "conflict_type": "same_content_same_day",
                "severity": "medium",
                "content_id": content_id,
                "date": d,
                "slot_ids": sorted(slot_ids),
            })

    # Stable ordering for determinism.
    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    conflicts.sort(key=lambda c: (
        severity_rank.get(c.get("severity", "info"), 9),
        c.get("conflict_type", ""),
        c.get("platform", ""),
        c.get("date", ""),
        str(c.get("slot_ids", "")),
    ))
    return conflicts
