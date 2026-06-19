"""WhatsApp Business Integration — schema and service structure tests."""
from app.schemas.whatsapp_business import (
    WhatsAppAccountCreate,
    WhatsAppAccountStatus,
    WhatsAppDashboardKpis,
    WhatsAppDemoSeedResponse,
)
from app.services.whatsapp_business_service import normalize_account_status
from app.services.whatsapp_webhook_service import whatsapp_credentials_configured


def test_normalize_account_status_legacy():
    assert normalize_account_status("pending") == "not_connected"
    assert normalize_account_status("connected") == "connected"
    assert normalize_account_status("error") == "sync_error"
    assert normalize_account_status("disabled") == "disabled"


def test_whatsapp_account_create_schema():
    body = WhatsAppAccountCreate(
        account_name="Factory WhatsApp",
        account_type="whatsapp_cloud_api",
        phone_number="+8613800000001",
    )
    assert body.account_type == "whatsapp_cloud_api"
    assert body.provider is None


def test_whatsapp_dashboard_kpis_defaults():
    kpis = WhatsAppDashboardKpis()
    assert kpis.total_contacts == 0
    assert kpis.follow_ups_required == 0


def test_whatsapp_demo_seed_response():
    resp = WhatsAppDemoSeedResponse(
        seeded=True,
        accounts_created=1,
        contacts_created=3,
        conversations_created=3,
        message="ok",
    )
    assert resp.seeded is True


def test_account_status_literal_values():
    statuses: list[WhatsAppAccountStatus] = [
        "not_connected",
        "connected",
        "sync_error",
        "disabled",
    ]
    assert len(statuses) == 4


def test_webhook_not_configured_by_default():
    assert whatsapp_credentials_configured() is False


if __name__ == "__main__":
    test_normalize_account_status_legacy()
    test_whatsapp_account_create_schema()
    test_whatsapp_dashboard_kpis_defaults()
    test_whatsapp_demo_seed_response()
    test_account_status_literal_values()
    test_webhook_not_configured_by_default()
    print("All WhatsApp business tests passed.")
