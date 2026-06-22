"""
Real Telegram → Content ingestion E2E verifier.

Uses real Telegram Bot API file_ids (uploaded via sendPhoto/sendVideo) and posts
group message updates to the local webhook — same code path as production webhooks.

Usage:
  python scripts/verify_real_telegram_ingestion.py --chat-id -5111242647 --client-id <uuid>
  python scripts/verify_real_telegram_ingestion.py --chat-id -5111242647 --client-id <uuid> --skip-ai --skip-schedule

Requires TELEGRAM_BOT_TOKEN in backend/.env and backend running on --api-base (default http://localhost:8000).
"""
from __future__ import annotations

import argparse
import asyncio
import io
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.storage import storage
from app.models.client import Client
from app.models.content import ContentItem
from app.models.media import MediaFile
from app.services.content_service import ContentService

TELEGRAM_API = "https://api.telegram.org"

# Minimal valid 1x1 JPEG
_MIN_JPEG = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
    0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
    0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
    0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
    0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
    0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
    0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
    0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
    0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
    0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
    0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
    0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
    0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
    0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
    0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
    0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
    0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
    0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
    0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
    0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
    0x00, 0x00, 0x3F, 0x00, 0xFB, 0xD5, 0xDB, 0x20, 0xA8, 0xF1, 0x7E, 0xB5,
    0xFF, 0xD9,
])


def _admin_user_id() -> int:
    raw = (settings.TELEGRAM_ADMIN_ID or "").strip().split(",")[0].strip()
    if not raw:
        raise SystemExit("TELEGRAM_ADMIN_ID is not set in backend/.env")
    return int(raw)


