"""
Detect business context from multi-source signals for caption generation.
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from typing import Any

from app.core.config import settings
from app.models.client import Client
from app.services.ai_service import get_openai, _extract_json, _validate_api_key
from app.services.brand_profile import brand_profile_from_client

logger = logging.getLogger(__name__)

# Standard category slugs used in markers and caption prompts
CATEGORY_SLUGS = (
    "food",
    "auto_service",
    "technology",
    "beauty",
    "construction",
    "retail",
    "education",
    "real_estate",
    "logistics",
    "medical",
    "generic_business",
)

_CATEGORY_META: dict[str, dict[str, Any]] = {
    "food": {
        "style": "food promotion",
        "aliases": ("restaurant", "cafe", "food", "kitchen", "dining"),
        "keywords": (
            "burger", "pizza", "food", "restaurant", "coffee", "cafe", "kitchen",
            "menu", "dining", "bakery", "sushi", "bar", "bistro", "meal", "chef",
            "еда", "ресторан", "кафе", "бургер", "пицца", "кухня",
        ),
    },
    "auto_service": {
        "style": "auto service promotion",
        "aliases": ("car repair", "auto repair", "automotive", "garage", "car_service"),
        "keywords": (
            "car repair", "auto service", "automotive", "garage", "mechanic", "brake",
            "wheel", "tire", "tyre", "oil change", "engine", "diagnostic", "alignment",
            "автосервис", "автомастерская", "ремонт авто", "шиномонтаж", "тормоз",
            "колесо", "диск", "подвеска", "сто", "авто",
        ),
    },
    "technology": {
        "style": "technology",
        "aliases": ("tech", "it", "electronics", "computer"),
        "keywords": (
            "laptop", "pc", "computer", "gpu", "phone", "smartphone", "tech", "software",
            "electronics", "monitor", "keyboard", "server", "it service", "gadget",
            "ноутбук", "компьютер", "телефон", "электроника", "программ",
        ),
    },
    "beauty": {
        "style": "beauty",
        "aliases": ("salon", "cosmetics", "spa"),
        "keywords": (
            "beauty", "cosmetic", "salon", "makeup", "skincare", "hair", "nails", "spa",
            "маникюр", "парикмахер", "космет", "салон", "брови", "ресницы",
        ),
    },
    "construction": {
        "style": "construction services",
        "aliases": ("building", "materials", "renovation"),
        "keywords": (
            "construction", "building", "cement", "brick", "renovation", "materials",
            "roof", "plumbing", "tile", "строитель", "ремонт", "стройматериал",
        ),
    },
    "retail": {
        "style": "retail promotion",
        "aliases": ("shop", "store", "ecommerce", "e-commerce"),
        "keywords": (
            "retail", "shop", "store", "ecommerce", "e-commerce", "sale", "discount",
            "магазин", "товар", "ассортимент", "скидка",
        ),
    },
    "education": {
        "style": "education",
        "aliases": ("training", "school", "course"),
        "keywords": (
            "education", "training", "course", "school", "lesson", "tutor", "university",
            "обучение", "курс", "школа", "урок", "тренинг",
        ),
    },
    "real_estate": {
        "style": "real estate",
        "aliases": ("property", "housing", "realtor"),
        "keywords": (
            "real estate", "apartment", "house", "property", "realtor", "rent", "mortgage",
            "недвижимость", "квартира", "дом", "аренда",
        ),
    },
    "logistics": {
        "style": "logistics",
        "aliases": ("delivery", "shipping", "transport"),
        "keywords": (
            "logistics", "delivery", "shipping", "cargo", "freight", "warehouse", "courier",
            "доставка", "грузоперевоз", "логистик", "склад",
        ),
    },
    "medical": {
        "style": "healthcare",
        "aliases": ("healthcare", "clinic", "hospital", "dental"),
        "keywords": (
            "medical", "clinic", "hospital", "doctor", "dental", "healthcare", "pharmacy",
            "клиника", "медиц", "стоматолог", "аптека", "врач",
        ),
    },
    "generic_business": {
        "style": "general promotion",
        "aliases": ("other", "business", "general"),
        "keywords": (),
    },
}

_CONTEXT_MARKER_RE = re.compile(
    r"\[Context AI\]:\s*([\w_]+)\s*\(confidence\s*([\d.]+)\)",
    re.IGNORECASE,
)
_CONTEXT_OVERRIDE_MARKER = "[Context AI override]:"
_CLIENT_CATEGORY_MAP = {
    "restaurant": "food",
    "retail": "retail",
    "beauty": "beauty",
    "construction": "construction",
    "logistics": "logistics",
    "technology": "technology",
    "education": "education",
    "healthcare": "medical",
    "real_estate": "real_estate",
    "other": "generic_business",
}

_SIGNAL_SKIP_PREFIXES = (
    "[Admin instruction]:",
    "[Internal comment]:",
    "[Telegram instruction]:",
    "[Low confidence note]:",
    "[Context AI]:",
    "[Context AI override]:",
    "[OCR]:",
    "[Transcript]:",
    "[Suggested post time]:",
    "[Pending client text]:",
)

_SYSTEM = """\
Detect the business/industry category for ONE social media post from the signals below.

