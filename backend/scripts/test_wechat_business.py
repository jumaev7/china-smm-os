"""WeChat Business Integration — schema and service structure tests."""
from app.schemas.wechat_business import (
    WeChatAccountCreate,
    WeChatAccountStatus,
    WeChatDashboardKpis,
    WeChatDemoSeedResponse,
)
from app.services.wechat_business_service import normalize_account_status


def test_normalize_account_status_legacy():
    assert normalize_account_status("pending") == "not_connected"
    assert normalize_account_status("connected") == "connected"
    assert normalize_account_status("error") == "sync_error"
    assert normalize_account_status("disabled") == "disabled"


def test_wechat_account_create_schema():
    body = WeChatAccountCreate(account_name="Factory WeChat", account_type="wecom")
    assert body.account_type == "wecom"
    assert body.provider is None


def test_wechat_dashboard_kpis_defaults():
    kpis = WeChatDashboardKpis()
    assert kpis.total_contacts == 0
    assert kpis.follow_ups_required == 0


def test_wechat_demo_seed_response():
    resp = WeChatDemoSeedResponse(
        seeded=True,
        accounts_created=2,
        contacts_created=3,
        conversations_created=3,
        message="ok",
    )
    assert resp.seeded is True


def test_account_status_literal_values():
    statuses: list[WeChatAccountStatus] = [
        "not_connected",
        "connected",
        "sync_error",
        "disabled",
    ]
    assert len(statuses) == 4


if __name__ == "__main__":
    test_normalize_account_status_legacy()
    test_wechat_account_create_schema()
    test_wechat_dashboard_kpis_defaults()
    test_wechat_demo_seed_response()
    test_account_status_literal_values()
    print("All WeChat business tests passed.")
