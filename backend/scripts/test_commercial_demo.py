"""Smoke tests for Commercial Demo Factory Experience."""
from app.services.commercial_demo_service import CommercialDemoService


def test_list_packages():
    result = CommercialDemoService.list_packages()
    assert len(result.packages) == 3
    ids = {p.id for p in result.packages}
    assert ids == {"haocheng", "toy_manufacturer", "textile_factory"}


def test_get_tour():
    tour = CommercialDemoService.get_tour()
    assert len(tour.steps) == 8
    assert tour.steps[0].id == "factory_profile"
    assert tour.steps[-1].id == "roi_center"


def test_get_product_positioning():
    positioning = CommercialDemoService.get_product_positioning()
    assert len(positioning.differentiators) >= 3
    assert len(positioning.comparisons) == 4
    assert "buyer discovery" in positioning.mission.lower() or "export" in positioning.mission.lower()


if __name__ == "__main__":
    test_list_packages()
    test_get_tour()
    test_get_product_positioning()
    print("All commercial demo smoke tests passed.")
