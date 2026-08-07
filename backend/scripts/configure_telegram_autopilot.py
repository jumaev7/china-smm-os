"""Configure the single-review Telegram ingestion autopilot for a tenant group."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import AsyncSessionLocal
from app.services.telegram_ingestion_service import TelegramIngestionService


async def configure(*, chat_id: str, tenant_id: UUID) -> None:
    async with AsyncSessionLocal() as db:
        row = await TelegramIngestionService.update_settings(db, {
            "enabled": True,
            "allowed_group_ids": [chat_id],
            "default_tenant_id": tenant_id,
            "default_status": "needs_review",
            "default_target_languages": ["ru", "uz", "en"],
            "auto_classification": True,
            "auto_enrichment": True,
            "quality_checks_enabled": True,
        })
        result = TelegramIngestionService.settings_to_dict(row)
        print({
            "enabled": result["enabled"],
            "allowed_group_ids": result["allowed_group_ids"],
            "default_tenant_id": result["default_tenant_id"],
            "default_status": result["default_status"],
            "auto_classification": result["auto_classification"],
            "auto_enrichment": result["auto_enrichment"],
            "quality_checks_enabled": result["quality_checks_enabled"],
        })


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-id", required=True)
    parser.add_argument("--tenant-id", type=UUID, required=True)
    args = parser.parse_args()
    asyncio.run(configure(chat_id=args.chat_id.strip(), tenant_id=args.tenant_id))


if __name__ == "__main__":
    main()
