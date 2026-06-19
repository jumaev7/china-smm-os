"""Manual validation tests for Buyer CRM schemas and constants."""
from app.models.buyer_crm import BUYER_STATUSES, CENTRAL_ASIA_COUNTRIES, BUYER_ENTITY_TYPES
from app.schemas.buyer_crm import BuyerCreate, BuyerUpdate


def test_status_constants():
    assert "prospect" in BUYER_STATUSES
    assert "active_buyer" in BUYER_STATUSES
    assert len(BUYER_STATUSES) == 6


def test_central_asia_countries():
    assert len(CENTRAL_ASIA_COUNTRIES) == 5
    assert "Uzbekistan" in CENTRAL_ASIA_COUNTRIES
    assert "Turkmenistan" in CENTRAL_ASIA_COUNTRIES


def test_entity_types():
    assert BUYER_ENTITY_TYPES == frozenset({"lead", "deal", "customer", "proposal"})


def test_buyer_create_validation():
    buyer = BuyerCreate(company_name="Test Co", country="Kazakhstan", status="prospect")
    assert buyer.company_name == "Test Co"
    buyer2 = BuyerCreate(
        company_name="Tags Co",
        tags=["Central Asia", "Priority"],
        product_categories=["Steel", "Cement"],
    )
    assert buyer2.tags == ["Central Asia", "Priority"]


def test_buyer_update_partial():
    update = BuyerUpdate(status="negotiating")
    assert update.status == "negotiating"
    assert update.company_name is None


if __name__ == "__main__":
    test_status_constants()
    test_central_asia_countries()
    test_entity_types()
    test_buyer_create_validation()
    test_buyer_update_partial()
    print("All buyer CRM tests passed.")
