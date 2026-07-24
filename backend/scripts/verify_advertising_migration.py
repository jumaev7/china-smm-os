"""Verify advertising migration revision chain and no-secret DDL.

Run from backend/:  python scripts/verify_advertising_migration.py
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

    mig = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20260912_advertising_intelligence.py"
    record("migration_file_exists", mig.exists(), str(mig))
    text = mig.read_text(encoding="utf-8") if mig.exists() else ""

    record("revision_id", 'revision = "20260912_advertising_intelligence"' in text)
    record("down_revision", 'down_revision = "20260911_measurement_foundation"' in text)

    required_tables = [
        "tenant_advertising_accounts",
        "tenant_ad_campaigns",
        "tenant_ad_groups",
        "tenant_ads",
        "tenant_ad_creatives",
        "tenant_ad_entity_history",
        "tenant_ad_import_runs",
        "tenant_ad_metric_ingestion_runs",
        "tenant_ad_metric_snapshots",
        "tenant_ad_metric_values",
        "tenant_ad_metric_aggregates",
        "tenant_ad_conversion_breakdowns",
        "tenant_ad_budget_snapshots",
        "tenant_ad_delivery_anomalies",
        "tenant_ad_creative_links",
        "tenant_ad_campaign_links",
    ]
    missing = [t for t in required_tables if t not in text]
    record("tables_declared", not missing, str(missing))

    secret_hits = [
        token for token in ("access_token", "refresh_token", "oauth_token", "client_secret", "password_hash")
        if token in text.lower()
    ]
    record("no_secret_columns", not secret_hits, str(secret_hits))
    record("has_downgrade", "def downgrade" in text)
    record("has_upgrade", "def upgrade" in text)

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
