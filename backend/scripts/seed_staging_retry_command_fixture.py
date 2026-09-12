"""Seed one synthetic pending retry command (staging only).

Uses PublishRetryCommandStagingFixtureBuilder against china_smm_os_staging.
Intended for B2b2-A Docker campaigns via:

  docker compose ... run --rm --entrypoint python \\
    publish-retry-command-worker \\
    scripts/seed_staging_retry_command_fixture.py

Prints one JSON object to stdout. Refuses non-staging databases.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _seed(database_url: str) -> dict:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.services.publish_retry_command_staging_fixture import (
        PublishRetryCommandStagingFixtureBuilder,
    )
    from app.services.publish_retry_command_staging_identity import (
        REQUIRED_DATABASE_NAME,
        RetryCommandStagingIdentityGuard,
    )

    settings.APP_ENV = "staging"
    settings.DATABASE_URL = database_url
    settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND = "fake"
    settings.PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED = True
    settings.TELEGRAM_BOT_TOKEN = ""
    settings.META_APP_SECRET = ""

    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.connect() as conn:
            db_name = (await conn.execute(text("SELECT current_database()"))).scalar_one()
            if db_name != REQUIRED_DATABASE_NAME:
                raise SystemExit(f"refusing non-staging database: {db_name}")

        async with factory() as db:
            ctx = await RetryCommandStagingIdentityGuard.verify(
                db,
                execution_backend="fake",
            )
            fx = await PublishRetryCommandStagingFixtureBuilder(ctx).create(
                db,
                command_status="pending",
                commit=True,
            )
        return {
            "command_id": str(fx.command_id),
            "original_attempt_id": str(fx.original_attempt_id),
            "correlation_id": fx.correlation_id,
            "tenant_id": str(fx.tenant_id),
            "content_id": str(fx.content_id),
            "platform": fx.platform,
        }
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL (defaults to env / settings)",
    )
    args = parser.parse_args(argv)
    url = (
        args.database_url
        or os.environ.get("DATABASE_URL")
        or os.environ.get("PUBLISH_RETRY_STAGING_PG_URL")
    )
    if not url:
        raise SystemExit("DATABASE_URL required")
    payload = asyncio.run(_seed(url))
    print(json.dumps(payload, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