Allowed category slugs (use exactly one):
food, auto_service, technology, beauty, construction, retail, education,
real_estate, logistics, medical, generic_business

Return ONLY JSON:
{
  "category": "slug from list above",
  "style": "writing style for captions",
  "confidence": 0.0 to 1.0,
  "reasoning": "one short sentence"
}

Rules:
- Visual/image analysis and OCR are the STRONGEST signals — trust them over client profile
- Car repair, wheels, brakes, garage, mechanic → auto_service (NOT technology)
- Burger, cafe, kitchen, restaurant food → food
- Laptop, PC, phone, electronics store → technology
- Discount/promo/admin instructions do NOT define industry — ignore them for category
- If signals are weak or mixed, use generic_business with confidence below 0.5
- Never assign technology when visual evidence shows auto repair, food, beauty, etc.
- Prefer brand profile only when visual/text signals are absent or ambiguous
"""


def normalize_category(raw: str | None) -> str:
    slug = (raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    if slug in _CATEGORY_META:
        return slug
    for cat, meta in _CATEGORY_META.items():
        if slug in meta["aliases"] or slug == meta["style"].replace(" ", "_"):
            return cat
    mapped = _CLIENT_CATEGORY_MAP.get(slug)
    if mapped:
        return mapped
    if "auto" in slug or "repair" in slug or "car" in slug:
        return "auto_service"
    if slug in ("tech", "it", "electronics"):
        return "technology"
    if slug in ("health", "healthcare", "clinic"):
        return "medical"
    return "generic_business"


def _extract_ocr(notes: str | None) -> str:
    if not notes:
        return ""
    match = re.search(r"\[OCR\]:\s*(.+?)(?:\n\[|$)", notes, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_transcript(notes: str | None) -> str:
    if not notes:
        return ""
    match = re.search(r"\[Transcript\]:\s*(.+?)(?:\n\[|$)", notes, re.DOTALL)
    return match.group(1).strip() if match else ""


def _extract_image_description(notes: str | None, image_description: str | None) -> str:
    if image_description and image_description.strip():
        return image_description.strip()
    if not notes:
        return ""
    for line in notes.split("\n"):
        stripped = line.strip()
        if stripped.lower().startswith("detected:"):
            return stripped
    return ""


def _human_source(notes: str | None) -> str:
    if not notes:
        return ""
    lines: list[str] = []
    for line in notes.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in _SIGNAL_SKIP_PREFIXES):
            continue
        if stripped.lower().startswith("detected:"):
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def _telegram_instructions_snippet(instructions_json: str | None) -> str:
    if not instructions_json:
        return ""
    try:
        history = json.loads(instructions_json)
    except json.JSONDecodeError:
        return ""
    if not isinstance(history, list):
        return ""
    parts = [
        str(entry.get("instruction", "")).strip()
        for entry in history[-5:]
        if entry.get("instruction")
    ]
    return " | ".join(parts)


def _score_text_blob(blob: str, *, weight: float) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    lower = blob.lower()
    if not lower.strip():
        return scores
    for category, meta in _CATEGORY_META.items():
        if category == "generic_business":
            continue
        hits = sum(1 for kw in meta["keywords"] if kw in lower)
        if hits:
            scores[category] += weight * min(1.0, 0.35 + hits * 0.2)
    return scores


def _heuristic_detect(signals: dict[str, Any]) -> dict[str, Any]:
    scores: dict[str, float] = defaultdict(float)

    visual_desc = signals.get("image_description") or ""
    visual_cat = signals.get("visual_category") or ""
    visual_conf = float(signals.get("visual_confidence") or 0)

    if visual_cat and visual_conf >= 0.55:
        scores[normalize_category(visual_cat)] += visual_conf * 1.2

    for field, weight in (
        ("image_description", 1.0),
        ("ocr_text", 0.85),
        ("human_source", 0.7),
        ("source_text", 0.65),
        ("transcript", 0.5),
        ("hashtags", 0.35),
    ):
        for cat, pts in _score_text_blob(str(signals.get(field) or ""), weight=weight).items():
            scores[cat] += pts

    brand = signals.get("brand_profile") or {}
    brand_blob = " ".join(
        str(brand.get(k) or "")
        for k in ("business_description", "products_services", "target_audience")
    )
    for cat, pts in _score_text_blob(brand_blob, weight=0.45).items():
        scores[cat] += pts

    client_cat = normalize_category(signals.get("client_category") or "other")
    if client_cat != "generic_business":
        scores[client_cat] += 0.25

    if not scores:
        return {
            "category": "generic_business",
            "business": "generic_business",
            "style": _CATEGORY_META["generic_business"]["style"],
            "confidence": 0.35,
            "reasoning": "no strong signals",
        }

    best_cat = max(scores, key=scores.get)
    raw_score = scores[best_cat]
    confidence = min(0.92, max(0.35, raw_score / 1.4))

    if visual_cat and normalize_category(visual_cat) == best_cat and visual_conf >= 0.6:
        confidence = max(confidence, min(0.95, visual_conf + 0.05))

    return {
        "category": best_cat,
        "business": best_cat,
        "style": _CATEGORY_META.get(best_cat, _CATEGORY_META["generic_business"])["style"],
        "confidence": round(confidence, 2),
        "reasoning": "weighted keyword and visual signals",
    }


def _resolve_detection(
    heuristic: dict[str, Any],
    llm: dict[str, Any] | None,
    signals: dict[str, Any],
) -> dict[str, Any]:
    visual_cat = normalize_category(signals.get("visual_category") or "")
    visual_conf = float(signals.get("visual_confidence") or 0)

    candidates: list[tuple[str, float, str]] = [
        (
            normalize_category(heuristic.get("category") or heuristic.get("business")),
            float(heuristic.get("confidence", 0)),
            "heuristic",
        ),
    ]
    if llm:
        candidates.append((
            normalize_category(llm.get("category") or llm.get("business")),
            float(llm.get("confidence", 0)),
            "llm",
        ))
    if visual_cat and visual_conf >= 0.5:
        candidates.append((visual_cat, visual_conf, "visual"))

    # Strong visual evidence wins over conflicting text/client profile
    if visual_cat and visual_conf >= 0.72:
        best = visual_cat
        confidence = visual_conf
        reasoning = f"visual analysis ({visual_cat})"
    else:
        best, confidence, source = max(candidates, key=lambda x: x[1])
        reasoning = llm.get("reasoning") if llm and source == "llm" else heuristic.get("reasoning", source)

        # Visual overrides weak LLM/client guesses (e.g. technology vs auto_service)
        if visual_cat and visual_conf >= 0.58 and visual_cat != best:
            if source == "llm" or confidence < 0.62:
                best = visual_cat
                confidence = max(visual_conf * 0.95, confidence)
                reasoning = f"visual override ({visual_cat})"

    if confidence < 0.5:
        return {
            "category": "generic_business",
            "business": "generic_business",
            "style": _CATEGORY_META["generic_business"]["style"],
            "confidence": round(confidence, 2),
            "reasoning": "low confidence — not forcing category",
        }

    return {
        "category": best,
        "business": best,
        "style": _CATEGORY_META.get(best, _CATEGORY_META["generic_business"])["style"],
        "confidence": round(min(0.98, confidence), 2),
        "reasoning": (reasoning or "")[:200],
    }


def _log_signals_summary(signals: dict[str, Any]) -> None:
    parts = []
    if signals.get("visual_category"):
        parts.append(
            f"visual={signals['visual_category']}@{float(signals.get('visual_confidence') or 0):.2f}"
        )
    if signals.get("image_description"):
        parts.append(f"image_desc={str(signals['image_description'])[:60]}")
    if signals.get("ocr_text"):
        parts.append(f"ocr={str(signals['ocr_text'])[:60]}")
    if signals.get("human_source"):
        parts.append(f"caption={str(signals['human_source'])[:60]}")
    if signals.get("client_category"):
        parts.append(f"client_profile={signals['client_category']}")
    if signals.get("conversation_snippet"):
        parts.append(f"instructions={str(signals['conversation_snippet'])[:60]}")
    logger.info("[Context AI] signals: %s", " | ".join(parts) or "none")


def _build_signals_block(signals: dict[str, Any]) -> str:
    lines = ["SIGNALS:"]
    if signals.get("client_name"):
        lines.append(f"- Client: {signals['client_name']}")
    if signals.get("client_category"):
        lines.append(f"- Client profile category (weak signal): {signals['client_category']}")
    brand = signals.get("brand_profile") or {}
    if brand.get("business_description"):
        lines.append(f"- Business description: {brand['business_description'][:400]}")
    if brand.get("products_services"):
        lines.append(f"- Products/services: {brand['products_services'][:300]}")
    if signals.get("media_file_type"):
        lines.append(f"- Media type: {signals['media_file_type']}")
    if signals.get("visual_category"):
        lines.append(
            f"- Visual analysis: {signals['visual_category']} "
            f"(confidence {float(signals.get('visual_confidence') or 0):.2f})"
        )
    if signals.get("image_description"):
        lines.append(f"- Image description: {signals['image_description'][:400]}")
    if signals.get("human_source"):
        lines.append(f"- Caption/source: {signals['human_source'][:400]}")
    if signals.get("ocr_text"):
        lines.append(f"- OCR: {signals['ocr_text'][:400]}")
    if signals.get("transcript"):
        lines.append(f"- Transcript excerpt: {signals['transcript'][:300]}")
    if signals.get("hashtags"):
        lines.append(f"- Hashtags: {signals['hashtags'][:200]}")
    if signals.get("conversation_snippet"):
        lines.append(f"- Recent admin instructions (do NOT use for industry): {signals['conversation_snippet'][:300]}")
    posts = signals.get("previous_posts") or []
    for i, post in enumerate(posts[:3], 1):
        cap = (post.get("caption_short_ru") or post.get("caption_short_en") or "")[:120]
        tags = (post.get("hashtags") or "")[:80]
        if cap or tags:
            lines.append(f"- Previous post {i}: {cap} {tags}".strip())
    return "\n".join(lines)


async def analyze_image_visual_context(image_bytes: bytes) -> dict[str, Any]:
    """
    Vision-based category detection from image pixels.
    Returns {category, confidence, visual_cues}.
    """
    if not image_bytes:
        return {"category": "", "confidence": 0.0, "visual_cues": ""}

    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        return {"category": "", "confidence": 0.0, "visual_cues": ""}

    try:
        import base64
        from app.services.ocr_service import _resize_for_vision

        jpeg_bytes, mime = _resize_for_vision(image_bytes)
        b64 = base64.b64encode(jpeg_bytes).decode()
        categories = ", ".join(CATEGORY_SLUGS)

        prompt = (
            "Analyze this image for social media content categorization.\n"
            f"Pick ONE category slug from: {categories}\n"
            "Rules:\n"
            "- Car repair shop, wheels, brakes, garage, mechanic tools → auto_service\n"
            "- Burger, cafe, restaurant food, kitchen → food\n"
            "- Laptop, PC, phone, electronics → technology\n"
            "- Salon, makeup, cosmetics → beauty\n"
            "- Do NOT label auto repair as technology\n"
            "Return ONLY JSON: "
            '{"category":"slug","confidence":0.0-1.0,"visual_cues":"brief English cues"}'
        )

        openai = get_openai()
        response = await openai.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content or "{}"
        data = _extract_json(raw)
        category = normalize_category(data.get("category"))
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0))))
        return {
            "category": category,
            "confidence": confidence,
            "visual_cues": (data.get("visual_cues") or "")[:200],
        }
    except Exception as exc:
        logger.warning("[Context AI] visual analysis failed: %s", exc)
        return {"category": "", "confidence": 0.0, "visual_cues": ""}


async def detect_business_context(
    *,
    client: Client,
    source_text: str | None = None,
    internal_notes: str | None = None,
    image_description: str | None = None,
    media_file_type: str | None = None,
    hashtags: str | None = None,
    previous_posts: list[dict] | None = None,
    conversation_snippet: str | None = None,
    image_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Return {category, business, style, confidence, reasoning}."""
    ocr_text = _extract_ocr(internal_notes)
    transcript = _extract_transcript(internal_notes)
    human_source = _human_source(internal_notes)
    image_desc = _extract_image_description(internal_notes, image_description)

    visual_category = ""
    visual_confidence = 0.0
    if image_bytes and media_file_type == "image":
        visual = await analyze_image_visual_context(image_bytes)
        visual_category = visual.get("category") or ""
        visual_confidence = float(visual.get("confidence") or 0)
        if visual.get("visual_cues") and not image_desc:
            image_desc = f"Detected: {visual['visual_cues']}"

    signals = {
        "client_name": client.company_name,
        "client_category": client.business_category,
        "brand_profile": brand_profile_from_client(client),
        "source_text": source_text or "",
        "ocr_text": ocr_text,
        "image_description": image_desc,
        "transcript": transcript,
        "human_source": human_source,
        "media_file_type": media_file_type or "",
        "hashtags": hashtags or "",
        "previous_posts": previous_posts or [],
        "conversation_snippet": conversation_snippet or "",
        "visual_category": visual_category,
        "visual_confidence": visual_confidence,
    }

    _log_signals_summary(signals)
    heuristic = _heuristic_detect(signals)
    llm_result: dict[str, Any] | None = None

    if settings.DEMO_MODE or not (settings.OPENAI_API_KEY or "").strip().startswith("sk-"):
        result = _resolve_detection(heuristic, None, signals)
    else:
        try:
            _validate_api_key()
            openai = get_openai()
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _build_signals_block(signals)},
                ],
                temperature=0.15,
                max_tokens=300,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or "{}"
            parsed = _extract_json(raw)
            category = normalize_category(parsed.get("category") or parsed.get("business"))
            style = (parsed.get("style") or _CATEGORY_META.get(category, {}).get("style", category)).strip()
            confidence = max(0.0, min(1.0, float(parsed.get("confidence", 0.5))))
            llm_result = {
                "category": category,
                "business": category,
                "style": style,
                "confidence": confidence,
                "reasoning": (parsed.get("reasoning") or "")[:200],
            }
        except Exception as exc:
            logger.warning("[Context AI] LLM detection failed (%s) — heuristic only", exc)

        result = _resolve_detection(heuristic, llm_result, signals)

    logger.info("[Context AI] detected: %s", result.get("category"))
    logger.info("[Context AI] confidence: %.2f", float(result.get("confidence", 0)))
    return result


