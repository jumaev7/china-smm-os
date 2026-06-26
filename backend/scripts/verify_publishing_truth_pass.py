"""Publishing truth pass — publish-safety, schedule, queue, test publish verification."""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

BASE = "http://127.0.0.1:8000/api/v1"


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


def pick_ready_content(items: list[dict]) -> dict | None:
    for item in items:
        if has_media(item) and has_caption(item):
            return item
    return None


def pick_draft_no_media(items: list[dict]) -> dict | None:
    for item in items:
        if item.get("status") == "draft" and not has_media(item) and not has_caption(item):
            return item
    for item in items:
        if not has_media(item) and not has_caption(item):
            return item
    return None


def detail_can_publish(payload: dict) -> bool | None:
    detail = payload.get("detail")
    if isinstance(detail, dict):
        if "can_publish" in detail:
            return bool(detail["can_publish"])
    return None


def main() -> int:
    report: dict = {"steps": [], "platforms": {}, "telegram_live": {}}
    failures: list[str] = []

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

    code, content = req("GET", "/content?limit=50", token=token)
    if code != 200:
        print("FAIL content_list", code, content)
        return 1
    items = content.get("items") or []

    draft_item = pick_draft_no_media(items)
    if draft_item:
        draft_id = draft_item["id"]
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
            print("OK test_publish draft/no-media blocked cleanly")

    ready_item = pick_ready_content(items)
    item = ready_item or (items[0] if items else None)
    if not item:
        print("FAIL no content items")
        return 1
    item_id = item["id"]
    report["content_id"] = item_id
    report["content_status"] = item.get("status")
    report["content_platforms"] = item.get("platforms")

    code, safety_test = req("GET", f"/content/{item_id}/publish-safety?mode=test_publish", token=token)
    tg_platform_status = (safety_test.get("platform_status") or {}).get("telegram", {})

    for mode in ("manual_publish", "test_publish"):
        code, safety = req("GET", f"/content/{item_id}/publish-safety?mode={mode}", token=token)
        report["steps"].append({
            "step": f"publish_safety_{mode}",
            "http": code,
            "can_publish": safety.get("can_publish"),
            "blockers": safety.get("blockers"),
            "platform_status": safety.get("platform_status"),
        })
        if code != 200:
            failures.append(f"publish_safety {mode} returned {code}")
    if not failures:
        print("OK publish_safety manual + test")

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
    if "instagram" not in platforms:
        platforms.append("instagram")

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
        print("WARN schedule", code, sched.get("detail"))
    else:
        print("OK schedule")

    code, queue = req("GET", "/publishing/queue", token=token)
    report["steps"].append({
        "step": "queue",
        "http": code,
        "total": queue.get("total"),
        "found": any(r.get("id") == item_id for r in queue.get("items") or []),
    })
    if code == 200:
        print("OK queue total=", queue.get("total"))
    else:
        print("WARN queue", code)

    for platform in ("instagram", "telegram"):
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

        if platform == "instagram":
            if code == 200 and first.get("mock") is True:
                post_id = str(first.get("platform_post_id") or "")
                if post_id.startswith("mock-ig-"):
                    print(f"OK test_publish instagram mock post_id={post_id}")
                else:
                    failures.append(f"instagram post_id not mock-ig-*: {post_id}")
            elif code in (400, 422):
                print(f"OK test_publish instagram blocked http={code}")
            else:
                failures.append(f"instagram unexpected http={code} mock={first.get('mock')}")

        if platform == "telegram":
            impl = tg_platform_status.get("implementation")
            if code == 200:
                if first.get("mock") is True:
                    print(f"OK test_publish telegram mock=true post_id={first.get('platform_post_id')}")
                elif first.get("mock") is False:
                    report["telegram_live"]["live_path_eligible"] = True
                    print(f"OK test_publish telegram LIVE post_id={first.get('platform_post_id')}")
                else:
                    failures.append("telegram publish missing mock flag")
            elif code in (400, 422):
                print(f"OK test_publish telegram blocked http={code}")
            else:
                failures.append(f"telegram unexpected http={code}")

            if impl == "live" and not report["telegram_live"]["live_path_eligible"]:
                report["telegram_live"]["skip_reason"] = "live implementation but publish blocked or not run"
            elif impl != "live":
                report["telegram_live"]["skip_reason"] = (
                    f"telegram implementation={impl} — live path skipped"
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
