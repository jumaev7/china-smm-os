"""Verify advertising Event Bus registration and MIP signal safety.

Run from backend/:  python scripts/verify_advertising_signals.py
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

    from app.core.events.registry import PLATFORM_EVENT_DEFINITIONS
    from app.services.intelligence.collectors.advertising import (
        AdvertisingCollector,
        _SAFE_KEYS,
    )

    event_types = {d.event_type for d in PLATFORM_EVENT_DEFINITIONS if d.event_type.startswith("advertising.")}
    required = {
        "advertising.account_connected",
        "advertising.account_disconnected",
        "advertising.import_requested",
        "advertising.import_failed",
        "advertising.metrics_stale",
        "advertising.delivery_issue_detected",
        "advertising.attribution_recorded",
    }
    record("events_registered", required <= event_types, str(sorted(event_types)))
    record("collector_present", AdvertisingCollector is not None)
    record("collector_name", AdvertisingCollector.name == "advertising")

    forbidden_payload_keys = {
        "access_token", "refresh_token", "token", "oauth", "ad_copy", "message",
        "targeting", "raw_payload", "signed_url", "password",
    }
    overlap = forbidden_payload_keys & _SAFE_KEYS
    record("safe_keys_exclude_secrets", not overlap, str(sorted(overlap)))

    collector = AdvertisingCollector()
    record("handles_import_failed", "advertising.import_failed" in collector.event_types)

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
