"""HTTP verification for Workflow Builder — lifecycle, validation, isolation."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid
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
    timeout: int = 30,
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


def _valid_definition_v1() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "trigger": {"event": "tenant.content.publish_failed"},
        "conditions": {
            "operator": "all",
            "items": [{"id": "c1", "field": "platform", "op": "equals", "value": "instagram"}],
        },
        "steps": [
            {
                "id": "step_1",
                "type": "action",
                "action_type": "create_notification",
                "config": {"title": "Publish failed: {resource_name}", "category": "automation"},
            },
            {
                "id": "step_2",
                "type": "action",
                "action_type": "record_activity",
                "config": {"title": "Workflow logged"},
            },
        ],
        "failure_policy": "stop_on_failure",
    }


def _valid_definition_v2() -> dict[str, Any]:
    defn = _valid_definition_v1()
    defn["steps"] = [
        *defn["steps"],
        {
            "id": "step_3",
            "type": "action",
            "action_type": "record_activity",
            "config": {"title": "Extra step added after publish"},
        },
    ]
    return defn


def main() -> int:
    return asyncio.run(_run())


async def _run() -> int:
    run_id = f"{int(time.time())}{uuid.uuid4().hex[:8]}"
    failures: list[str] = []

    def record(check_id: str, ok: bool, detail: str = "") -> None:
        prefix = "PASS" if ok else "FAIL"
        print(f"{prefix} {check_id}" + (f" -> {detail}" if detail else ""))
        if not ok:
            failures.append(f"{check_id}: {detail}")

    admin_token, bootstrap_detail = await ensure_admin_token(req)
    record("bootstrap_admin", bool(admin_token), bootstrap_detail)
    if not admin_token:
        print("\nWorkflow Builder HTTP verification failed — admin bootstrap unavailable")
        return 1

    email_a = f"wf-http-a-{run_id}@example.com"
    email_b = f"wf-http-b-{run_id}@example.com"
    code, created_a, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Workflow HTTP A {run_id}", "owner_email": email_a, "plan": "trial"},
        token=admin_token,
    )
    code_b, created_b, _ = req(
        "POST",
        "/admin-auth/platform/tenants/create-client",
        {"company_name": f"Workflow HTTP B {run_id}", "owner_email": email_b, "plan": "trial"},
        token=admin_token,
    )
    if code != 201 or code_b != 201 or not isinstance(created_a, dict) or not isinstance(created_b, dict):
        record("bootstrap_tenants", False, f"A={code} B={code_b}")
        return 1
    record("bootstrap_tenants", True, f"run_id={run_id}")

    temp_a = created_a.get("temporary_password")
    temp_b = created_b.get("temporary_password")
    if not temp_a or not temp_b:
        record("bootstrap_temp_passwords", False, "missing temporary_password")
        return 1

    code, login_a, _ = req("POST", "/auth/login", {"email": email_a, "password": temp_a})
    code_b_login, login_b, _ = req("POST", "/auth/login", {"email": email_b, "password": temp_b})
    token_a = login_a.get("access_token") if isinstance(login_a, dict) else None
    token_b = login_b.get("access_token") if isinstance(login_b, dict) else None
    record("tenant_login", code == 200 and bool(token_a), f"HTTP {code}")
    record("tenant_b_login", code_b_login == 200 and bool(token_b), f"HTTP {code_b_login}")
    if not token_a or not token_b:
        return 1

    # ── catalog ──────────────────────────────────────────────────────────
    code, catalog, _ = req("GET", "/workflows/catalog", token=token_a)
    catalog_events = {e.get("event") for e in catalog.get("events", [])} if isinstance(catalog, dict) else set()
    record(
        "catalog",
        code == 200
        and isinstance(catalog, dict)
        and "tenant.content.publish_failed" in catalog_events
        and "create_notification" in (catalog.get("action_types") or []),
        f"HTTP {code} events={len(catalog_events)}",
    )

    # ── create draft ─────────────────────────────────────────────────────
    key = f"wf{run_id}"
    code, created, _ = req(
        "POST",
        "/workflows",
        {"name": f"Verify Workflow {run_id}", "key": key},
        token=token_a,
    )
    workflow_id = created.get("id") if isinstance(created, dict) else None
    record(
        "create_draft",
        code == 200 and isinstance(created, dict) and created.get("status") == "draft" and bool(workflow_id),
        f"HTTP {code}",
    )
    if not workflow_id:
        return 1
    draft_revision = created.get("draft_revision")

    # ── reject invalid publish (empty steps) ────────────────────────────
    code, invalid_publish, _ = req("POST", f"/workflows/{workflow_id}/publish", token=token_a)
    record(
        "reject_invalid_publish",
        code == 400,
        f"HTTP {code} detail={invalid_publish.get('detail') if isinstance(invalid_publish, dict) else invalid_publish}",
    )

    # ── update draft to a valid definition ──────────────────────────────
    code, updated, _ = req(
        "PATCH",
        f"/workflows/{workflow_id}",
        {"draft_revision": draft_revision, "definition": _valid_definition_v1()},
        token=token_a,
    )
    record(
        "update_draft",
        code == 200
        and isinstance(updated, dict)
        and updated.get("draft_validation_status") == "valid"
        and len((updated.get("draft_definition") or {}).get("steps") or []) == 2,
        f"HTTP {code} validation={updated.get('draft_validation_status') if isinstance(updated, dict) else 'n/a'}",
    )
    new_draft_revision = updated.get("draft_revision") if isinstance(updated, dict) else None

    # ── stale draft revision conflict ───────────────────────────────────
    code, stale, _ = req(
        "PATCH",
        f"/workflows/{workflow_id}",
        {"draft_revision": draft_revision, "name": "Stale rename attempt"},
        token=token_a,
    )
    stale_detail = stale.get("detail") if isinstance(stale, dict) else stale
    record(
        "stale_draft_revision_409",
        code == 409 and isinstance(stale_detail, dict) and stale_detail.get("code") == "stale_draft_revision",
        f"HTTP {code} detail={stale_detail}",
    )

    # ── validate ─────────────────────────────────────────────────────────
    code, validated, _ = req("POST", f"/workflows/{workflow_id}/validate", token=token_a)
    record(
        "validate",
        code == 200 and isinstance(validated, dict) and validated.get("valid") is True,
        f"HTTP {code}",
    )

    # ── publish (v1, 2 steps) ───────────────────────────────────────────
    code, published_1, _ = req("POST", f"/workflows/{workflow_id}/publish", token=token_a)
    record(
        "publish",
        code == 200
        and isinstance(published_1, dict)
        and published_1.get("status") == "published"
        and published_1.get("published_version_number") == 1,
        f"HTTP {code} version={published_1.get('published_version_number') if isinstance(published_1, dict) else 'n/a'}",
    )
    published_version_id_1 = published_1.get("published_version_id") if isinstance(published_1, dict) else None
    post_publish_draft_revision = published_1.get("draft_revision") if isinstance(published_1, dict) else None

    # ── edit published workflow — mutates draft only, not active ────────
    code, edited, _ = req(
        "PATCH",
        f"/workflows/{workflow_id}",
        {"draft_revision": post_publish_draft_revision, "definition": _valid_definition_v2()},
        token=token_a,
    )
    edited_draft_steps = len((edited.get("draft_definition") or {}).get("steps") or []) if isinstance(edited, dict) else 0
    edited_active_steps = len((edited.get("active_definition") or {}).get("steps") or []) if isinstance(edited, dict) else 0
    record(
        "edit_published_creates_draft",
        code == 200 and edited_draft_steps == 3 and edited_active_steps == 2,
        f"HTTP {code} draft_steps={edited_draft_steps} active_steps={edited_active_steps}",
    )

    # ── publish again (v2, 3 steps) — proves prior version immutable ───
    code, published_2, _ = req("POST", f"/workflows/{workflow_id}/publish", token=token_a)
    record(
        "publish_again",
        code == 200 and isinstance(published_2, dict) and published_2.get("status") == "published",
        f"HTTP {code} version={published_2.get('published_version_number') if isinstance(published_2, dict) else 'n/a'}",
    )

    code, version_1_detail, _ = req(
        "GET", f"/workflows/{workflow_id}/versions/{published_version_id_1}", token=token_a,
    )
    v1_steps = len((version_1_detail.get("definition") or {}).get("steps") or []) if isinstance(version_1_detail, dict) else -1
    record(
        "publish_immutability",
        code == 200 and v1_steps == 2,
        f"HTTP {code} version1_steps={v1_steps}",
    )

    # ── pause / resume ───────────────────────────────────────────────────
    code, paused, _ = req("POST", f"/workflows/{workflow_id}/pause", token=token_a)
    record(
        "pause",
        code == 200 and isinstance(paused, dict) and paused.get("status") == "paused",
        f"HTTP {code}",
    )
    code, resumed, _ = req("POST", f"/workflows/{workflow_id}/resume", token=token_a)
    record(
        "resume",
        code == 200 and isinstance(resumed, dict) and resumed.get("status") == "published",
        f"HTTP {code}",
    )

    # ── clone ────────────────────────────────────────────────────────────
    code, cloned, _ = req("POST", f"/workflows/{workflow_id}/clone", token=token_a)
    cloned_id = cloned.get("id") if isinstance(cloned, dict) else None
    cloned_steps = len((cloned.get("draft_definition") or {}).get("steps") or []) if isinstance(cloned, dict) else 0
    record(
        "clone",
        code == 200
        and isinstance(cloned, dict)
        and cloned.get("status") == "draft"
        and cloned_id is not None
        and cloned_id != workflow_id
        and cloned_steps == 3,
        f"HTTP {code} cloned_id={'set' if cloned_id else 'missing'} steps={cloned_steps}",
    )

    # ── tenant isolation ─────────────────────────────────────────────────
    code, wrong, _ = req("GET", f"/workflows/{workflow_id}", token=token_b)
    record("tenant_isolation_404", code == 404, f"HTTP {code}")

    # ── evaluate_only test mode ─────────────────────────────────────────
    code, test_match, _ = req(
        "POST",
        f"/workflows/{workflow_id}/test",
        {"mode": "evaluate_only", "synthetic_payload": {"platform": "instagram"}},
        token=token_a,
    )
    record(
        "evaluate_only_test_match",
        code == 200
        and isinstance(test_match, dict)
        and test_match.get("valid") is True
        and test_match.get("matched") is True
        and len(test_match.get("planned_steps") or []) == 3,
        f"HTTP {code} matched={test_match.get('matched') if isinstance(test_match, dict) else 'n/a'}",
    )

    code, test_no_match, _ = req(
        "POST",
        f"/workflows/{workflow_id}/test",
        {"mode": "evaluate_only", "synthetic_payload": {"platform": "facebook"}},
        token=token_a,
    )
    record(
        "evaluate_only_test_no_match",
        code == 200
        and isinstance(test_no_match, dict)
        and test_no_match.get("matched") is False
        and len(test_no_match.get("planned_steps") or []) == 0,
        f"HTTP {code} matched={test_no_match.get('matched') if isinstance(test_no_match, dict) else 'n/a'}",
    )

    # ── wrong tenant on a different endpoint ────────────────────────────
    code, wrong_test, _ = req(
        "POST",
        f"/workflows/{workflow_id}/test",
        {"mode": "evaluate_only", "synthetic_payload": {}},
        token=token_b,
    )
    record("wrong_tenant_test_404", code == 404, f"HTTP {code}")

    print(f"\n{len(failures)} FAILED" if failures else "\nAll Workflow Builder HTTP checks PASSED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
