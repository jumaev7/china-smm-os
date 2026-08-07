"""Regression tests for live publish retry deduplication."""

import asyncio
import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.publish_service import PublishService


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarRows(self._rows)


class _Db:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _query):
        return _Result(self._rows)


def _attempt(platform: str, payload: dict):
    return SimpleNamespace(platform=platform, response=json.dumps(payload))


async def _run() -> None:
    rows = [
        _attempt(
            "facebook",
            {"success": True, "mock": False, "platform_post_id": "fb-live-1"},
        ),
        # Older success for the same platform must not replace the newest one.
        _attempt(
            "facebook",
            {"success": True, "mock": False, "platform_post_id": "fb-live-old"},
        ),
        # Mock/test attempts must never suppress a real publish.
        _attempt(
            "instagram",
            {"success": True, "mock": True, "platform_post_id": "ig-mock"},
        ),
        _attempt(
            "telegram",
            {"success": True, "test": True, "platform_post_id": "tg-test"},
        ),
    ]

    found = await PublishService._prior_live_successes(
        _Db(rows),
        uuid4(),
        ["facebook", "instagram", "telegram"],
    )

    assert list(found) == ["facebook"]
    assert found["facebook"]["platform_post_id"] == "fb-live-1"
    assert found["facebook"]["deduplicated"] is True


def test_prior_live_successes_ignore_mock_and_test_attempts() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    test_prior_live_successes_ignore_mock_and_test_attempts()
    print("publish retry deduplication regression test passed")
