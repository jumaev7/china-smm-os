"""Prove the Advertising Intelligence domain is strictly read-only.

Three independent proofs, no DB / no HTTP server required:
  1. The provider adapter interface (and every concrete adapter) exposes only
     read/observe methods — no create/update/delete/pause/activate/budget/bid/
     targeting/upload mutation methods anywhere.
  2. The HTTP API surface (``/advertising`` router) exposes no provider-mutating
     routes: the only write routes touch OUR tables (mock account registration
     and internal linkage) — never a provider campaign/ad group/ad/creative.
  3. The capability catalog's ``assert_read_only`` accepts every allowed read
     capability and rejects every forbidden write capability (and unknowns).

Run from backend/:  python scripts/verify_advertising_read_only.py
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


_WRITE_PREFIXES = (
    "create_", "update_", "delete_", "pause", "activate", "resume", "archive",
    "set_budget", "update_budget", "set_bid", "update_bid", "set_status",
    "set_targeting", "update_targeting", "upload_creative", "publish", "boost",
)

# Tokens that, if they appeared in a route path, would imply mutating a provider
# object. (Internal linkage + mock registration are explicitly allowed.)
_FORBIDDEN_ROUTE_TOKENS = (
    "pause", "activate", "resume", "archive", "budget", "bid", "targeting",
    "boost", "publish", "duplicate", "spend-cap", "status",
)


def _write_like_methods(obj) -> list[str]:
    found: list[str] = []
    for name in dir(obj):
        if name.startswith("__"):
            continue
        attr = getattr(obj, name, None)
        if not callable(attr):
            continue
        if any(name.lower().startswith(p) for p in _WRITE_PREFIXES):
            found.append(name)
    return found


def main() -> int:
    failures: list[str] = []

    def record(check: str, ok: bool, detail: str = "") -> None:
        print(("OK" if ok else "FAIL") + f" {check}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check}: {detail}")

    # ================================================================== (1)
    from app.services.advertising_intelligence.providers.base import (
        AdvertisingProviderAdapter,
    )
    from app.services.advertising_intelligence.providers import (
        MetaAdvertisingAdapter,
        MockAdvertisingAdapter,
        UnsupportedAdvertisingAdapter,
        get_adapter,
        registered_providers,
    )
    from app.services.advertising_platform import registry as platform_registry

    _READ_METHODS = {"capabilities", "health_check", "fetch_structure", "fetch_insights", "is_disconnected"}

    # Abstract contract exposes only the read methods.
    abstract = set(getattr(AdvertisingProviderAdapter, "__abstractmethods__", frozenset()))
    record(
        "abstract_methods_are_reads",
        abstract <= {"capabilities", "health_check", "fetch_structure", "fetch_insights"},
        str(sorted(abstract)),
    )

    adapters = [
        ("base", AdvertisingProviderAdapter),
        ("intelligence.mock", MockAdvertisingAdapter()),
        ("intelligence.meta", MetaAdvertisingAdapter()),
        ("intelligence.unsupported", UnsupportedAdvertisingAdapter("tiktok")),
        ("platform.meta", platform_registry.MetaAdvertisingAdapter()),
        ("platform.mock", platform_registry.MockAdvertisingAdapter()),
        ("platform.unsupported", platform_registry.UnsupportedAdvertisingAdapter("x")),
    ]
    for label, adapter in adapters:
        writes = _write_like_methods(adapter)
        record(f"no_write_methods[{label}]", not writes, str(writes))
        # every public callable is within the read method whitelist
        public_callables = {
            n for n in dir(adapter)
            if not n.startswith("_") and callable(getattr(adapter, n, None))
            and (inspect.isfunction(getattr(adapter, n, None))
                 or inspect.ismethod(getattr(adapter, n, None))
                 or inspect.iscoroutinefunction(getattr(adapter, n, None)))
        }
        # class-attr "provider" is a str (not callable); ignore non-method attrs
        extra = public_callables - _READ_METHODS
        record(f"public_callables_read_only[{label}]", not extra, str(sorted(extra)))

    record("registered_providers", registered_providers() == frozenset({"meta", "mock"}),
           str(sorted(registered_providers())))
    record("get_adapter_never_raises_unknown", get_adapter("nope").provider == "nope")

    # ================================================================== (2)
    from app.api.v1.advertising import router

    routes = [r for r in router.routes if hasattr(r, "methods")]
    record("advertising_router_has_routes", len(routes) > 0, str(len(routes)))

    write_routes = []  # (path, methods)
    for r in routes:
        methods = {m for m in (r.methods or set()) if m not in ("HEAD", "OPTIONS")}
        if methods - {"GET"}:
            write_routes.append((r.path, sorted(methods)))

    # All write routes must be one of the explicitly allowed OUR-table writes.
    allowed_write_suffixes = (
        "/accounts/register-mock",
        "/import",
        "/refresh-metrics",
        "/link",
        "/unlink",
        "/link-content",
        "/unlink-content",
    )
    bad_writes = [
        (p, m) for (p, m) in write_routes
        if not any(p.endswith(sfx) for sfx in allowed_write_suffixes)
    ]
    record("all_write_routes_are_allowed", not bad_writes, str(bad_writes))

    forbidden_paths = [
        (r.path, sorted(r.methods or []))
        for r in routes
        if any(tok in r.path.lower() for tok in _FORBIDDEN_ROUTE_TOKENS)
    ]
    record("no_provider_mutation_routes", not forbidden_paths, str(forbidden_paths))

    # Import / refresh are POST but they READ from the provider (ingest locally).
    import_routes = [r.path for r in routes if r.path.endswith("/import") or r.path.endswith("/refresh-metrics")]
    record("import_refresh_present", len(import_routes) >= 2, str(import_routes))

    # ================================================================== (3)
    from app.services.advertising_platform.capability_catalog import (
        ALLOWED_READ_CAPABILITIES,
        FORBIDDEN_WRITE_CAPABILITIES,
        assert_read_only,
        is_forbidden_capability,
        is_read_capability,
    )
    from app.services.advertising_platform.errors import WriteOperationForbiddenError

    record("capabilities_disjoint", not (ALLOWED_READ_CAPABILITIES & FORBIDDEN_WRITE_CAPABILITIES))
    record("allowed_nonempty", len(ALLOWED_READ_CAPABILITIES) >= 8, str(len(ALLOWED_READ_CAPABILITIES)))
    record("forbidden_nonempty", len(FORBIDDEN_WRITE_CAPABILITIES) >= 10, str(len(FORBIDDEN_WRITE_CAPABILITIES)))

    reads_ok = True
    for cap in ALLOWED_READ_CAPABILITIES:
        try:
            assert_read_only(cap)
        except WriteOperationForbiddenError:
            reads_ok = False
        if not is_read_capability(cap):
            reads_ok = False
    record("assert_read_only_accepts_reads", reads_ok)

    writes_rejected = 0
    for cap in FORBIDDEN_WRITE_CAPABILITIES:
        if not is_forbidden_capability(cap):
            continue
        try:
            assert_read_only(cap)
        except WriteOperationForbiddenError:
            writes_rejected += 1
    record(
        "assert_read_only_rejects_writes",
        writes_rejected == len(FORBIDDEN_WRITE_CAPABILITIES),
        f"{writes_rejected}/{len(FORBIDDEN_WRITE_CAPABILITIES)}",
    )

    unknown_rejected = False
    try:
        assert_read_only("frobnicate_campaign")
    except WriteOperationForbiddenError:
        unknown_rejected = True
    record("assert_read_only_rejects_unknown", unknown_rejected)

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
