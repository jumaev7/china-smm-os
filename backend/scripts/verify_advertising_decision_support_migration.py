"""Verify Advertising Decision Support migration revision chain.

Run from backend/:  python scripts/verify_advertising_decision_support_migration.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    mig = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "versions"
        / "20260913_advertising_decision_support.py"
    )
    record("migration_file_exists", mig.exists(), str(mig))
    text = mig.read_text(encoding="utf-8") if mig.exists() else ""

    record("revision_id", 'revision = "20260913_advertising_decision_support"' in text)
    record("down_revision", 'down_revision = "20260912_advertising_intelligence"' in text)

    required_tables = [
        "tenant_ad_budget_simulations",
        "tenant_ad_budget_simulation_items",
        "tenant_ad_experiments",
        "tenant_ad_experiment_variants",
        "tenant_ad_experiment_measurements",
        "tenant_ad_experiment_reviews",
        "tenant_ad_change_plans",
        "tenant_ad_change_plan_items",
    ]
    missing = [t for t in required_tables if t not in text]
    record("tables_declared", not missing, str(missing))

    secret_hits = [
        token
        for token in ("access_token", "refresh_token", "oauth_token", "client_secret", "password_hash")
        if token in text.lower()
    ]
    record("no_secret_columns", not secret_hits, str(secret_hits))

    forbidden = ["provider_payload", "executable_command", "approved_for_execution", "provider_synced"]
    found_forbidden = [t for t in forbidden if t in text]
    record("no_executable_provider_columns", not found_forbidden, str(found_forbidden))

    record("has_downgrade", "def downgrade" in text)
    record("has_upgrade", "def upgrade" in text)

    # Alembic single head
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        record("single_alembic_head", len(heads) == 1, str(heads))
        record(
            "head_is_decision_support",
            heads == ["20260913_advertising_decision_support"],
            str(heads),
        )
    except Exception as exc:  # noqa: BLE001
        record("alembic_heads_check", False, str(exc))

    if failures:
        print(f"\nFAILED {len(failures)} check(s)")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
