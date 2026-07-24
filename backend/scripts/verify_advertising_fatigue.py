"""Verify creative fatigue diagnostics — soft wording, no automatic action.

Run from backend/:  python scripts/verify_advertising_fatigue.py
"""
from __future__ import annotations

import sys
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

    from app.services.advertising_intelligence.creative_diagnostics import (
        FATIGUE_STATUSES,
        compute_creative_fatigue,
    )

    record(
        "statuses",
        set(FATIGUE_STATUSES)
        >= {"insufficient_data", "no_signal", "possible_fatigue", "strong_fatigue_signal"},
    )

    insufficient = compute_creative_fatigue(frequency=None)
    none = compute_creative_fatigue(frequency=Decimal("1.0"))
    possible = compute_creative_fatigue(frequency=Decimal("3.0"))
    strong = compute_creative_fatigue(frequency=Decimal("5.0"))

    record("insufficient", insufficient["status"] == "insufficient_data")
    record("no_signal", none["status"] == "no_signal")
    record("possible", possible["status"] == "possible_fatigue")
    record("strong", strong["status"] == "strong_fatigue_signal")
    record("possible_wording", "Possible fatigue signal" in possible["message"])

    hard = ("replace creative immediately", "creative is exhausted", "automatically replace")
    blob = " ".join(r["message"].lower() for r in (insufficient, none, possible, strong))
    record("no_hard_action_wording", not any(h in blob for h in hard), blob[:120])
    record("deterministic", compute_creative_fatigue(frequency=Decimal("3.0")) == possible)

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
