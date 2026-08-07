"""
Rule-based content classification for Telegram ingestion.
Architecture supports swapping in AI classification later via classify_with_ai().
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

CLASSIFICATION_CATEGORIES = (
    "product",
    "factory",
    "production_process",
    "promotion",
    "customer_review",
    "company_news",
    "exhibition_event",
    "educational_content",
    "other",
)

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "product": (
        "product", "товар", "продукт", "model", "модель", "catalog", "каталог",
        "price", "цена", "sku", "规格", "产品", "mahsulot", "narx",
    ),
    "factory": (
        "factory", "завод", "фабрик", "manufacturing", "производств", "цех",
        "workshop", "厂房", "工厂", "fabrika", "ishlab chiqarish",
    ),
    "production_process": (
        "production", "process", "процесс", "assembly", "сборк", "line",
        "流水线", "工序", "ishlab chiqarish jarayoni", "production line",
    ),
    "promotion": (
        "promo", "promotion", "скидк", "discount", "sale", "акци", "offer",
        "促销", "优惠", "chegirma", "aksiya",
    ),
    "customer_review": (
        "review", "отзыв", "feedback", "testimonial", "客户评价", "评价",
        "mijoz fikri", "reviewed", "⭐️⭐️",
    ),
    "company_news": (
        "news", "новост", "announcement", "объявлен", "company update",
        "新闻", "公告", "yangilik", "kompaniya",
    ),
    "exhibition_event": (
        "exhibition", "expo", "выставк", "fair", "event", "conference",
        "展会", "展览", "ko'rgazma", "tadbir",
    ),
    "educational_content": (
        "tutorial", "how to", "guide", "learn", "education", "обучен",
        "教程", "教育", "o'quv", "qanday qilish",
    ),
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def classify_content(
    *,
    caption: str | None = None,
    internal_notes: str | None = None,
    media_file_type: str | None = None,
    context_ai_category: str | None = None,
) -> dict[str, Any]:
    """
    Rule-based classification. Returns category, confidence, method.
    Ready for AI: call classify_with_ai() when OpenAI is configured.
    """
    combined = " ".join(filter(None, [caption, internal_notes]))
    normalized = _normalize(combined)

    if context_ai_category:
        mapped = _map_context_ai(context_ai_category)
        if mapped:
            return {
                "category": mapped,
                "confidence": 0.75,
                "method": "context_ai",
            }

    if not normalized:
        if media_file_type == "video":
            return {"category": "production_process", "confidence": 0.35, "method": "rule_default"}
        return {"category": "other", "confidence": 0.2, "method": "rule_default"}

    scores: dict[str, int] = {cat: 0 for cat in CLASSIFICATION_CATEGORIES}
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in normalized:
                scores[category] += 1

    best = max(scores, key=scores.get)
    best_score = scores[best]
    if best_score == 0:
        return {"category": "other", "confidence": 0.3, "method": "rule_fallback"}

    total = sum(scores.values()) or 1
    confidence = min(0.95, 0.4 + (best_score / total) * 0.5)
    return {"category": best, "confidence": round(confidence, 2), "method": "rule_keywords"}


def _map_context_ai(category: str) -> str | None:
    mapping = {
        "food": "product",
        "retail": "product",
        "auto_service": "production_process",
        "technology": "educational_content",
        "beauty": "product",
        "construction": "factory",
        "logistics": "company_news",
        "education": "educational_content",
        "healthcare": "product",
        "real_estate": "company_news",
    }
    return mapping.get(category)


async def classify_with_ai(
    *,
    caption: str | None,
    internal_notes: str | None,
    image_description: str | None = None,
    tenant_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Placeholder for AI classification. Returns None when AI is not configured.
    """
    from app.core.config import settings
    if settings.DEMO_MODE or not settings.AI_PLATFORM_ENABLED or not tenant_id:
        return None
    from app.services.ai_platform.generation_service import GenerationService
    from app.services.ai_platform.schemas import TASK_AI_CONTENT_ADAPTATION

    source = "\n".join(
        part.strip() for part in (caption, internal_notes, image_description) if part and part.strip()
    )
    if not source:
        return None
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["category", "confidence"],
        "properties": {
            "category": {"type": "string", "enum": list(CLASSIFICATION_CATEGORIES)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    }
    try:
        response, _, _ = await GenerationService.generate_structured(
            tenant_id=tenant_id,
            task_type=TASK_AI_CONTENT_ADAPTATION,
            model_alias="content_fast",
            system_instructions=(
                "Classify social-media source material. Return JSON only. Do not invent facts. "
                f"Allowed categories: {', '.join(CLASSIFICATION_CATEGORIES)}. "
                "Your JSON must match this schema exactly: "
                + json.dumps(schema, ensure_ascii=False)
            ),
            input_messages=[{"role": "user", "content": json.dumps({"source": source}, ensure_ascii=False)}],
            output_schema=schema,
            temperature=0,
            max_output_tokens=120,
            metadata={"pipeline": "telegram_ingestion_classification"},
            parse_output=False,
        )
        data = response.structured_output or {}
        category = str(data.get("category") or "")
        confidence = float(data.get("confidence", 0))
        if category not in CLASSIFICATION_CATEGORIES or not 0 <= confidence <= 1:
            return None
        return {"category": category, "confidence": round(confidence, 2), "method": "governed_ai"}
    except Exception as exc:
        logger.warning("telegram_ai_classification_fallback error=%s", type(exc).__name__)
        return None
