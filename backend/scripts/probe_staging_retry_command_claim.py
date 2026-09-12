"""Probe claim_batch against staging DB without intending to own work.

Used by B2b2-A restart observation windows. Prints JSON:
  {probe_worker, results:[{kind, command_id, reason, is_reclaim}]}

Fails hard if the optional --forbid-command-id is claimed/reclaimed.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _probe(database_url: str, forbid_command_id: str | None) -> dict:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.core.config import settings
    from app.services.publish_retry_command_claim_service import (
        PublishRetryCommandClaimService,
    )

    settings.PUBLISH_RETRY_COMMANDS_ENABLED = True
    settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED = True
    settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED = True
    settings.DATABASE_URL = database_url

    probe_id = f"staging-b2b2a-probe:1:{uuid4()}"
    engine = create_async_engine(database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with factory() as db:
            results = await PublishRetryCommandClaimService.claim_batch(
                db,
                worker_id=probe_id,
                commit=True,
            )
        out = []
        for r in results:
            item = {
                "kind": r.kind,
                "command_id": str(r.command_id) if r.command_id else None,
                "reason": r.reason,
                "is_reclaim": bool(r.is_reclaim),
            }
            out.append(item)
            if (
                forbid_command_id
                and item["command_id"] == forbid_command_id
                and item["kind"] in {"claimed", "reclaimed"}
            ):
                raise SystemExit(
                    f"PROBE INVARIANT FAIL: claim_batch returned forbidden "
                    f"command: {item}"
                )
        return {"probe_worker": probe_id, "results": out}
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=None)
    parser.add_argument("--forbid-command-id", default=None)
    args = parser.parse_args(argv)
    url = args.database_url or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL required")
    payload = asyncio.run(_probe(url, args.forbid_command_id))
    print(json.dumps(payload, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
