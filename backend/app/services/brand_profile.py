"""Build brand profile dict from Client model for AI prompts."""
from app.models.client import Client
from app.schemas.client import DEFAULT_PREFERRED_LANGUAGES


def brand_profile_from_client(client: Client) -> dict:
    return {
        "company_name": client.company_name,
        "brand_name": client.brand_name,
        "business_description": client.business_description,
        "products_services": client.products_services,
        "target_audience": client.target_audience,
        "tone_of_voice": client.tone_of_voice or "friendly",
        "preferred_languages": client.preferred_languages or list(DEFAULT_PREFERRED_LANGUAGES),
        "cta_phone": client.cta_phone,
        "cta_telegram": client.cta_telegram,
        "cta_website": client.cta_website,
        "cta_address": client.cta_address,
        "words_to_avoid": client.words_to_avoid,
        "hashtag_preferences": client.hashtag_preferences,
        "logo_url": client.logo_url,
    }
