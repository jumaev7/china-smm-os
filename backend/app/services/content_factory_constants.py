"""Shared constants for AI Content Factory pipeline."""
from __future__ import annotations

SUPPORTED_LANGUAGES = ("ru", "uz", "en", "zh")

FACTORY_PLATFORMS = (
    "telegram",
    "facebook",
    "linkedin",
    "instagram",
    "wechat",
    "whatsapp_status",
)

# Manufacturer / exporter content categories
CONTENT_CATEGORIES = (
    "product_announcement",
    "factory_news",
    "production_process",
    "customer_success",
    "promotion",
    "exhibition",
    "educational",
    "export_opportunity",
    "corporate_update",
)

INPUT_TYPES = ("image", "video", "document", "text", "mixed")

REVIEW_STATUSES = (
    "draft",
    "generated",
    "needs_review",
    "approved",
    "scheduled",
    "published",
    "rejected",
)

FACTORY_CONTENT_TYPES = frozenset({
    "reel", "post", "story", "carousel", "article", "telegram", "linkedin",
})

_CATEGORY_LABELS: dict[str, str] = {
    "product_announcement": "Product announcement",
    "factory_news": "Factory news",
    "production_process": "Production process",
    "customer_success": "Customer success story",
    "promotion": "Promotion",
    "exhibition": "Exhibition announcement",
    "educational": "Educational content",
    "export_opportunity": "Export opportunity",
    "corporate_update": "Corporate update",
}

_PLATFORM_FORMAT_HINTS: dict[str, str] = {
    "telegram": "Short paragraphs, optional markdown, ≤4096 chars, link preview friendly",
    "facebook": "Conversational tone, 1-3 short paragraphs, question or CTA at end",
    "linkedin": "Professional B2B tone, industry insight hook, 3-5 sentences",
    "instagram": "Visual-first caption, line breaks, emoji sparingly, hashtags at end",
    "wechat": "Concise Simplified Chinese, formal-export tone, WeChat Moments style",
    "whatsapp_status": "Very short status text ≤700 chars, direct CTA, mobile-first",
}

_TYPE_PLATFORMS: dict[str, list[str]] = {
    "reel": ["instagram", "telegram"],
    "post": ["instagram", "facebook", "wechat"],
    "story": ["instagram", "whatsapp_status"],
    "carousel": ["instagram", "facebook", "linkedin"],
    "article": ["linkedin", "wechat"],
    "telegram": ["telegram"],
    "linkedin": ["linkedin"],
}

_TYPE_ROTATION = ["reel", "post", "story", "carousel", "telegram", "linkedin", "article"]
