"""Verify configured S3/R2 storage without exposing credentials."""

import asyncio
import base64
import urllib.request

from app.core.config import settings
from app.core.storage import storage


PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _fetch(url: str) -> tuple[int, str, bytes]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; ChinaSMMOS-R2-Check/1.0)"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.status, response.headers.get_content_type(), response.read()


async def main() -> None:
    if not settings.USE_S3:
        raise RuntimeError("USE_S3 is disabled")
    if not settings.S3_PUBLIC_BASE_URL.startswith("https://"):
        raise RuntimeError("S3_PUBLIC_BASE_URL must be HTTPS")

    key = await storage.save_file(PNG_1X1, "r2-smoke.png", folder="smoke")
    url = storage.get_url(key)
    try:
        stored = await storage.read_file_bytes(key)
        if stored != PNG_1X1:
            raise RuntimeError("S3 read-back did not match uploaded bytes")
        status, content_type, public_data = await asyncio.to_thread(_fetch, url)
        if status != 200 or content_type != "image/png" or public_data != PNG_1X1:
            raise RuntimeError(
                f"Public read failed: status={status}, type={content_type}, bytes={len(public_data)}"
            )
        print(f"R2 smoke test passed: {url}")
    finally:
        await storage.delete_file(key)


if __name__ == "__main__":
    asyncio.run(main())
