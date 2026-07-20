"""Deterministic gap analysis for a campaign plan.

Produces a stably-ordered list of gap descriptors (never persisted here). A gap is
an advisory observation: an unfilled slot, an under-represented pillar, a missing
locale/platform, an empty phase, stale assigned content, or a blocked account.
"""
from __future__ import annotations

from typing import Any

GAP_ENGINE_VERSION = "1.0.0"

_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def analyze_gaps(
    *,
    slots: list[dict[str, Any]],
    assignments_by_slot: dict[str, dict[str, Any]],
    campaign_platforms: list[str],
    campaign_locales: list[str],
    pillar_weights: dict[str, int],
    phases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    total = len(slots)

    # --- unfilled slots
    unfilled = [
        str(s["slot_id"]) for s in slots
        if str(s["slot_id"]) not in assignments_by_slot
    ]
    if unfilled:
        ratio = len(unfilled) / total if total else 1.0
        severity = "high" if ratio >= 0.5 else "medium" if ratio >= 0.2 else "low"
        gaps.append({
            "gap_type": "unfilled_slot",
            "severity": severity,
            "dimension": "assignment",
            "dimension_value": None,
            "detail": {"count": len(unfilled), "slot_ids": unfilled[:100], "ratio": round(ratio, 4)},
        })

    # --- blocked accounts
    blocked_slots = [
        str(s["slot_id"]) for s in slots
        if (assignments_by_slot.get(str(s["slot_id"])) or {}).get("assignment_status") == "blocked"
    ]
    if blocked_slots:
        gaps.append({
            "gap_type": "blocked_account",
            "severity": "high",
            "dimension": "readiness",
            "dimension_value": None,
            "detail": {"count": len(blocked_slots), "slot_ids": blocked_slots[:100]},
        })

    # --- stale content
    stale_slots = [
        str(s["slot_id"]) for s in slots
        if (assignments_by_slot.get(str(s["slot_id"])) or {}).get("readiness_status") in ("ready_with_warnings", "blocked")
        and (assignments_by_slot.get(str(s["slot_id"])) or {}).get("assignment_status") != "blocked"
    ]
    if stale_slots:
        gaps.append({
            "gap_type": "stale_content",
            "severity": "medium",
            "dimension": "readiness",
            "dimension_value": None,
            "detail": {"count": len(stale_slots), "slot_ids": stale_slots[:100]},
        })

    # --- missing locales
    present_locales = {s["locale"] for s in slots}
    for loc in campaign_locales or []:
        if loc not in present_locales:
            gaps.append({
                "gap_type": "locale_missing",
                "severity": "medium",
                "dimension": "locale",
                "dimension_value": loc,
                "detail": {"locale": loc},
            })

    # --- missing platforms
    present_platforms = {s["platform"] for s in slots}
    for plat in campaign_platforms or []:
        if plat not in present_platforms:
            gaps.append({
                "gap_type": "platform_missing",
                "severity": "medium",
                "dimension": "platform",
                "dimension_value": plat,
                "detail": {"platform": plat},
            })

    # --- underrepresented pillars (share below target by margin)
    if pillar_weights and total:
        total_weight = sum(max(0, w) for w in pillar_weights.values()) or 1
        actual: dict[str, int] = {}
        for s in slots:
            pk = s.get("pillar_key")
            if pk:
                actual[pk] = actual.get(pk, 0) + 1
        for pk, weight in sorted(pillar_weights.items()):
            target_share = max(0, weight) / total_weight
            actual_share = actual.get(pk, 0) / total
            if actual_share + 0.05 < target_share:
                gaps.append({
                    "gap_type": "pillar_underrepresented",
                    "severity": "low",
                    "dimension": "pillar",
                    "dimension_value": pk,
                    "detail": {
                        "pillar_key": pk,
                        "target_share": round(target_share, 4),
                        "actual_share": round(actual_share, 4),
                        "actual_count": actual.get(pk, 0),
                    },
                })

    # --- empty phases
    for ph in phases or []:
        start = ph.get("start_date")
        end = ph.get("end_date")
        if not start or not end:
            continue
        has_slot = any(start <= s["date"] <= end for s in slots)
        if not has_slot:
            gaps.append({
                "gap_type": "phase_empty",
                "severity": "medium",
                "dimension": "phase",
                "dimension_value": ph.get("name"),
                "detail": {"phase": ph.get("name"), "start": start, "end": end},
            })

    gaps.sort(key=lambda g: (
        _SEVERITY_RANK.get(g.get("severity", "info"), 9),
        g.get("gap_type", ""),
        str(g.get("dimension_value") or ""),
    ))
    return gaps
