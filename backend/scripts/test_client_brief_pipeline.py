"""Unit tests for client brief plan normalization (no DB)."""
from app.services.client_brief_service import (
    _heuristic_plan,
    _normalize_plan,
    _normalize_plan_item,
    PLAN_ITEM_COUNT,
)
from app.models.client_brief import ClientBrief
from app.models.client import Client


def _make_brief(**kwargs) -> ClientBrief:
    brief = ClientBrief(
        client_id=kwargs.get("client_id"),
        product_name=kwargs.get("product_name", "Demo Tea"),
        target_market=kwargs.get("target_market", "Uzbekistan"),
        campaign_goal=kwargs.get("campaign_goal", "awareness"),
        language="en",
        desired_platforms=["instagram", "telegram"],
    )
    return brief


def _make_client() -> Client:
    client = Client(company_name="Demo Factory")
    return client


def test_heuristic_plan_has_seven_items():
    brief = _make_brief()
    client = _make_client()
    plan = _heuristic_plan(brief, client)
    assert len(plan["items"]) == PLAN_ITEM_COUNT
    assert plan["plan_status"] == "draft"
    item = plan["items"][0]
    assert item["platform"] in ("instagram", "telegram", "facebook", "tiktok", "linkedin")
    assert item["media_type"] in ("image", "carousel", "reel", "story", "short_video")
    assert all(k in item["captions"] for k in ("ru", "uz", "en", "zh"))
    assert item["hashtags"]
    assert item["cta"]


def test_normalize_plan_pads_to_seven():
    brief = _make_brief()
    raw = {"summary": "Test", "items": [{"theme": "Only one", "goal": "Test goal"}]}
    plan = _normalize_plan(raw, brief, source="ai")
    assert len(plan["items"]) == 7
    assert plan["items"][0]["theme"] == "Only one"


if __name__ == "__main__":
    test_heuristic_plan_has_seven_items()
    test_normalize_plan_pads_to_seven()
    print("All client brief pipeline tests passed.")