def format_context_marker(context: dict[str, Any]) -> str:
    category = context.get("category") or context.get("business") or "generic_business"
    return (
        f"[Context AI]: {category} "
        f"(confidence {float(context.get('confidence', 0)):.2f})"
    )


def parse_detected_context(notes: str | None) -> dict[str, Any] | None:
    if not notes:
        return None
    match = _CONTEXT_MARKER_RE.search(notes)
    if not match:
        return None
    return {
        "category": normalize_category(match.group(1)),
        "confidence": float(match.group(2)),
    }


def sync_context_override_marker(item) -> None:
    """Keep [Context AI override]: marker in internal_notes in sync with column."""
    notes = item.internal_notes or ""
    lines = [
        ln for ln in notes.split("\n")
        if not ln.strip().startswith(_CONTEXT_OVERRIDE_MARKER)
    ]
    base = "\n".join(lines).strip()
    override = (getattr(item, "context_ai_override", None) or "").strip()
    if override:
        cat = normalize_category(override)
        marker = f"{_CONTEXT_OVERRIDE_MARKER} {cat}"
        item.internal_notes = f"{base}\n{marker}".strip() if base else marker
    else:
        item.internal_notes = base or None


def context_from_override(category: str) -> dict[str, Any]:
    cat = normalize_category(category)
    meta = _CATEGORY_META.get(cat, _CATEGORY_META["generic_business"])
    return {
        "category": cat,
        "business": cat,
        "style": meta["style"],
        "confidence": 1.0,
        "reasoning": "manual override",
        "overridden": True,
    }


