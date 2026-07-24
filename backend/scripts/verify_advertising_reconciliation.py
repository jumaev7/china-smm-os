"""Verify provider vs CRM conversion reconciliation rules.

Run from backend/:  python scripts/verify_advertising_reconciliation.py
"""
from __future__ import annotations

import sys
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

    from app.services.advertising_intelligence.conversion_reconciliation import (
        RECONCILIATION_STATUSES,
        compute_reconciliation,
    )

    record(
        "statuses_complete",
        {
            "not_available", "provider_only", "crm_only", "matched",
            "partial_match", "discrepant", "unattributed",
        } <= set(RECONCILIATION_STATUSES),
    )

    provider_only = compute_reconciliation(reported=10, crm_confirmed=None, has_explicit_link=False)
    record("provider_only", provider_only["status"] == "provider_only", provider_only["status"])

    crm_only = compute_reconciliation(reported=0, crm_confirmed=5, has_explicit_link=True)
    record("crm_only", crm_only["status"] == "crm_only", crm_only["status"])

    matched = compute_reconciliation(reported=8, crm_confirmed=8, has_explicit_link=True)
    record("matched", matched["status"] == "matched", matched["status"])

    partial = compute_reconciliation(reported=10, crm_confirmed=9, has_explicit_link=True)
    record("partial_match", partial["status"] == "partial_match", partial["status"])

    discrepant = compute_reconciliation(reported=20, crm_confirmed=5, has_explicit_link=True)
    record("discrepant", discrepant["status"] == "discrepant", discrepant["status"])

    # Timing alone / no explicit link must NOT claim a match even if counts equal.
    no_link = compute_reconciliation(reported=5, crm_confirmed=5, has_explicit_link=False)
    record("timing_or_count_alone_rejected", no_link["status"] == "provider_only", no_link["status"])

    unattributed = compute_reconciliation(reported=0, crm_confirmed=0, has_explicit_link=False)
    record("unattributed_zero", unattributed["status"] == "unattributed")

    record("provider_vs_crm_distinct", matched["reported"] == 8 and matched["crm_confirmed"] == 8)

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
