"""Offline smoke tests for Social Listening Phase 1 (no HTTP, no DB).

Pure checks over the read-only listening domain: adapter write-boundary,
URL scheme safety, dedupe key priority, matcher evidence, and fixture gating
helpers.

Run from backend/:  python scripts/test_listening_foundation.py
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    except Exception:
        pass

_WRITE_PREFIXES = (
    "publish",
    "reply",
    "comment",
    "react",
    "like",
    "message",
    "follow",
    "block",
    "report",
    "delete",
    "mutate",
    "send_",
    "create_comment",
    "boost",
)


def _write_like_methods(obj) -> list[str]:
    found: list[str] = []
    for name, _ in inspect.getmembers(obj, predicate=inspect.ismethod):
        if name.startswith("__"):
            continue
        lower = name.lower()
        if any(lower.startswith(p) or p in lower for p in _WRITE_PREFIXES):
            # Allow health_check / fetch_observations / validate_configuration.
            if name in {
                "capabilities",
                "validate_configuration",
                "fetch_observations",
                "health_check",
            }:
                continue
            found.append(name)
    return found


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    from app.core.config import settings
    from app.services.listening.dedupe import (
        build_content_fingerprint,
        build_dedupe_key,
        canonicalize_url,
    )
    from app.services.listening.ingestion_service import (
        fixture_ingest_allowed,
        projects_eligible_for_scheduled_ingestion,
    )
    from app.services.listening.matching import find_boundary_match, match_mention_against_queries
    from app.services.listening.providers import get_adapter, list_source_capabilities
    from app.services.listening.providers.base import ListeningSourceAdapter
    from app.services.listening.schemas import SourceCapabilities

    # --- URL scheme safety ---
    record("url_rejects_javascript", canonicalize_url("javascript:alert(1)") is None)
    record("url_rejects_data", canonicalize_url("data:text/html,hi") is None)
    record("url_rejects_ftp", canonicalize_url("ftp://files.example.com/a") is None)
    record(
        "url_accepts_https",
        canonicalize_url("https://WWW.Example.com/path/?utm_source=x") == "https://example.com/path",
    )

    # --- Dedupe priority ---
    fp = build_content_fingerprint(
        source_type="manual_import",
        provider_account_ref="acct",
        author_display="a",
        content_text="Hello",
        published_at=None,
        canonical_url="https://example.com/p/1",
    )
    key = build_dedupe_key(
        source_type="manual_import",
        provider_account_ref="acct",
        provider_external_id="ext-9",
        canonical_url="https://example.com/p/1",
        content_fingerprint=fp,
    )
    record("dedupe_prefers_external_id", key.startswith("ext:"), key)

    url_key = build_dedupe_key(
        source_type="manual_import",
        provider_account_ref="",
        provider_external_id=None,
        canonical_url="https://example.com/p/1",
        content_fingerprint=fp,
    )
    record("dedupe_falls_back_to_url", url_key.startswith("url:"), url_key)

    # --- Matching ---
    record("boundary_match_hit", find_boundary_match("Acme rocks", "Acme") is not None)
    record("boundary_match_miss", find_boundary_match("Pacemaker", "Acme") is None)

    class _Q:
        def __init__(self) -> None:
            self.id = uuid4()
            self.is_enabled = True
            self.include_terms_json = ["Acme"]
            self.exclude_terms_json = ["spam"]
            self.source_filters_json = None
            self.language_filters_json = None
            self.subject_id = None

    evidence = match_mention_against_queries(
        content_text="Love Acme",
        canonical_url=None,
        author_display=None,
        language="en",
        source_type="manual_import",
        queries=[_Q()],
        subjects_by_id={},
    )
    record("match_evidence_present", len(evidence) == 1)

    # --- Schedule / fixture helpers ---
    record("paused_not_scheduled", projects_eligible_for_scheduled_ingestion("paused") is False)
    record("active_scheduled", projects_eligible_for_scheduled_ingestion("active") is True)
    env = (settings.APP_ENV or "").strip().lower()
    record(
        "fixture_gate_consistent",
        fixture_ingest_allowed() == (env not in {"production", "prod"}),
        f"APP_ENV={settings.APP_ENV!r}",
    )

    # --- Adapter write boundary (structural) ---
    for source_type in ("manual_import", "fixture"):
        adapter = get_adapter(source_type)
        record(
            f"adapter_is_listening_{source_type}",
            isinstance(adapter, ListeningSourceAdapter),
        )
        writes = _write_like_methods(adapter)
        record(f"adapter_no_writes_{source_type}", writes == [], str(writes))
        caps = adapter.capabilities()
        record(
            f"adapter_caps_type_{source_type}",
            isinstance(caps, SourceCapabilities),
        )
        record(
            f"adapter_not_live_{source_type}",
            caps.capability_status != "live",
            caps.capability_status,
        )

    # Base class itself must not declare mutation abstracts.
    base_writes = [
        name
        for name, _ in inspect.getmembers(ListeningSourceAdapter, predicate=inspect.isfunction)
        if any(name.lower().startswith(p) for p in ("publish", "reply", "comment", "react", "message", "follow"))
    ]
    record("base_adapter_no_write_abstracts", base_writes == [], str(base_writes))

    caps_list = list_source_capabilities()
    record("capabilities_nonempty", len(caps_list) >= 2)
    live_caps = [c for c in caps_list if c.capability_status == "live"]
    record(
        "live_capabilities_are_governed_facebook_only",
        {c.source_type for c in live_caps}
        == {"facebook_page_comments", "facebook_page_mentions"},
        str(sorted(c.source_type for c in live_caps)),
    )
    record(
        "live_capabilities_remain_separate",
        any(c.owned_content_comments and not c.direct_account_mentions for c in live_caps)
        and any(c.direct_account_mentions and not c.owned_content_comments for c in live_caps),
    )

    # Package static scan for obvious provider-write symbols.
    listening_root = Path(__file__).resolve().parents[1] / "app" / "services" / "listening"
    bad: list[str] = []
    for path in listening_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for needle in (
            "publish_post",
            "send_reply",
            "create_comment",
            "provider.write",
            "mutate_provider",
        ):
            if needle in text:
                bad.append(f"{path.name}:{needle}")
    record("no_provider_write_symbols", bad == [], str(bad))

    # Review service must not import provider adapters (write boundary).
    # Project service may resolve adapters for capabilities / live source binding
    # but must never call fetch_observations or provider mutation APIs.
    review_src = (listening_root / "review_service.py").read_text(encoding="utf-8")
    project_src = (listening_root / "project_service.py").read_text(encoding="utf-8")
    record(
        "review_service_no_provider_import",
        "providers" not in review_src and "get_adapter" not in review_src,
    )
    record(
        "project_service_no_fetch_observations",
        "fetch_observations" not in project_src
        and "publish_post" not in project_src
        and "create_comment" not in project_src
        and "send_reply" not in project_src,
    )
    if "get_adapter" in project_src:
        record(
            "project_service_adapter_read_only_usage",
            "fetch_observations" not in project_src
            and ".capabilities()" in project_src,
        )
    else:
        record("project_service_adapter_read_only_usage", True)

    # Import payload / rate-limit guards.
    from app.services.listening.errors import ImportValidationError, ListeningRateLimitedError
    from app.services.listening.limits import (
        MAX_IMPORT_PAYLOAD_BYTES,
        enforce_import_payload_bytes,
        enforce_import_rate_limit,
        import_payload_byte_size,
    )

    tiny = [{"content_text": "ok", "provider_external_id": "1"}]
    record("payload_size_positive", import_payload_byte_size(tiny) > 0)
    try:
        enforce_import_payload_bytes(tiny)
        record("payload_small_ok", True)
    except ImportValidationError:
        record("payload_small_ok", False)

    huge = [{"content_text": "x" * (MAX_IMPORT_PAYLOAD_BYTES + 1), "provider_external_id": "huge"}]
    huge_rejected = False
    try:
        enforce_import_payload_bytes(huge)
    except ImportValidationError:
        huge_rejected = True
    record("payload_oversize_rejected", huge_rejected)

    rate_ok = False
    try:
        enforce_import_rate_limit(0)
        rate_ok = True
    except ListeningRateLimitedError:
        rate_ok = False
    record("rate_limit_allows_zero", rate_ok)

    rate_blocked = False
    try:
        from app.services.listening.limits import MAX_IMPORT_REQUESTS_PER_TENANT_PER_HOUR

        enforce_import_rate_limit(MAX_IMPORT_REQUESTS_PER_TENANT_PER_HOUR)
    except ListeningRateLimitedError:
        rate_blocked = True
    record("rate_limit_blocks_at_max", rate_blocked)

    # Manual import strips unknown keys (no credential smuggling into summary).
    import asyncio
    from app.services.listening.providers.manual_import import ManualImportAdapter

    page = asyncio.run(
        ManualImportAdapter().fetch_observations(
            items=[
                {
                    "content_text": "Acme",
                    "provider_external_id": "k1",
                    "access_token": "SECRET",
                    "password": "SECRET",
                }
            ]
        )
    )
    summary_keys = (page.items[0].raw_safe_summary or {}).get("keys") or []
    record(
        "manual_import_strips_secret_keys",
        "access_token" not in summary_keys and "password" not in summary_keys,
        str(summary_keys),
    )

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