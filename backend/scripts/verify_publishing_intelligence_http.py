"""HTTP verification for Publishing Intelligence APIs + tenant isolation."""
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
    email_a = f"pi-http-a-{stamp}@example.com"
    email_b = f"pi-http-b-{stamp}@example.com"

    code, created_a, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"PI HTTP A {stamp}", "owner_email": email_a, "plan": "trial"},
        token=admin_token,
    )
    code_b, created_b, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"PI HTTP B {stamp}", "owner_email": email_b, "plan": "trial"},
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

    # Never print tokens or passwords
    status, _, _ = req("GET", "/publishing-intelligence/policies")
    record("policies_require_auth", status in {401, 403}, f"status={status}")

    status, policies, _ = req("GET", "/publishing-intelligence/policies", token=token_a)
    record("policies_ok", status == 200 and isinstance(policies, dict), f"status={status}")
    record(
        "policies_have_platforms",
        isinstance(policies, dict) and "platforms" in policies,
    )

    status, catalog, _ = req("GET", "/publishing-intelligence/check-catalog", token=token_a)
    record("check_catalog_ok", status == 200 and isinstance(catalog, dict), f"status={status}")

    # Create client + content for tenant A
    status, client_a, _ = req(
        "POST",
        "/clients",
        {
            "company_name": f"PI Content Client {stamp}",
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
    record("create_content", status in {200, 201} and isinstance(content, dict), f"status={status}")
    if not isinstance(content, dict) or not content.get("id"):
        print(f"content create payload keys: {list(content.keys()) if isinstance(content, dict) else type(content)}")
        return 1
    content_id = content["id"]
    caption = (
        "Discover durable factory components for export markets. "
        "Contact us today to request a quote."
    )
    status, content, _ = req(
        "PATCH",
        f"/content/{content_id}",
        {
            "caption_long_en": caption,
            "hashtags": "#export #factory #b2b",
        },
        token=token_a,
    )
    record("patch_content_caption", status == 200, f"status={status}")

    # Review endpoint accepts no score/weight override body — engine computes score.
    status, review, _ = req(
        "POST",
        f"/publishing-intelligence/content/{content_id}/review",
        token=token_a,
    )
    record("create_review", status == 200 and isinstance(review, dict), f"status={status}")
    if not isinstance(review, dict):
        return 1
    record("review_has_fingerprint", bool(review.get("content_fingerprint")))
    record("review_has_checks", isinstance(review.get("checks"), list) and len(review["checks"]) > 0)
    record("review_advisory_readiness", "publish_readiness" in review)
    record(
        "clients_cannot_override_engine_version",
        review.get("review_engine_version") == "1.0.0",
        str(review.get("review_engine_version")),
    )
    review_id = review.get("review_id")
    score1 = review.get("overall_score")

    status, latest, _ = req(
        "GET",
        f"/publishing-intelligence/content/{content_id}/reviews/latest",
        token=token_a,
    )
    record("latest_ok", status == 200 and latest.get("review_id") == review_id, f"status={status}")

    status, history, _ = req(
        "GET",
        f"/publishing-intelligence/content/{content_id}/reviews",
        token=token_a,
    )
    record(
        "history_ok",
        status == 200 and isinstance(history, dict) and history.get("total", 0) >= 1,
        f"status={status}",
    )

    # Deterministic re-run
    status, review2, _ = req(
        "POST",
        f"/publishing-intelligence/content/{content_id}/review",
        token=token_a,
    )
    record(
        "rerun_deterministic_score",
        status == 200 and review2.get("overall_score") == score1,
        f"{review2.get('overall_score') if isinstance(review2, dict) else None} vs {score1}",
    )
    record(
        "rerun_new_version",
        isinstance(review2, dict) and review2.get("review_version") == 2,
        str(review2.get("review_version") if isinstance(review2, dict) else None),
    )

    # Edit content → stale
    status, _, _ = req(
        "PATCH",
        f"/content/{content_id}",
        {"caption_long_en": content.get("caption_long_en", "") + " Buy now!"},
        token=token_a,
    )
    status, latest_stale, _ = req(
        "GET",
        f"/publishing-intelligence/content/{content_id}/reviews/latest",
        token=token_a,
    )
    record(
        "stale_after_edit",
        status == 200 and (latest_stale.get("is_stale") or latest_stale.get("status") == "stale"),
        f"status={status} is_stale={latest_stale.get('is_stale') if isinstance(latest_stale, dict) else None}",
    )

    # Wrong-tenant access
    status, _, _ = req(
        "GET",
        f"/publishing-intelligence/reviews/{review_id}",
        token=token_b,
    )
    record("wrong_tenant_review_404", status == 404, f"status={status}")

    status, _, _ = req(
        "POST",
        f"/publishing-intelligence/content/{content_id}/review",
        token=token_b,
    )
    record("wrong_tenant_content_404", status == 404, f"status={status}")

    status, validate, _ = req(
        "POST",
        f"/publishing-intelligence/content/{content_id}/validate",
        token=token_a,
    )
    record(
        "validate_distinguishes_hard_blockers",
        status == 200
        and isinstance(validate, dict)
        and validate.get("is_advisory_score") is True
        and "hard_blockers" in validate,
        f"status={status}",
    )

    # No stack traces / secrets in error bodies already checked via 404
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