async def resolve_business_context_for_generation(
    context_signals: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if not context_signals:
        return None
    override = context_signals.get("context_ai_override")
    if override and str(override).strip():
        result = context_from_override(str(override))
        logger.info("[Context AI] detected: %s (override)", result["category"])
        logger.info("[Context AI] confidence: 1.00")
        return result

    detect_kwargs = {
        k: context_signals[k]
        for k in (
            "client", "source_text", "internal_notes", "image_description",
            "media_file_type", "hashtags", "previous_posts", "conversation_snippet",
            "image_bytes",
        )
        if k in context_signals
    }
    return await detect_business_context(**detect_kwargs)


async def build_context_signals(
    db,
    *,
    client: Client,
    item,
    source_text: str | None = None,
    conversation_snippet: str | None = None,
) -> dict[str, Any]:
    """Collect signals for detect_business_context from a content item."""
    from sqlalchemy import select
    from app.core.storage import storage
    from app.models.content import ContentItem

    prev_result = await db.execute(
        select(ContentItem)
        .where(
            ContentItem.client_id == client.id,
            ContentItem.id != item.id,
        )
        .order_by(ContentItem.created_at.desc())
        .limit(3)
    )
    previous_posts = [
        {
            "caption_short_ru": p.caption_short_ru,
            "caption_short_en": p.caption_short_en,
            "hashtags": p.hashtags,
        }
        for p in prev_result.scalars()
        if p.caption_short_ru or p.caption_short_en or p.hashtags
    ]

    media_type = None
    image_bytes: bytes | None = None
    if getattr(item, "media_file", None):
        media_type = item.media_file.file_type
        if media_type == "image" and item.media_file.storage_path:
            try:
                if storage.exists(item.media_file.storage_path):
                    image_bytes = await storage.read_file_bytes(item.media_file.storage_path)
            except Exception as exc:
                logger.warning("[Context AI] could not load image for analysis: %s", exc)

    instructions_snippet = conversation_snippet or _telegram_instructions_snippet(
        getattr(item, "telegram_instructions", None)
    )

    return {
        "client": client,
        "source_text": source_text,
        "internal_notes": item.internal_notes,
        "media_file_type": media_type,
        "hashtags": item.hashtags,
        "previous_posts": previous_posts,
        "conversation_snippet": instructions_snippet,
        "image_bytes": image_bytes,
        "context_ai_override": getattr(item, "context_ai_override", None),
    }
