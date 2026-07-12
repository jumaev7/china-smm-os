"""Publishing truth pass — blocked path + mock publish success verification."""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = os.environ.get("VERIFY_API_BASE", "http://127.0.0.1:8000/api/v1")
MOCK_PLATFORMS = ("instagram", "telegram")
PUBLISH_VERIFY_READY_MARKER = "[PUBLISH_VERIFY_READY]"

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def req(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()
        try:
            payload = json.loads(raw) if raw else {"detail": str(exc)}
        except json.JSONDecodeError:
            payload = {"detail": raw or str(exc)}
        return exc.code, payload


def has_caption(item: dict) -> bool:
    for key in (
        "caption_short_en",
        "caption_long_en",
        "caption_short_ru",
        "caption_long_ru",
        "caption_short_uz",
        "caption_long_uz",
    ):
        if (item.get(key) or "").strip():
            return True
    return False


def has_media(item: dict) -> bool:
    return bool(item.get("media_file_id"))


def pick_publish_verify_ready(items: list[dict]) -> dict | None:
    for item in items:
        notes = item.get("internal_notes") or ""
        if PUBLISH_VERIFY_READY_MARKER in notes:
            return item
    return None


def pick_draft_no_media(items: list[dict]) -> dict | None:
    for item in items:
        if item.get("status") == "draft" and not has_media(item) and not has_caption(item):
            return item
    for item in items:
        if PUBLISH_VERIFY_READY_MARKER not in (item.get("internal_notes") or ""):
            if not has_media(item) and not has_caption(item):
                return item
    return None


def detail_can_publish(payload: dict) -> bool | None:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        if "can_publish" in detail:
            return bool(detail["can_publish"])
    return None


async def _seed_publish_verify_ready() -> dict | None:
    from app.core.database import AsyncSessionLocal
    from app.services.demo_tenant_seed_service import ensure_publish_verify_ready_for_demo_user

    async with AsyncSessionLocal() as db:
        return await ensure_publish_verify_ready_for_demo_user(db)


def seed_publish_verify_ready() -> dict | None:
    return asyncio.run(_seed_publish_verify_ready())


def main() -> int:
    report: dict = {
        "steps": [],
        "platforms": {},
        "telegram_live": {},
        "blocked_path": {},
        "success_mock_path": {},
    }
    failures: list[str] = []

    seed_info = seed_publish_verify_ready()
    report["seed"] = seed_info or {"error": "demo tenant not found"}
    if not seed_info:
        failures.append("failed to seed publish-verify-ready content for demo tenant")
        print("FAIL seed publish-verify-ready")
    else:
        print("OK seed publish-verify-ready content_id=", seed_info["content_id"])

    code, login = req("POST", "/auth/login", {"email": "demo@factory.local", "password": "demo1234"})
    if code != 200:
        code, login = req(
            "POST",
            "/admin-auth/login",
            {"email": "admin@example.com", "password": "ChangeMe_12345!"},
        )
    if code != 200:
        print("FAIL login", code, login)
        return 1
    token = login["access_token"]
    report["auth"] = "admin" if "admin" in str(login.get("token_type", "")).lower() else "tenant"

    code, content = req("GET", "/content?limit=100", token=token)
    if code != 200:
        print("FAIL content_list", code, content)
        return 1
    items = content.get("items") or []

    draft_item = pick_draft_no_media(items)
    blocked_ok = False
    if draft_item:
        draft_id = draft_item["id"]
        report["blocked_path"]["draft_content_id"] = draft_id
        for mode in ("manual_publish", "test_publish"):
            code, safety = req(
                "GET",
                f"/content/{draft_id}/publish-safety?mode={mode}",
                token=token,
            )
            report["steps"].append({
                "step": f"publish_safety_draft_no_media_{mode}",
                "http": code,
                "can_publish": safety.get("can_publish"),
                "blockers": safety.get("blockers"),
            })
            if code != 200:
                failures.append(f"publish_safety draft/no-media {mode} returned {code}")
            elif safety.get("can_publish"):
                failures.append(f"publish_safety draft/no-media {mode} should block")

        code, blocked_pub = req(
            "POST",
            f"/content/{draft_id}/publish",
            {"test": True, "mode": "test_publish", "platforms": ["telegram"]},
            token=token,
        )
        report["steps"].append({
            "step": "test_publish_draft_no_media",
            "http": code,
            "can_publish": detail_can_publish(blocked_pub),
            "detail": blocked_pub.get("detail"),
        })
        if code == 500:
            failures.append("test_publish draft/no-media returned 500")
        elif code not in (400, 422):
            failures.append(f"test_publish draft/no-media expected 400/422 got {code}")
        elif detail_can_publish(blocked_pub) is not False:
            failures.append("test_publish draft/no-media missing can_publish=false")
        else:
            blocked_ok = True
            print("OK blocked path: draft/no-media test_publish blocked cleanly")
    else:
        failures.append("no draft/no-media content item found for blocked-path verification")

    report["blocked_path"]["verified"] = blocked_ok

    ready_item = pick_publish_verify_ready(items)
    if not ready_item and seed_info:
        code, seeded = req("GET", f"/content/{seed_info['content_id']}", token=token)
        if code == 200:
            ready_item = seeded
    if not ready_item:
        failures.append("publish-verify-ready content item not found after seed")
        print("FAIL no publish-verify-ready content")
    else:
        print("OK ready content id=", ready_item["id"])

    item = ready_item or (items[0] if items else None)
    if not item:
        print("FAIL no content items")
        return 1
    item_id = item["id"]
    report["content_id"] = item_id
    report["content_status"] = item.get("status")
    report["content_platforms"] = item.get("platforms")

    safety_results: dict[str, dict] = {}
    for mode in ("manual_publish", "test_publish"):
        code, safety = req("GET", f"/content/{item_id}/publish-safety?mode={mode}", token=token)
        safety_results[mode] = safety
        report["steps"].append({
            "step": f"publish_safety_ready_{mode}",
            "http": code,
            "passed": safety.get("passed"),
            "can_publish": safety.get("can_publish"),
            "blockers": safety.get("blockers"),
            "platform_status": safety.get("platform_status"),
        })
        if code != 200:
            failures.append(f"publish_safety ready {mode} returned {code}")
        elif not safety.get("passed") or not safety.get("can_publish"):
            failures.append(
                f"publish_safety ready {mode} should pass "
                f"(passed={safety.get('passed')} can_publish={safety.get('can_publish')})",
            )
        else:
            print(f"OK publish_safety ready {mode} passed=true can_publish=true")

    report["success_mock_path"]["publish_safety"] = {
        mode: {
            "passed": safety_results[mode].get("passed"),
            "can_publish": safety_results[mode].get("can_publish"),
        }
        for mode in safety_results
    }

    tg_platform_status = (safety_results.get("test_publish") or {}).get("platform_status", {}).get("telegram", {})

    code, accounts = req("GET", "/publishing/accounts", token=token)
    telegram_accounts = []
    if code == 200:
        telegram_accounts = [
            a for a in (accounts.get("items") or [])
            if a.get("platform") == "telegram"
        ]
    tg_mock = any(a.get("status") == "mock" for a in telegram_accounts)
    tg_connected = any(a.get("status") == "connected" for a in telegram_accounts)
    report["telegram_live"] = {
        "mock_account_present": tg_mock,
        "connected_account_present": tg_connected,
        "live_path_eligible": False,
        "skip_reason": None,
    }

    scheduled_for = (datetime.now(timezone.utc) + timedelta(days=7)).replace(
        hour=9, minute=0, second=0, microsecond=0,
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    platforms = list(item.get("platforms") or ["instagram", "telegram"])
    for platform in MOCK_PLATFORMS:
        if platform not in platforms:
            platforms.append(platform)

    code, sched = req(
        "POST",
        "/calendar/schedule",
        {
            "content_item_id": item_id,
            "scheduled_date": scheduled_for[:10],
            "time_slot": "morning",
            "scheduled_for": scheduled_for,
            "platforms": platforms,
        },
        token=token,
    )
    report["steps"].append({"step": "schedule", "http": code, "detail": sched})
    if code not in (200, 201):
        failures.append(f"schedule ready content failed http={code}")
        print("FAIL schedule", code, sched.get("detail"))
    else:
        print("OK schedule")

    code, queue = req("GET", "/publishing/queue", token=token)
    queue_found = any(r.get("id") == item_id for r in queue.get("items") or [])
    report["steps"].append({
        "step": "queue",
        "http": code,
        "total": queue.get("total"),
        "found": queue_found,
    })
    if code != 200:
        failures.append(f"queue returned {code}")
        print("FAIL queue", code)
    elif not queue_found:
        failures.append("ready content not found in publishing queue after schedule")
        print("FAIL queue item not found")
    else:
        print("OK queue total=", queue.get("total"), "found ready item")

    mock_success_count = 0
    for platform in MOCK_PLATFORMS:
        code, pub = req(
            "POST",
            f"/content/{item_id}/publish",
            {"test": True, "mode": "test_publish", "platforms": [platform]},
            token=token,
        )
        results = pub.get("results") or []
        first = results[0] if results else {}
        detail = pub.get("detail") if isinstance(pub.get("detail"), dict) else {}
        entry = {
            "http": code,
            "success": pub.get("all_success") if results else None,
            "mock": first.get("mock"),
            "platform_post_id": first.get("platform_post_id"),
            "account_name": first.get("account_name"),
            "error": first.get("error") or detail.get("message") or pub.get("detail"),
            "blocked": code in (400, 422),
            "can_publish": detail.get("can_publish") if detail else None,
        }
        report["platforms"][platform] = entry

        if code == 500:
            failures.append(f"test_publish {platform} returned 500")
            print(f"FAIL test_publish {platform} http=500")
            continue

        if code != 200:
            failures.append(f"test_publish {platform} expected 200 got {code}: {entry['error']}")
            print(f"FAIL test_publish {platform} http={code}")
            continue

        if first.get("mock") is not True:
            failures.append(f"test_publish {platform} missing mock=true")
            print(f"FAIL test_publish {platform} mock flag missing")
            continue

        if platform == "instagram":
            post_id = str(first.get("platform_post_id") or "")
            if not post_id.startswith("mock-ig-"):
                failures.append(f"instagram post_id not mock-ig-*: {post_id}")
                print(f"FAIL instagram post_id={post_id}")
            else:
                mock_success_count += 1
                print(f"OK test_publish instagram mock=true post_id={post_id}")

        if platform == "telegram":
            account_name = str(first.get("account_name") or "")
            if "mock" not in account_name.lower():
                failures.append(f"telegram account_name does not indicate mock: {account_name}")
                print(f"FAIL telegram account_name={account_name}")
            else:
                mock_success_count += 1
                print(
                    f"OK test_publish telegram mock=true "
                    f"account_name={account_name} post_id={first.get('platform_post_id')}",
                )

            impl = tg_platform_status.get("implementation")
            if first.get("mock") is False:
                report["telegram_live"]["live_path_eligible"] = True
            elif impl != "live":
                report["telegram_live"]["skip_reason"] = (
                    f"telegram implementation={impl} — live path skipped"
                )

    report["success_mock_path"]["mock_publish_count"] = mock_success_count
    report["success_mock_path"]["verified"] = mock_success_count == len(MOCK_PLATFORMS)
    if mock_success_count != len(MOCK_PLATFORMS):
        failures.append(
            f"mock publish success for {mock_success_count}/{len(MOCK_PLATFORMS)} platforms",
        )

    if not tg_connected:
        report["telegram_live"]["skip_reason"] = (
            report["telegram_live"].get("skip_reason")
            or "no connected non-mock Telegram account"
        )

    out_path = __file__.replace("verify_publishing_truth_pass.py", ".verify_publishing_truth_last.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, default=str)
    print("REPORT", out_path)

    if failures:
        print("FAILURES:")
        for f in failures:
            print(" -", f)
        return 1

    print("PASS publishing truth — blocked path + mock success paths verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
