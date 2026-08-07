from pathlib import Path


def test_scheduled_publish_has_no_obsolete_facebook_milestone_blocker():
    source = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "publish_safety_service.py"
    ).read_text(encoding="utf-8")
    scheduled = source.split("async def _evaluate_scheduled_publish", 1)[1]
    scheduled = scheduled.split("async def ", 1)[0]
    assert "Facebook scheduled live publish is not enabled in this milestone" not in scheduled
    assert "_check_platforms_and_accounts" in scheduled
    assert "client_approved" in scheduled
    assert "admin_approved" in scheduled
    assert 'item.status not in ("scheduled", "publishing")' in scheduled
