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


def _attempt(
    platform: str,
    payload: dict | None = None,
    *,
    external_post_id: str | None = None,
    external_post_url: str | None = None,
    attempt_id=None,
):
    # Match production persistence: mock/test do not store external_post_id
    # unless the caller explicitly supplies a column value.
    resolved_external = external_post_id
    if resolved_external is None and payload is not None:
        if payload.get("mock") is True or payload.get("test") is True:
            resolved_external = None
        else:
            resolved_external = payload.get("platform_post_id")
    return SimpleNamespace(
        id=attempt_id or uuid4(),
        platform=platform,
        response=json.dumps(payload) if payload is not None else None,
        external_post_id=resolved_external,
        external_post_url=external_post_url,
    )


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


async def _run_column_only_and_conflict() -> None:
    content_id = uuid4()
    rows = [
        _attempt(
            "telegram",
            None,
            external_post_id="ext-column-only",
            external_post_url="https://t.me/c/1/1",
        ),
        _attempt(
            "facebook",
            {"success": True, "mock": False, "platform_post_id": "fb-response"},
            external_post_id="fb-column",
        ),
    ]
    found = await PublishService._prior_live_successes(
        _Db(rows),
        content_id,
        ["telegram", "facebook"],
    )
    assert found["telegram"]["platform_post_id"] == "ext-column-only"
    assert found["telegram"]["post_url"] == "https://t.me/c/1/1"
    assert found["telegram"]["deduplicated"] is True
    # F1: conflicting IDs suppress without selecting an authoritative id.
    assert found["facebook"]["identity_conflict"] is True
    assert found["facebook"]["platform_post_id"] is None
    assert found["facebook"]["deduplicated"] is True
    assert found["facebook"]["conflict_durable_external_post_id"] == "fb-column"
    assert found["facebook"]["conflict_response_platform_post_id"] == "fb-response"


def test_prior_live_successes_ignore_mock_and_test_attempts() -> None:
    asyncio.run(_run())


def test_prior_live_successes_recognize_external_post_id_without_response() -> None:
    asyncio.run(_run_column_only_and_conflict())


if __name__ == "__main__":
    test_prior_live_successes_ignore_mock_and_test_attempts()
    test_prior_live_successes_recognize_external_post_id_without_response()
    print("publish retry deduplication regression test passed")
