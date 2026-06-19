"""Platform integration validation — schemas and relationship resolver structure."""
from uuid import uuid4

from app.schemas.platform_relationships import (
    ContentLinksUpdate,
    PlatformRelationshipsResponse,
    RelatedEntityItem,
)


def test_related_entity_item():
    item = RelatedEntityItem(
        entity_type="lead",
        entity_id=uuid4(),
        label="Acme Corp",
        href="/leads",
        status="new",
    )
    assert item.entity_type == "lead"
    assert item.label == "Acme Corp"


def test_platform_relationships_response_empty():
    resp = PlatformRelationshipsResponse(
        entity_type="lead",
        entity_id=uuid4(),
    )
    assert resp.related_leads == []
    assert resp.related_buyers == []
    assert resp.related_communications == []


def test_content_links_update_optional_fields():
    body = ContentLinksUpdate(linked_sales_lead_id=uuid4())
    dumped = body.model_dump(exclude_unset=True)
    assert "linked_sales_lead_id" in dumped
    assert "linked_buyer_id" not in dumped


def test_content_links_clear():
    body = ContentLinksUpdate(linked_buyer_id=None)
    assert body.linked_buyer_id is None


if __name__ == "__main__":
    test_related_entity_item()
    test_platform_relationships_response_empty()
    test_content_links_update_optional_fields()
    test_content_links_clear()
    print("All platform integration schema tests passed.")
