"""Deterministic coverage scoring for a campaign plan.

Coverage is an advisory 0–100 score blending: how many slots are assigned, how
evenly platforms/locales/pillars are represented, and how many slots are blocked.
Pure functions — identical inputs always produce identical scores.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

COVERAGE_ENGINE_VERSION = "1.0.0"


@dataclass
class CoverageResult:
    coverage_score: int
    total_slots: int
    assigned_slots: int
    blocked_slots: int
    unassigned_slots: int
    platform_distribution: dict[str, int] = field(default_factory=dict)
    locale_distribution: dict[str, int] = field(default_factory=dict)
    pillar_distribution: dict[str, int] = field(default_factory=dict)
    missing_platforms: list[str] = field(default_factory=list)
    missing_locales: list[str] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "coverage_score": self.coverage_score,
            "total_slots": self.total_slots,
            "assigned_slots": self.assigned_slots,
            "blocked_slots": self.blocked_slots,
            "unassigned_slots": self.unassigned_slots,
            "platform_distribution": self.platform_distribution,
            "locale_distribution": self.locale_distribution,
            "pillar_distribution": self.pillar_distribution,
            "missing_platforms": self.missing_platforms,
            "missing_locales": self.missing_locales,
            "engine_version": COVERAGE_ENGINE_VERSION,
            **self.detail,
        }


def _balance_ratio(distribution: dict[str, int], expected_keys: list[str]) -> float:
    """1.0 when every expected key is present; scaled by how many are covered."""
    if not expected_keys:
        return 1.0
    covered = sum(1 for k in expected_keys if distribution.get(k, 0) > 0)
    return covered / len(expected_keys)


def compute_coverage(
    *,
    slots: list[dict[str, Any]],
    assignments_by_slot: dict[str, dict[str, Any]],
    campaign_platforms: list[str],
    campaign_locales: list[str],
) -> CoverageResult:
    total = len(slots)
    platform_dist: dict[str, int] = {}
    locale_dist: dict[str, int] = {}
    pillar_dist: dict[str, int] = {}
    assigned = 0
    blocked = 0
    for s in slots:
        platform_dist[s["platform"]] = platform_dist.get(s["platform"], 0) + 1
        locale_dist[s["locale"]] = locale_dist.get(s["locale"], 0) + 1
        pk = s.get("pillar_key") or "unassigned_pillar"
        pillar_dist[pk] = pillar_dist.get(pk, 0) + 1
        a = assignments_by_slot.get(str(s["slot_id"]))
        if a is not None:
            if a.get("assignment_status") == "blocked":
                blocked += 1
            else:
                assigned += 1

    unassigned = total - assigned - blocked
    if total == 0:
        return CoverageResult(
            coverage_score=0, total_slots=0, assigned_slots=0, blocked_slots=0, unassigned_slots=0,
            detail={"note": "No slots in plan."},
        )

    assign_ratio = assigned / total
    block_penalty = blocked / total
    platform_balance = _balance_ratio(platform_dist, campaign_platforms or list(platform_dist.keys()))
    locale_balance = _balance_ratio(locale_dist, campaign_locales or list(locale_dist.keys()))

    # Weighted composite (deterministic).
    score = (
        assign_ratio * 60.0
        + platform_balance * 15.0
        + locale_balance * 15.0
        + (1.0 - block_penalty) * 10.0
    )
    coverage_score = max(0, min(100, int(round(score))))

    missing_platforms = [p for p in (campaign_platforms or []) if platform_dist.get(p, 0) == 0]
    missing_locales = [loc for loc in (campaign_locales or []) if locale_dist.get(loc, 0) == 0]

    return CoverageResult(
        coverage_score=coverage_score,
        total_slots=total,
        assigned_slots=assigned,
        blocked_slots=blocked,
        unassigned_slots=unassigned,
        platform_distribution=platform_dist,
        locale_distribution=locale_dist,
        pillar_distribution=pillar_dist,
        missing_platforms=missing_platforms,
        missing_locales=missing_locales,
        detail={
            "assign_ratio": round(assign_ratio, 4),
            "platform_balance": round(platform_balance, 4),
            "locale_balance": round(locale_balance, 4),
        },
    )
