"""Regression checks for Instagram Business publisher safety and live flow."""
from __future__ import annotations

import asyncio
from io import BytesIO
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings
from app.services import instagram_publisher
from app.services.publish_context import PublishContext


def context(*, status: str = "connected", image_url: str = "https://example.test/image.png") -> PublishContext:
    return PublishContext(
        content_id="content-1",
        client_id="client-1",
        company_name="Test Client",
        platform="instagram",
        caption="Instagram verification",
        hashtags="#china_smm_os_test",
        media_url=image_url,
        media_type="image",
        final_video_url=None,
        account_name="@china_smm_os_test_client",
        account_status=status,
        instagram_business_account_id="17841438685574360",
        page_access_token="test-page-token",
        permissions=["instagram_basic", "instagram_content_publish"],
    )


async def main() -> None:
    original_flag = settings.ENABLE_INSTAGRAM_LIVE_SMOKE
    original_publish = instagram_publisher.publish_instagram_image
    try:
        source = BytesIO()
        Image.new("RGB", (576, 1280), "white").save(source, format="JPEG")
        fitted, changed = instagram_publisher._fit_instagram_image_bytes(source.getvalue())
        with Image.open(BytesIO(fitted)) as fitted_image:
            assert changed is True
            assert 0.8 <= fitted_image.width / fitted_image.height <= 1.91

        mock = await instagram_publisher.publish(context(status="mock"))
        assert mock["success"] is True and mock["mock"] is True
        assert str(mock["platform_post_id"]).startswith("mock-ig-")

        settings.ENABLE_INSTAGRAM_LIVE_SMOKE = False
        blocked = await instagram_publisher.publish(context())
        assert blocked["success"] is False and blocked["blocked"] is True
        assert "disabled" in blocked["error"]

        insecure = await instagram_publisher.publish(
            context(image_url="http://localhost:8000/media/image.png"),
        )
        assert insecure["success"] is False and "HTTPS" in insecure["error"]

        async def fake_publish(**kwargs):
            assert kwargs["instagram_business_account_id"] == "17841438685574360"
            assert kwargs["image_url"].startswith("https://")
            return {
                "platform_post_id": "17890000000000000",
                "post_url": "https://www.instagram.com/p/test-post/",
            }

        instagram_publisher.publish_instagram_image = fake_publish
        settings.ENABLE_INSTAGRAM_LIVE_SMOKE = True
        live = await instagram_publisher.publish(context())
        assert live["success"] is True and live["mock"] is False
        assert live["post_url"] == "https://www.instagram.com/p/test-post/"
        print("OK Instagram publisher mock, safety guard, HTTPS guard, and live flow")
    finally:
        settings.ENABLE_INSTAGRAM_LIVE_SMOKE = original_flag
        instagram_publisher.publish_instagram_image = original_publish


if __name__ == "__main__":
    asyncio.run(main())
