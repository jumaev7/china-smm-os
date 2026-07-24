"""Verify explicit advertising attribution methods (no probabilistic MTA).

Run from backend/:  python scripts/verify_advertising_attribution.py
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

    from app.services.advertising_intelligence.attribution_service import (
        ATTRIBUTION_METHODS,
        classify_attribution,
    )

    required = {
        "provider_reported",
        "tracked_link_direct",
        "crm_explicit_source",
        "campaign_plan_link",
        "creative_publication_link",
        "manual_link",
        "unattributed",
    }
    record("methods_complete", required <= set(ATTRIBUTION_METHODS), str(ATTRIBUTION_METHODS))

    cases = [
        ("crm_explicit_source", {"has_crm_source": True}),
        ("tracked_link_direct", {"has_tracked_link": True}),
        ("manual_link", {"has_manual_link": True}),
        ("campaign_plan_link", {"has_campaign_plan_link": True}),
        ("creative_publication_link", {"has_creative_publication": True}),
        ("provider_reported", {"provider_reported_conversions": True}),
        ("unattributed", {}),
    ]
    for expected, kwargs in cases:
        result = classify_attribution(**kwargs)
        record(
            f"method_{expected}",
            result.get("method") == expected
            and "confidence" in result
            and "evidence_type" in result
            and "limitations" in result,
            str({k: result.get(k) for k in ("method", "confidence", "evidence_type")}),
        )

    timing_only = classify_attribution(timing_correlation_only=True)
    record("timing_alone_unattributed", timing_only["method"] == "unattributed")
    record("timing_flag_recorded", timing_only.get("timing_only_ignored") is True)
    record("timing_confidence_zero", float(timing_only["confidence"]) == 0.0)

    crm = classify_attribution(has_crm_source=True)
    provider = classify_attribution(provider_reported_conversions=True)
    record("crm_confidence_gt_provider", float(crm["confidence"]) > float(provider["confidence"]))
    record("no_mta_claims", "multi-touch" not in str(crm.get("limitations", "")).lower())

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
