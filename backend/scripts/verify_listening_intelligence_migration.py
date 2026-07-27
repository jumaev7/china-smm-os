"""Verify Listening Phase 2 migration revision + ensure helper create-only.

Run from backend/:  python scripts/verify_listening_intelligence_migration.py
"""
from __future__ import annotations

import inspect
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

    mig = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "20260915_listening_market_intelligence.py"
    record("migration_file_exists", mig.exists(), str(mig))
    text = mig.read_text(encoding="utf-8") if mig.exists() else ""
    record("revision_id", 'revision = "20260915_listening_market_intelligence"' in text)
    record("down_revision", 'down_revision = "20260914_social_listening_foundation"' in text)
    record("creates_insight_reviews", "tenant_listening_insight_reviews" in text)
    record("has_downgrade", "def downgrade" in text)

    from app.core import database as dbmod

    src = inspect.getsource(dbmod._ensure_listening_tables)
    record("ensure_has_insight_reviews", "tenant_listening_insight_reviews" in src)
    record("ensure_create_only", "ALTER TABLE" not in src.upper())

    from app.models.listening import TenantListeningInsightReview, LISTENING_SCHEMA_VERSION

    record("model_imported", TenantListeningInsightReview.__tablename__ == "tenant_listening_insight_reviews")
    record("schema_version_bumped", LISTENING_SCHEMA_VERSION.startswith("1."))

    if failures:
        print(f"\n{len(failures)} failure(s)")
        for f in failures:
            print(" -", f)
        return 1
    print("\nListening Phase 2 migration checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