async def _upload_photo(token: str, chat_id: int | str) -> tuple[str, int]:
    """Upload JPEG to Telegram; return (file_id, message_id)."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            f"{TELEGRAM_API}/bot{token}/sendPhoto",
            data={"chat_id": str(chat_id)},
            files={"photo": ("e2e_test.jpg", _MIN_JPEG, "image/jpeg")},
        )
        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok"):
            raise RuntimeError(f"sendPhoto failed: {body}")
        result = body["result"]
        photos = result["photo"]
        return photos[-1]["file_id"], int(result["message_id"])


async def _upload_video(token: str, chat_id: int | str) -> tuple[str, int]:
    """Upload a tiny MP4 (ffmpeg on host or in backend Docker container)."""
    import shutil
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
        mp4_path = tmp.name

    ffmpeg_cmd = [
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        mp4_path,
    ]

    try:
        if shutil.which("ffmpeg"):
            subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
        else:
            docker_mp4 = "/tmp/e2e_test_video.mp4"
            subprocess.run(
                [
                    "docker", "exec", "china-smm-os-backend-1",
                    "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    docker_mp4,
                ],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["docker", "cp", f"china-smm-os-backend-1:{docker_mp4}", mp4_path],
                check=True,
                capture_output=True,
            )
        async with httpx.AsyncClient(timeout=120.0) as client:
            with open(mp4_path, "rb") as f:
                resp = await client.post(
                    f"{TELEGRAM_API}/bot{token}/sendVideo",
                    data={"chat_id": str(chat_id)},
                    files={"video": ("e2e_test.mp4", f, "video/mp4")},
                )
            resp.raise_for_status()
            body = resp.json()
            if not body.get("ok"):
                raise RuntimeError(f"sendVideo failed: {body}")
            result = body["result"]
            return result["video"]["file_id"], int(result["message_id"])
    finally:
        Path(mp4_path).unlink(missing_ok=True)


def _build_group_update(
    *,
    chat_id: int,
    chat_title: str,
    message_id: int,
    from_user_id: int,
    from_name: str,
    photo_file_id: str | None = None,
    video_file_id: str | None = None,
    caption: str | None = None,
    update_id: int,
) -> dict:
    message: dict = {
        "message_id": message_id,
        "from": {"id": from_user_id, "is_bot": False, "first_name": from_name},
        "chat": {"id": chat_id, "title": chat_title, "type": "group"},
        "date": int(time.time()),
    }
    if photo_file_id:
        message["photo"] = [
            {"file_id": photo_file_id, "file_unique_id": f"uniq_{message_id}", "width": 1, "height": 1},
        ]
    if video_file_id:
        message["video"] = {
            "file_id": video_file_id,
            "file_unique_id": f"vid_{message_id}",
            "width": 320,
            "height": 240,
            "duration": 1,
            "mime_type": "video/mp4",
        }
    if caption:
        message["caption"] = caption
    return {"update_id": update_id, "message": message}


async def _post_webhook(api_base: str, update: dict) -> dict:
    url = f"{api_base.rstrip('/')}/api/v1/telegram/webhook"
    headers = {}
    secret = (getattr(settings, "TELEGRAM_WEBHOOK_SECRET", None) or "").strip()
    if secret:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json=update, headers=headers)
        resp.raise_for_status()
        return resp.json()


async def _count_content_for_client(client_id: UUID) -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ContentItem).where(
                ContentItem.client_id == client_id,
                ContentItem.source.in_(["telegram", "telegram_group"]),
            )
        )
        return len(list(result.scalars().all()))


async def _latest_telegram_items(client_id: UUID, limit: int = 5) -> list[ContentItem]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ContentItem)
            .where(
                ContentItem.client_id == client_id,
                ContentItem.source.in_(["telegram", "telegram_group"]),
            )
            .order_by(ContentItem.created_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


async def _verify_item(item: ContentItem, client: Client) -> dict:
    async with AsyncSessionLocal() as db:
        item = await db.get(ContentItem, item.id)
        mf = await db.get(MediaFile, item.media_file_id) if item.media_file_id else None
        client_db = await db.get(Client, client.id)
        serialized = ContentService.serialize(item)
        media_url = serialized.get("media_url")
        storage_ok = False
        if mf and mf.storage_path:
            try:
                data = await storage.get_file(mf.storage_path)
                storage_ok = len(data) > 0
            except Exception:
                storage_ok = False
        return {
            "content_id": str(item.id),
            "source": item.source,
            "status": item.status,
            "tenant_id": str(client_db.tenant_id) if client_db and client_db.tenant_id else None,
            "client_id": str(item.client_id),
            "media_type": mf.file_type if mf else None,
            "media_url": media_url,
            "storage_bytes": mf.file_size if mf else 0,
            "storage_ok": storage_ok,
            "caption": item.telegram_original_caption or (item.internal_notes or "")[:80],
            "placeholder_client": (client_db.company_name or "").startswith("Telegram Group:"),
        }


async def _run_ai_generate(api_base: str, content_id: UUID, token: str | None = None) -> dict:
    url = f"{api_base.rstrip('/')}/api/v1/content/{content_id}/generate"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(url, json={"source_language": "zh"}, headers=headers)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "detail": resp.text[:300]}
        data = resp.json()
        has_captions = any(data.get(k) for k in ("caption_short_ru", "caption_long_ru", "caption_short_en"))
        return {"ok": has_captions, "status": resp.status_code, "demo": resp.headers.get("x-demo-mode")}


async def _run_schedule(api_base: str, content_id: UUID, client_id: UUID, token: str | None = None) -> dict:
    from datetime import date, timedelta

    scheduled_date = (date.today() + timedelta(days=1)).isoformat()
    url = f"{api_base.rstrip('/')}/api/v1/calendar/schedule"
    payload = {
        "content_item_id": str(content_id),
        "scheduled_date": scheduled_date,
        "platforms": ["instagram"],
    }
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, json=payload, headers=headers)
        if resp.status_code >= 400:
            return {"ok": False, "status": resp.status_code, "detail": resp.text[:300]}
        return {"ok": True, "status": resp.status_code, "scheduled_date": scheduled_date}


async def _admin_token(api_base: str) -> str | None:
    """Best-effort admin login for protected generate/schedule endpoints."""
    email = (settings.ADMIN_BOOTSTRAP_EMAIL or "").strip()
    password = (settings.ADMIN_BOOTSTRAP_PASSWORD or "").strip()
    if not email or not password:
        return None
    url = f"{api_base.rstrip('/')}/api/v1/admin-auth/login"
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, json={"email": email, "password": password})
        if resp.status_code >= 400:
            return None
        return (resp.json() or {}).get("access_token")


async def run_verification(
    *,
    chat_id: int,
    client_id: UUID,
    chat_title: str,
    api_base: str,
    skip_ai: bool,
    skip_schedule: bool,
) -> int:
    token = (settings.TELEGRAM_BOT_TOKEN or "").strip()
    if not token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set")

    async with AsyncSessionLocal() as db:
        client = await db.get(Client, client_id)
        if not client:
            raise SystemExit(f"Client not found: {client_id}")
        if str(client.telegram_group_id) != str(chat_id):
            print(f"WARNING: client.telegram_group_id={client.telegram_group_id} != chat_id={chat_id}")

    admin_id = _admin_user_id()
    upload_chat = admin_id  # private chat — bot can upload; file_ids work in group webhook

    print(f"API base: {api_base}")
    print(f"Target group: {chat_title} ({chat_id})")
    print(f"Target client: {client_id}")
    print(f"Uploading test media via Telegram API (chat {upload_chat})...")

    photo_file_id, _ = await _upload_photo(token, upload_chat)
    print(f"  photo file_id: {photo_file_id[:40]}...")

    video_file_id: str | None = None
    try:
        video_file_id, _ = await _upload_video(token, upload_chat)
        print(f"  video file_id: {video_file_id[:40]}...")
    except Exception as exc:
        print(f"  video upload skipped: {exc}")

    before = await _count_content_for_client(client_id)
    base_update_id = int(time.time() * 1000)
    cases = [
        ("photo", {"photo_file_id": photo_file_id, "caption": None}),
        ("text+photo", {"photo_file_id": photo_file_id, "caption": "E2E caption: product showcase 产品展示"}),
    ]
    if video_file_id:
        cases.insert(1, ("video", {"video_file_id": video_file_id, "caption": None}))

    results: dict[str, dict] = {}
    for i, (label, kwargs) in enumerate(cases):
        msg_id = base_update_id + i
        update = _build_group_update(
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=msg_id,
            from_user_id=admin_id,
            from_name="E2E Tester",
            photo_file_id=kwargs.get("photo_file_id"),
            video_file_id=kwargs.get("video_file_id"),
            caption=kwargs.get("caption"),
            update_id=base_update_id + i,
        )
        print(f"\nPosting webhook: {label}...")
        try:
            wh = await _post_webhook(api_base, update)
            print(f"  webhook response: {json.dumps(wh)[:200]}")
            results[label] = {"webhook": wh, "ok": bool(wh.get("created") or wh.get("ok"))}
        except Exception as exc:
            print(f"  FAIL: {exc}")
            results[label] = {"ok": False, "error": str(exc)}

    await asyncio.sleep(1)
    after = await _count_content_for_client(client_id)
    new_count = after - before
    print(f"\nContent items for client: {before} -> {after} (+{new_count})")

    items = await _latest_telegram_items(client_id, limit=len(cases) + 2)
    print("\n=== INGESTION VERIFICATION ===")
    failures = 0
    for item in items[:len(cases)]:
        info = await _verify_item(item, client)  # type: ignore[arg-type]
        print(json.dumps(info, indent=2))
        if not info.get("media_url") and info.get("media_type"):
            failures += 1
            print("  FAIL: missing media_url")
        if info.get("placeholder_client"):
            failures += 1
            print("  FAIL: routed to placeholder buffer client")
        if str(info.get("client_id")) != str(client_id):
            failures += 1
            print("  FAIL: wrong client_id")

    preview_ok = all(
        (await _verify_item(it, client))["media_url"] or not (await _verify_item(it, client))["media_type"]  # type: ignore[arg-type]
        for it in items[:len(cases)]
    )
    print(f"\n/content preview (media_url): {'PASS' if preview_ok else 'FAIL'}")

    ai_result: dict = {"skipped": True}
    schedule_result: dict = {"skipped": True}
    admin_token = await _admin_token(api_base)
    if items and not skip_ai:
        ai_result = await _run_ai_generate(api_base, items[0].id, admin_token)
        print(f"\nAI generation: {'PASS' if ai_result.get('ok') else 'FAIL'} — {ai_result}")
        if not ai_result.get("ok"):
            failures += 1
    if items and not skip_schedule:
        schedule_result = await _run_schedule(api_base, items[0].id, client_id, admin_token)
        print(f"Scheduling: {'PASS' if schedule_result.get('ok') else 'FAIL'} — {schedule_result}")
        if not schedule_result.get("ok"):
            failures += 1

    print("\n=== SUMMARY ===")
    for label, _ in cases:
        status = "PASS" if results.get(label, {}).get("ok") else "FAIL"
        print(f"  {label} → content item: {status}")
    print(f"  /content preview: {'PASS' if preview_ok else 'FAIL'}")
    print(f"  AI generation: {'PASS' if ai_result.get('ok') else ('SKIP' if skip_ai else 'FAIL')}")
    print(f"  scheduling: {'PASS' if schedule_result.get('ok') else ('SKIP' if skip_schedule else 'FAIL')}")

    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-id", type=int, required=True)
    parser.add_argument("--client-id", type=str, required=True)
    parser.add_argument("--chat-title", type=str, default="It progress")
    parser.add_argument("--api-base", type=str, default="http://localhost:8000")
    parser.add_argument("--skip-ai", action="store_true")
    parser.add_argument("--skip-schedule", action="store_true")
    args = parser.parse_args()
    failures = asyncio.run(
        run_verification(
            chat_id=args.chat_id,
            client_id=UUID(args.client_id),
            chat_title=args.chat_title,
            api_base=args.api_base,
            skip_ai=args.skip_ai,
            skip_schedule=args.skip_schedule,
        )
    )
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
