from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.content_review_service import (
    CLIENT_REVIEW_APPROVED,
    should_auto_schedule_after_client_approval,
)


def _item(**overrides):
    values = {
        "client": SimpleNamespace(auto_publish_after_client_approval=True),
        "status": "approved",
        "approved_at": datetime.now(timezone.utc),
        "client_review_status": CLIENT_REVIEW_APPROVED,
        "client_approved_at": datetime.now(timezone.utc),
        "published_at": None,
        "platforms": ["facebook", "instagram"],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_auto_schedule_requires_full_double_approval_and_opt_in():
    assert should_auto_schedule_after_client_approval(_item()) is True


def test_auto_schedule_is_disabled_without_client_opt_in():
    item = _item(client=SimpleNamespace(auto_publish_after_client_approval=False))
    assert should_auto_schedule_after_client_approval(item) is False


def test_auto_schedule_never_bypasses_admin_or_client_approval():
    assert should_auto_schedule_after_client_approval(_item(approved_at=None)) is False
    assert should_auto_schedule_after_client_approval(_item(status="draft")) is False
    assert should_auto_schedule_after_client_approval(_item(client_approved_at=None)) is False
    assert should_auto_schedule_after_client_approval(_item(client_review_status="pending")) is False


def test_auto_schedule_requires_destination_and_unpublished_content():
    assert should_auto_schedule_after_client_approval(_item(platforms=[])) is False
    assert should_auto_schedule_after_client_approval(
        _item(published_at=datetime.now(timezone.utc))
    ) is False
