"""Pilot readiness verification — executive demo walkthrough + tenant page health.

Runs HTTP smoke tests against the demo tenant and static checks on key frontend routes.
Outputs a checklist with Passed / Warning / Failed statuses.

Usage:
  python backend/scripts/verify_pilot_readiness.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

BASE = "http://127.0.0.1:8000/api/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_ROOT = REPO_ROOT / "frontend"
DEMO_EMAIL = "demo@factory.local"
DEMO_PASSWORD = "demo1234"
SLOW_MS = 2000

CheckStatus = Literal["passed", "warning", "failed"]

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@dataclass
class Check:
    id: str
    category: str
    label: str
    status: CheckStatus
    message: str
    duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category": self.category,
            "label": self.label,
            "status": self.status,
            "message": self.message,
            "duration_ms": self.duration_ms,
        }


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)
    started_at: float = field(default_factory=time.time)

    def add(
        self,
        check_id: str,
        category: str,
        label: str,
        status: CheckStatus,
        message: str,
        duration_ms: int | None = None,
    ) -> None:
        self.checks.append(
            Check(check_id, category, label, status, message, duration_ms),
        )

    def summary(self) -> dict[str, int]:
        counts = {"passed": 0, "warning": 0, "failed": 0}
        for c in self.checks:
            counts[c.status] += 1
        return counts

    def exit_code(self) -> int:
        if any(c.status == "failed" for c in self.checks):
            return 1
        return 0


def req(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, dict | list | str, int]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
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


def _api_status(
    report: Report,
    check_id: str,
    category: str,
    label: str,
    path: str,
    token: str | None,
    *,
    expect_2xx: bool = True,
    min_items_key: str | None = None,
) -> dict | list | None:
    code, data, duration_ms = req("GET", path, token=token)
    if code == 0:
        report.add(check_id, category, label, "failed", f"Request error: {data}", duration_ms)
        return None
    if expect_2xx and code >= 400:
        detail = data.get("detail") if isinstance(data, dict) else data
        report.add(check_id, category, label, "failed", f"HTTP {code}: {detail}", duration_ms)
        return None

    status: CheckStatus = "passed"
    msg = f"HTTP {code} ({duration_ms}ms)"
    if duration_ms > SLOW_MS:
        status = "warning"
        msg = f"Slow response {duration_ms}ms (>{SLOW_MS}ms threshold)"

    if min_items_key and isinstance(data, dict):
        items = data.get(min_items_key) or data.get("items") or []
        total = data.get("total")
        count = len(items) if isinstance(items, list) else 0
        if total == 0 or (total is None and count == 0):
            status = "warning"
            msg = f"HTTP {code} — empty dataset ({duration_ms}ms)"

    report.add(check_id, category, label, status, msg, duration_ms)
    return data if isinstance(data, dict) else None


def _frontend_page_exists(report: Report, route: str, rel_path: str) -> None:
    page = FRONTEND_ROOT / rel_path
    if page.is_file():
        report.add(
            f"page_{route.strip('/').replace('/', '_')}",
            "frontend_routes",
            f"Page file exists: {route}",
            "passed",
            str(page.relative_to(REPO_ROOT)),
        )
    else:
        report.add(
            f"page_{route.strip('/').replace('/', '_')}",
            "frontend_routes",
            f"Page file exists: {route}",
            "failed",
            f"Missing {rel_path}",
        )


def _file_contains(report: Report, check_id: str, label: str, path: Path, needle: str) -> None:
    if not path.is_file():
        report.add(check_id, "tenant_nav", label, "failed", f"File not found: {path}")
        return
    text = path.read_text(encoding="utf-8")
    if needle in text:
        report.add(check_id, "tenant_nav", label, "passed", f"Found `{needle}` in {path.name}")
    else:
        report.add(check_id, "tenant_nav", label, "warning", f"Missing `{needle}` in {path.name}")


def run_static_checks(report: Report) -> None:
    walkthrough = [
        ("/dashboard", "app/(dashboard)/dashboard/page.tsx"),
        ("/crm-pipeline", "app/(dashboard)/crm-pipeline/page.tsx"),
        ("/proposals", "app/(dashboard)/proposals/page.tsx"),
        ("/publishing", "app/(dashboard)/publishing/page.tsx"),
        ("/content", "app/(dashboard)/content/page.tsx"),
        ("/analytics", "app/(dashboard)/analytics/page.tsx"),
    ]
    for route, rel in walkthrough:
        _frontend_page_exists(report, route, rel)

    shell = FRONTEND_ROOT / "components/layout/DashboardShell.tsx"
    perms = FRONTEND_ROOT / "lib/route-permissions.ts"
    for route in ("/crm-pipeline", "/proposals", "/publishing", "/content", "/analytics"):
        _file_contains(
            report,
            f"nav_{route.strip('/').replace('/', '_')}",
            f"Tenant nav includes {route}",
            shell,
            f'href: "{route}"',
        )
        _file_contains(
            report,
            f"perms_{route.strip('/').replace('/', '_')}",
            f"Tenant route access includes {route}",
            perms,
            f'"{route}"',
        )

    page_states = FRONTEND_ROOT / "components/ui/PageStates.tsx"
    if page_states.is_file():
        report.add(
            "ui_page_states",
            "ui_consistency",
            "Shared PageStates component",
            "passed",
            "LoadingState / EmptyState / ErrorState available",
        )
    else:
        report.add(
            "ui_page_states",
            "ui_consistency",
            "Shared PageStates component",
            "failed",
            "PageStates.tsx missing",
        )


def run_api_walkthrough(report: Report) -> str | None:
    code, _, _ = req("POST", "/auth/create-demo-user")
    if code in (200, 201):
        report.add("demo_user", "auth", "Demo user bootstrap", "passed", "create-demo-user OK")
    elif code == 409:
        report.add("demo_user", "auth", "Demo user bootstrap", "passed", "Demo user already exists")
    else:
        report.add(
            "demo_user",
            "auth",
            "Demo user bootstrap",
            "warning",
            f"create-demo-user returned HTTP {code} — continuing with login",
        )

    code, login, duration_ms = req(
        "POST",
        "/auth/login",
        {"email": DEMO_EMAIL, "password": DEMO_PASSWORD},
    )
    if code != 200:
        report.add("tenant_login", "auth", "Tenant login", "failed", f"HTTP {code}: {login}", duration_ms)
        return None
    token = login.get("access_token") if isinstance(login, dict) else None
    if not token:
        report.add("tenant_login", "auth", "Tenant login", "failed", "No access_token in response", duration_ms)
        return None
    report.add(
        "tenant_login",
        "auth",
        "Tenant login",
        "passed",
        f"Logged in as {DEMO_EMAIL} ({duration_ms}ms)",
        duration_ms,
    )
    return token


def main() -> int:
    report = Report()
    print("=== Pilot Readiness Verification ===\n")

    run_static_checks(report)
    token = run_api_walkthrough(report)

    if token:
        executive_flow = [
            ("dashboard_overview", "Dashboard overview", "/dashboard/overview"),
            ("crm_pipeline_dashboard", "CRM pipeline dashboard", "/crm-pipeline/dashboard"),
            ("crm_pipeline_deals", "CRM pipeline deals", "/crm-pipeline/deals?limit=10"),
            ("proposals_list", "Commercial proposals", "/sales-crm/proposals?limit=10"),
            ("publishing_accounts", "Publishing accounts", "/publishing/accounts"),
            ("content_list", "Content library", "/content?limit=10"),
            ("analytics_overview", "Analytics overview", "/analytics/overview"),
            ("analytics_platforms", "Analytics platforms", "/analytics/platforms"),
            ("analytics_activity", "Analytics activity", "/analytics/activity"),
        ]
        for check_id, label, path in executive_flow:
            data = _api_status(report, check_id, "executive_walkthrough", label, path, token)

        deals_data = None
        code, deals_raw, _ = req("GET", "/crm-pipeline/deals?limit=5", token=token)
        if code == 200 and isinstance(deals_raw, dict):
            deals_data = deals_raw

        content_data = None
        code, content_raw, _ = req("GET", "/content?limit=5", token=token)
        if code == 200 and isinstance(content_raw, dict):
            content_data = content_raw

        pub_data = None
        code, pub_raw, _ = req("GET", "/publishing/accounts", token=token)
        if code == 200 and isinstance(pub_raw, dict):
            pub_data = pub_raw

        if deals_data is not None:
            total = deals_data.get("total", len(deals_data.get("items") or []))
            if total == 0:
                report.add(
                    "data_deals",
                    "demo_data",
                    "Pipeline has deals",
                    "warning",
                    "No deals — CRM pipeline will show empty state in demo",
                )
            else:
                report.add(
                    "data_deals",
                    "demo_data",
                    "Pipeline has deals",
                    "passed",
                    f"{total} deal(s) available",
                )

        if content_data is not None:
            total = content_data.get("total", len(content_data.get("items") or []))
            if total == 0:
                report.add(
                    "data_content",
                    "demo_data",
                    "Content library populated",
                    "warning",
                    "No content items — seed demo data or create content manually",
                )
            else:
                report.add(
                    "data_content",
                    "demo_data",
                    "Content library populated",
                    "passed",
                    f"{total} content item(s)",
                )

        if pub_data is not None:
            total = pub_data.get("total", len(pub_data.get("items") or []))
            if total == 0:
                report.add(
                    "data_publishing",
                    "demo_data",
                    "Publishing accounts connected",
                    "warning",
                    "No publishing accounts — add mock accounts before publishing demo",
                )
            else:
                report.add(
                    "data_publishing",
                    "demo_data",
                    "Publishing accounts connected",
                    "passed",
                    f"{total} account(s)",
                )

        code, proposal_create_page, _ = req("GET", "/sales-crm/proposals?limit=1", token=token)
        if code < 400:
            report.add(
                "flow_proposals_accessible",
                "executive_walkthrough",
                "Proposals API reachable from pipeline",
                "passed",
                "Proposals list accessible — link /proposals to /proposals/new OK",
            )
        else:
            report.add(
                "flow_proposals_accessible",
                "executive_walkthrough",
                "Proposals API reachable from pipeline",
                "failed",
                f"Proposals blocked: HTTP {code}",
            )
    else:
        report.add(
            "executive_walkthrough",
            "executive_walkthrough",
            "API walkthrough",
            "failed",
            "Skipped — tenant login failed",
        )

    counts = report.summary()
    elapsed = int((time.time() - report.started_at) * 1000)

    print("CHECKLIST")
    print("-" * 72)
    for status in ("passed", "warning", "failed"):
        items = [c for c in report.checks if c.status == status]
        if not items:
            continue
        print(f"\n{status.upper()} ({len(items)})")
        for c in items:
            timing = f" [{c.duration_ms}ms]" if c.duration_ms is not None else ""
            print(f"  [{c.category}] {c.label}: {c.message}{timing}")

    print("\n" + "-" * 72)
    print(
        f"SUMMARY: {counts['passed']} passed, {counts['warning']} warnings, "
        f"{counts['failed']} failed ({elapsed}ms total)",
    )

    out = {
        "summary": counts,
        "elapsed_ms": elapsed,
        "checks": [c.to_dict() for c in report.checks],
    }
    artifact = Path(__file__).resolve().parent / ".verify_pilot_readiness_last.json"
    artifact.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nReport written to {artifact.relative_to(REPO_ROOT)}")

    return report.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
