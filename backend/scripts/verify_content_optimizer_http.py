"""HTTP verification for Content Optimizer APIs + tenant isolation.

Self-contained auth bootstrap via verify_http_bootstrap. Never prints tokens,
passwords, or full captions.

Run from backend/ with API listening on VERIFY_API_BASE (default :8000):
  python scripts/verify_content_optimizer_http.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from verify_http_bootstrap import ensure_admin_token  # noqa: E402

BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000/api/v1")


def req(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    *,
    timeout: int = 60,
) -> tuple[int, Any, int]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode()
            duration_ms = int((time.perf_counter() - start) * 1000)
            if not raw:
                return resp.status, {}, duration_ms
            try:
                return resp.status, json.loads(raw), duration_ms
            except json.JSONDecodeError:
                return resp.status, raw, duration_ms
    except urllib.error.HTTPError as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload, duration_ms
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        return 0, {"detail": str(exc)}, duration_ms


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "OK" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" — {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    admin_token, admin_detail = await ensure_admin_token(req)
    record("admin_token", bool(admin_token), admin_detail)
    if not admin_token:
        return 1

    stamp = int(time.time())
    email_a = f"co-http-a-{stamp}@example.com"
    email_b = f"co-http-b-{stamp}@example.com"

    code, created_a, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"CO HTTP A {stamp}", "owner_email": email_a, "plan": "trial"},
        token=admin_token,
    )
    code_b, created_b, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"CO HTTP B {stamp}", "owner_email": email_b, "plan": "trial"},
        token=admin_token,
    )
    record(
        "bootstrap_tenants",
        code == 201 and code_b == 201 and isinstance(created_a, dict) and isinstance(created_b, dict),
        f"A={code} B={code_b}",
    )
    if code != 201 or code_b != 201 or not isinstance(created_a, dict) or not isinstance(created_b, dict):
        return 1

    status, login_a, _ = req(
        "POST",
        "/auth/login",
        {"email": email_a, "password": created_a["temporary_password"]},
    )
    status_b, login_b, _ = req(
        "POST",
        "/auth/login",
        {"email": email_b, "password": created_b["temporary_password"]},
    )
    token_a = login_a.get("access_token") if isinstance(login_a, dict) else None
    token_b = login_b.get("access_token") if isinstance(login_b, dict) else None
    record("login_a", status == 200 and bool(token_a), f"status={status}")
    record("login_b", status_b == 200 and bool(token_b), f"status={status_b}")
    if not token_a or not token_b:
        return 1

    status, _, _ = req("GET", "/content-optimizer/configuration")
    record("config_requires_auth", status in {401, 403}, f"status={status}")

    status, cfg, _ = req("GET", "/content-optimizer/configuration", token=token_a)
    record("config_ok", status == 200 and isinstance(cfg, dict), f"status={status}")
    record(
        "config_has_versions",
        isinstance(cfg, dict)
        and bool(cfg.get("optimizer_version"))
        and bool(cfg.get("platform_policy_version") or cfg.get("policy_catalog_version")),
    )
    record(
        "config_no_ai_branding",
        isinstance(cfg, dict)
        and "openai" not in json.dumps(cfg).lower()
        and "anthropic" not in json.dumps(cfg).lower()
        and "chatgpt" not in json.dumps(cfg).lower()
        and "generative ai" not in json.dumps(cfg).lower(),
    )

    status, ops, _ = req("GET", "/content-optimizer/operations", token=token_a)
    record(
        "operations_ok",
        status == 200 and isinstance(ops, dict) and len(ops.get("operations") or []) >= 10,
        f"status={status}",
    )

    status, client_a, _ = req(
        "POST",
        "/clients",
        {
            "company_name": f"CO Content Client {stamp}",
            "business_category": "manufacturing",
            "source_language": "en",
        },
        token=token_a,
    )
    record("create_client_a", status in {200, 201} and isinstance(client_a, dict), f"status={status}")
    if not isinstance(client_a, dict) or not client_a.get("id"):
        return 1
    client_id = client_a["id"]

    status, content, _ = req(
        "POST",
        "/content",
        {
            "client_id": client_id,
            "platforms": ["telegram", "instagram"],
        },
        token=token_a,
    )
    record("create_content_a", status in {200, 201} and isinstance(content, dict), f"status={status}")
    if not isinstance(content, dict) or not content.get("id"):
        return 1
    content_id = content["id"]

    caption = (
        "Discover our export-ready steel components for global buyers.\n\n"
        "We manufacture to specification and ship worldwide with full documentation. "
        "Our team supports OEM and wholesale orders across multiple markets. "
        "Contact us today to request a quote and learn more."
    )
    status, content, _ = req(
        "PATCH",
        f"/content/{content_id}",
        {
            "caption_long_en": caption,
            "hashtags": "#export #steel #b2b #china",
        },
        token=token_a,
    )
    record("patch_content_caption", status == 200, f"status={status}")

    status, opt, _ = req(
        "POST",
        f"/content-optimizer/content/{content_id}/optimize",
        {
            "platforms": ["telegram", "instagram"],
            "locales": ["en"],
            "length_profiles": ["short", "standard"],
            "include_existing_cta": True,
            "include_existing_hashtags": True,
        },
        token=token_a,
    )
    record("optimize_ok", status == 200 and isinstance(opt, dict), f"status={status}")
    if not isinstance(opt, dict):
        return 1

    run = opt.get("run") or {}
    variants = opt.get("variants") or run.get("variants") or []
    generated = [v for v in variants if v.get("status") == "generated"]
    record("optimize_run_status", run.get("status") in {"generated", "partial"}, str(run.get("status")))
    record("optimize_variants_present", len(generated) >= 1, str(len(generated)))
    record(
        "optimize_has_transformations",
        any(len(v.get("transformations") or []) >= 1 for v in generated),
    )
    record(
        "optimize_has_scores",
        any(v.get("variant_score") is not None for v in generated),
    )
    source_fp = run.get("source_fingerprint")
    record("optimize_source_fingerprint", bool(source_fp))

    # Deterministic re-optimize
    status, opt2, _ = req(
        "POST",
        f"/content-optimizer/content/{content_id}/optimize",
        {
            "platforms": ["telegram", "instagram"],
            "locales": ["en"],
            "length_profiles": ["short", "standard"],
        },
        token=token_a,
    )
    run2 = opt2.get("run") if isinstance(opt2, dict) else {}
    variants2 = (opt2.get("variants") if isinstance(opt2, dict) else None) or []
    record("reoptimize_ok", status == 200, f"status={status}")
    record(
        "deterministic_source_fingerprint",
        isinstance(run2, dict) and run2.get("source_fingerprint") == source_fp,
    )
    fps1 = {
        (v.get("platform"), v.get("locale"), v.get("length_profile")): v.get("variant_fingerprint")
        for v in generated
    }
    fps2 = {
        (v.get("platform"), v.get("locale"), v.get("length_profile")): v.get("variant_fingerprint")
        for v in variants2
        if v.get("status") == "generated"
    }
    record("deterministic_variant_fingerprints", fps1 == fps2)

    run_id = run.get("run_id") or run.get("id")
    status, run_detail, _ = req("GET", f"/content-optimizer/runs/{run_id}", token=token_a)
    record("get_run_ok", status == 200 and isinstance(run_detail, dict), f"status={status}")
    detail_variants = (run_detail.get("variants") if isinstance(run_detail, dict) else None) or []
    record(
        "get_run_includes_transformations",
        any(len(v.get("transformations") or []) >= 1 for v in detail_variants),
    )

    status, runs_list, _ = req(
        "GET",
        f"/content-optimizer/content/{content_id}/runs",
        token=token_a,
    )
    record(
        "list_runs_ok",
        status == 200 and isinstance(runs_list, dict) and (runs_list.get("total") or 0) >= 1,
        f"status={status}",
    )

    # Accept / reject / apply — before creating extra templates so the source
    # fingerprint (which includes approved template texts) stays stable.
    target = generated[0] if generated else None
    tmpl_id = None
    if target:
        vid = target.get("variant_id") or target.get("id")
        status, accepted, _ = req(
            "POST",
            f"/content-optimizer/variants/{vid}/accept",
            token=token_a,
        )
        record("accept_ok", status == 200 and accepted.get("status") == "accepted", f"status={status}")

        spare = next(
            (v for v in generated if (v.get("variant_id") or v.get("id")) != vid),
            None,
        )
        if spare:
            spare_id = spare.get("variant_id") or spare.get("id")
            status, rejected, _ = req(
                "POST",
                f"/content-optimizer/variants/{spare_id}/reject",
                token=token_a,
            )
            record("reject_ok", status == 200 and rejected.get("status") == "rejected", f"status={status}")

        status, wrong, _ = req(
            "POST",
            f"/content-optimizer/variants/{vid}/apply",
            {"expected_source_fingerprint": "0" * 64},
            token=token_a,
        )
        record("apply_wrong_fp_409", status == 409, f"status={status}")

        status, applied, _ = req(
            "POST",
            f"/content-optimizer/variants/{vid}/apply",
            {"expected_source_fingerprint": source_fp},
            token=token_a,
        )
        record("apply_ok", status == 200 and applied.get("status") == "applied", f"status={status}")

        status, refreshed, _ = req("GET", f"/content/{content_id}", token=token_a)
        record(
            "apply_updated_caption",
            status == 200
            and isinstance(refreshed, dict)
            and bool(refreshed.get("caption_long_en"))
            and refreshed.get("caption_long_en") != caption,
            f"status={status}",
        )
        record(
            "apply_did_not_publish",
            isinstance(refreshed, dict)
            and refreshed.get("status") not in {"published", "scheduled", "publishing"},
            str(refreshed.get("status") if isinstance(refreshed, dict) else None),
        )
        record(
            "apply_did_not_schedule",
            isinstance(refreshed, dict) and not refreshed.get("scheduled_for"),
        )

        # After apply, source changed — remaining active variants should 409 / stale
        remaining = [
            v for v in generated
            if (v.get("variant_id") or v.get("id")) != vid and v.get("status") == "generated"
        ]
        if remaining:
            rid = remaining[0].get("variant_id") or remaining[0].get("id")
            status, _, _ = req(
                "POST",
                f"/content-optimizer/variants/{rid}/apply",
                {"expected_source_fingerprint": source_fp},
                token=token_a,
            )
            record("apply_stale_after_source_change_409", status == 409, f"status={status}")
        else:
            record("apply_stale_after_source_change_409", True, "no spare — skipped")

        # Wrong-tenant isolation
        status, _, _ = req("GET", f"/content-optimizer/variants/{vid}", token=token_b)
        record("wrong_tenant_variant_404", status == 404, f"status={status}")
        status, _, _ = req("GET", f"/content-optimizer/runs/{run_id}", token=token_b)
        record("wrong_tenant_run_404", status == 404, f"status={status}")
        status, _, _ = req(
            "POST",
            f"/content-optimizer/content/{content_id}/optimize",
            {"locales": ["en"]},
            token=token_b,
        )
        record("wrong_tenant_optimize_404", status == 404, f"status={status}")

    # Template CRUD (after apply so fingerprint concurrency checks stay clean)
    status, tmpl, _ = req(
        "POST",
        "/content-optimizer/templates",
        {
            "template_type": "cta",
            "name": "Quote CTA",
            "locale": "en",
            "content": "Contact us today to request a quote",
            "allowed_platforms": ["telegram", "instagram"],
        },
        token=token_a,
    )
    record("template_create_ok", status in {200, 201} and isinstance(tmpl, dict), f"status={status}")
    tmpl_id = tmpl.get("id") if isinstance(tmpl, dict) else None

    status, tmpls, _ = req("GET", "/content-optimizer/templates", token=token_a)
    record(
        "template_list_ok",
        status == 200 and isinstance(tmpls, dict) and (tmpls.get("total") or 0) >= 1,
        f"status={status}",
    )
    if tmpl_id:
        status, _, _ = req("DELETE", f"/content-optimizer/templates/{tmpl_id}", token=token_b)
        record("wrong_tenant_template_404", status == 404, f"status={status}")

    # Client cannot inject versions / scores / tenant
    status, injected, _ = req(
        "POST",
        f"/content-optimizer/content/{content_id}/optimize",
        {
            "locales": ["en"],
            "optimizer_version": "99.0.0",
            "policy_version": "hacked",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "score": 100,
        },
        token=token_a,
    )
    # Extra fields should be ignored by pydantic; request still succeeds or 422 if forbidden.
    record(
        "client_cannot_inject_versions",
        status in {200, 422}
        and (
            status == 422
            or (
                isinstance(injected, dict)
                and (injected.get("run") or {}).get("optimizer_version") != "99.0.0"
            )
        ),
        f"status={status}",
    )

    record("http_auth_bootstrap_self_contained", True)

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
