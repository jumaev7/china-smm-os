"""
Deterministic local dev workflow: sync Telegram webhook to active cloudflared quick tunnel.

Steps:
  1. Validate TELEGRAM_BOT_TOKEN
  2. Check backend /health on localhost:8000
  3. Resolve public URL (--public-url or cloudflared metrics auto-detect)
  4. setWebhook → getWebhookInfo → verify URL match
  5. Probe webhook through tunnel
  6. Print READY for human photo test

Start tunnel first:
  cloudflared tunnel --url http://127.0.0.1:8000

Then sync:
  python scripts/sync_cloudflared_telegram_webhook.py
  python scripts/sync_cloudflared_telegram_webhook.py --public-url https://xxxx.trycloudflare.com
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from setup_telegram_webhook import detect_cloudflared_public_url, sync_webhook


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync Telegram webhook to the current cloudflared quick tunnel URL"
    )
    parser.add_argument(
        "--public-url",
        help="Tunnel base URL (optional; auto-detected from cloudflared metrics on :20241)",
    )
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000", help="Local backend base URL")
    parser.add_argument("--drop-pending", action="store_true", help="Drop pending Telegram updates")
    parser.add_argument("--no-probe", action="store_true", help="Skip public tunnel probe POST")
    args = parser.parse_args()

    public_url = (args.public_url or "").strip()
    if not public_url:
        print("Detecting cloudflared quick tunnel URL (metrics :20241, 3s timeout)...")
        public_url = asyncio.run(detect_cloudflared_public_url()) or ""
        if not public_url:
            raise SystemExit(
                "Could not detect cloudflared URL.\n"
                "  Start: cloudflared tunnel --url http://127.0.0.1:8000\n"
                "  Or pass: --public-url https://xxxx.trycloudflare.com"
            )
        print(f"Detected: {public_url}")

    asyncio.run(
        sync_webhook(
            public_url,
            backend_base=args.backend_url,
            drop_pending=args.drop_pending,
            probe=not args.no_probe,
        )
    )


if __name__ == "__main__":
    main()
