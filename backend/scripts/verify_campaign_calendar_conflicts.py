"""Verify calendar conflict detection.

Run from backend/:  python scripts/verify_campaign_calendar_conflicts.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    from app.services.campaign_planner.conflict_detector import detect_conflicts

    failures = []

    def record(c, ok, d=""):
        print(("OK" if ok else "FAIL") + f" {c}" + (f" — {d}" if d else ""))
        if not ok:
            failures.append(c)

    slots = [
        {"slot_id": "1", "platform": "telegram", "locale": "en", "date": "2026-07-01", "time": "09:00"},
        {"slot_id": "2", "platform": "telegram", "locale": "en", "date": "2026-07-01", "time": "09:00"},
        {"slot_id": "3", "platform": "telegram", "locale": "en", "date": "2026-07-01", "time": "09:30"},
        {"slot_id": "4", "platform": "instagram", "locale": "en", "date": "2026-07-01", "time": "10:00"},
    ]
    conflicts = detect_conflicts(
        slots=slots,
        assignments_by_slot={
            "1": {"content_id": "c1", "assignment_status": "ready", "readiness_status": "ready"},
            "4": {"content_id": "c1", "assignment_status": "ready", "readiness_status": "ready"},
        },
        max_posts_per_day_per_platform=2,
        min_spacing_minutes=60,
    )
    types = {c["conflict_type"] for c in conflicts}
    record("duplicate_detected", "duplicate_platform_time" in types)
    record("spacing_detected", "min_spacing_violation" in types)
    record("max_per_day_detected", "max_posts_per_day_exceeded" in types)
    record("same_content_same_day", "same_content_same_day" in types)
    record("stable_order", conflicts == sorted(conflicts, key=lambda c: (
        {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(c.get("severity", "info"), 9),
        c.get("conflict_type", ""),
        c.get("platform", ""),
        c.get("date", ""),
        str(c.get("slot_ids", "")),
    )))

    print()
    if failures:
        print(f"FAILED {len(failures)}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
