"""Verify deterministic budget pacing thresholds and statuses.

Run from backend/:  python scripts/verify_advertising_pacing.py
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.models.advertising import PACING_STATUSES
    from app.services.advertising_intelligence.pacing_service import (
        PACING_CALCULATION_VERSION,
        compute_pacing,
    )

    record("calculation_version", PACING_CALCULATION_VERSION == "1.0.0", PACING_CALCULATION_VERSION)

    under = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=1000, window_days=30)
    on_pace = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=2700, window_days=30)
    over = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=5000, window_days=30)
    exhausted = compute_pacing(budget_minor=3000, budget_type="lifetime", spend_minor=3200)
    not_applicable = compute_pacing(budget_minor=None, budget_type="unknown", spend_minor=10)
    insufficient = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=None)
    paused = compute_pacing(budget_minor=100, budget_type="daily", spend_minor=50, effective_status="paused")
    ended = compute_pacing(budget_minor=100, budget_type="lifetime", spend_minor=50, effective_status="completed")

    record("underspending", under["pacing_status"] == "underspending", str(under["pacing_status"]))
    record("on_pace", on_pace["pacing_status"] == "on_pace", str(on_pace["pacing_status"]))
    record("overspending", over["pacing_status"] == "overspending", str(over["pacing_status"]))
    record("budget_exhausted", exhausted["pacing_status"] == "budget_exhausted", str(exhausted["pacing_status"]))
    record("not_applicable", not_applicable["pacing_status"] == "not_applicable")
    record("insufficient_data", insufficient["pacing_status"] == "insufficient_data")
    record("paused", paused["pacing_status"] == "paused")
    record("ended", ended["pacing_status"] == "ended")

    ratio = under["pacing_ratio"]
    record("under_ratio_below_0_8", ratio is not None and ratio < Decimal("0.8"), str(ratio))
    record("on_pace_ratio_in_band", Decimal("0.8") <= on_pace["pacing_ratio"] <= Decimal("1.2"))
    record("over_ratio_above_1_2", over["pacing_ratio"] > Decimal("1.2"))
    record(
        "statuses_in_vocab",
        {under["pacing_status"], on_pace["pacing_status"], over["pacing_status"], exhausted["pacing_status"]}
        <= PACING_STATUSES,
    )
    record(
        "deterministic",
        compute_pacing(budget_minor=100, budget_type="daily", spend_minor=1000, window_days=30) == under,
    )

    now = datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
    start = now - timedelta(days=5)
    end = now + timedelta(days=5)
    lifetime = compute_pacing(
        budget_minor=10_000,
        budget_type="lifetime",
        spend_minor=2_000,
        start_time=start,
        end_time=end,
        now=now,
    )
    record("lifetime_elapsed_fraction_present", lifetime.get("elapsed_fraction") is not None)
    record("version_on_result", lifetime.get("calculation_version") == PACING_CALCULATION_VERSION)

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
