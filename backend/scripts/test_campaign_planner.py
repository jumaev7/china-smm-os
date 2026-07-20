"""Unit-style smoke tests for Campaign Planner pure engines (no DB required).

Run from backend/:  python scripts/test_campaign_planner.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.services.campaign_planner.cadence_engine import resolve_cadence
    from app.services.campaign_planner.conflict_detector import detect_conflicts
    from app.services.campaign_planner.coverage_engine import compute_coverage
    from app.services.campaign_planner.gap_analysis import analyze_gaps
    from app.services.campaign_planner.plan_fingerprint import (
        compute_plan_fingerprint,
        compute_plan_output_fingerprint,
    )
    from app.services.campaign_planner.planning_service import generate_slots
    from app.services.campaign_planner.schemas import PhaseSpec, PillarSpec, PlanSpec

    cadence = resolve_cadence(["telegram", "instagram"], {"posts_per_week": 3, "max_posts_per_day_per_platform": 2})
    record("cadence_hard_constraints", cadence.hard.max_posts_per_day_per_platform == 2)
    record("cadence_suggested_times_labeled", all(len(p.suggested_times) >= 1 for p in cadence.preferences.values()))

    spec = PlanSpec(
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 14),
        timezone="Asia/Tashkent",
        primary_locale="en",
        locales=["en", "ru"],
        platforms=["telegram", "instagram"],
        blackout_dates=[date(2026, 3, 8)],
        cadence={"posts_per_week": 3, "max_posts_per_day_per_platform": 2, "min_spacing_minutes": 120},
        pillars=[PillarSpec(key="edu", pillar_id=None, name="Edu", weight=2), PillarSpec(key="promo", pillar_id=None, name="Promo", weight=1)],
        phases=[PhaseSpec(key="0:launch", phase_id=None, name="Launch", start_date=date(2026, 3, 1), end_date=date(2026, 3, 7), weight=1)],
    )
    slots_a = generate_slots(spec, cadence)
    slots_b = generate_slots(spec, cadence)
    record("deterministic_slot_count", len(slots_a) == len(slots_b) and len(slots_a) > 0, str(len(slots_a)))
    record(
        "deterministic_slot_identity",
        [(s.platform, s.scheduled_date, s.scheduled_time, s.locale) for s in slots_a]
        == [(s.platform, s.scheduled_date, s.scheduled_time, s.locale) for s in slots_b],
    )
    record("no_blackout_slots", all(s.scheduled_date != date(2026, 3, 8) for s in slots_a))
    seen = set()
    dup = False
    for s in slots_a:
        key = (s.platform, s.scheduled_date, s.scheduled_time)
        if key in seen:
            dup = True
        seen.add(key)
    record("no_exact_duplicate_platform_time", not dup)

    fp1 = compute_plan_fingerprint({
        "planner_version": "1.0.0", "policy_version": "1.0.0",
        "start_date": "2026-03-01", "end_date": "2026-03-14", "timezone": "Asia/Tashkent",
        "primary_locale": "en", "locales": ["en", "ru"], "platforms": ["telegram", "instagram"],
        "blackout_dates": ["2026-03-08"], "cadence": {}, "pillars": [], "phases": [],
    })
    fp2 = compute_plan_fingerprint({
        "planner_version": "1.0.0", "policy_version": "1.0.0",
        "end_date": "2026-03-14", "start_date": "2026-03-01", "timezone": "Asia/Tashkent",
        "primary_locale": "en", "locales": ["ru", "en"], "platforms": ["instagram", "telegram"],
        "blackout_dates": ["2026-03-08"], "cadence": {}, "pillars": [], "phases": [],
    })
    record("fingerprint_stable_ordering", fp1 == fp2 and len(fp1) == 64)

    out_fp_a = compute_plan_output_fingerprint([
        {"platform": s.platform, "locale": s.locale, "date": s.scheduled_date.isoformat(),
         "time": s.scheduled_time, "pillar_key": s.pillar_key, "phase_key": s.phase_key, "index": s.index}
        for s in slots_a
    ])
    out_fp_b = compute_plan_output_fingerprint([
        {"platform": s.platform, "locale": s.locale, "date": s.scheduled_date.isoformat(),
         "time": s.scheduled_time, "pillar_key": s.pillar_key, "phase_key": s.phase_key, "index": s.index}
        for s in slots_b
    ])
    record("output_fingerprint_deterministic", out_fp_a == out_fp_b)

    slot_dicts = [
        {"slot_id": f"s{i}", "platform": s.platform, "locale": s.locale,
         "date": s.scheduled_date.isoformat(), "time": s.scheduled_time, "pillar_key": s.pillar_key}
        for i, s in enumerate(slots_a)
    ]
    cov = compute_coverage(
        slots=slot_dicts, assignments_by_slot={},
        campaign_platforms=["telegram", "instagram"], campaign_locales=["en", "ru"],
    )
    record("coverage_unassigned", cov.unassigned_slots == cov.total_slots and cov.total_slots > 0)

    gaps = analyze_gaps(
        slots=slot_dicts, assignments_by_slot={},
        campaign_platforms=["telegram", "instagram", "linkedin"],
        campaign_locales=["en", "ru", "uz"],
        pillar_weights={"edu": 2, "promo": 1}, phases=[],
    )
    record("gaps_detect_unfilled", any(g["gap_type"] == "unfilled_slot" for g in gaps))
    record("gaps_detect_missing_platform", any(g["gap_type"] == "platform_missing" for g in gaps))

    conflicts = detect_conflicts(
        slots=slot_dicts + [dict(slot_dicts[0], slot_id="dup")],
        assignments_by_slot={},
        max_posts_per_day_per_platform=1,
        min_spacing_minutes=9999,
    )
    record("conflicts_detect_duplicate", any(c["conflict_type"] == "duplicate_platform_time" for c in conflicts))

    from app.models.campaign_planner import TenantMarketingCampaign
    record("model_import", TenantMarketingCampaign.__tablename__ == "tenant_marketing_campaigns")

    from app.core.events.registry import event_registry
    record("event_registered", event_registry.is_registered("campaign.plan_generated"))
    record("ai_event_registered", event_registry.is_registered("campaign.ai_plan_applied"))

    print()
    if failures:
        print(f"FAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
