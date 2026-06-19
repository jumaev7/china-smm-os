"""
AI Content Generation Service
Generates multilingual social media captions (RU / UZ / EN) for Chinese businesses in Uzbekistan.
"""
import json
import re
from openai import AsyncOpenAI
from app.core.config import settings
from app.schemas.content import GeneratedContent


_client: AsyncOpenAI | None = None


def get_openai() -> AsyncOpenAI:
    global _client
    if _client is None:
        # 60-second timeout: enough for a full GPT-4o response, short enough to fail fast
        _client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=60.0)
    return _client


def _validate_api_key() -> None:
    key = settings.OPENAI_API_KEY or ""
    if not key or key.startswith("sk-your") or key == "your-key-here":
        raise ValueError(
            "OpenAI API key is not configured. "
            "Set OPENAI_API_KEY in backend/.env and restart the backend."
        )


# Language display names for the prompt
LANG_NAMES = {
    "zh": "Chinese (Simplified)",
    "en": "English",
    "ru": "Russian",
    "uz": "Uzbek",
    "ko": "Korean",
    "ja": "Japanese",
}

STYLE_DESC = {
    "professional":  "formal, trustworthy, corporate — suitable for B2B or premium services",
    "casual":        "friendly, warm, conversational — like talking to a neighbor",
    "luxury":        "elegant, premium, aspirational — evokes exclusivity and quality",
    "educational":   "informative, clear, helpful — teaches something valuable",
    "promotional":   "exciting, urgent, action-oriented — drives clicks and conversions",
}

TONE_DESC = {
    "formal":     "professional, respectful, polished — suitable for corporate audiences",
    "friendly":   "warm, approachable, conversational — like talking to a trusted friend",
    "premium":    "elegant, aspirational, high-end — evokes quality and exclusivity",
    "energetic":  "dynamic, upbeat, motivating — creates excitement and momentum",
    "technical":  "precise, expert, informative — highlights specs and reliability",
}

OUTPUT_LANG_LABELS = {
    "ru": "Russian",
    "uz": "Uzbek (Latin script)",
    "en": "English",
    "cn": "Simplified Chinese",
}

SYSTEM_PROMPT = """\
You are a professional social media content writer specializing in Chinese businesses operating in Uzbekistan.

Your expertise:
- Deep knowledge of Uzbekistan's market, culture, and consumer psychology
- Understanding of Chinese business values (quality, trust, long-term relationships)
- Native-level fluency in Russian, Uzbek, and English for the Uzbek market
- Ability to translate and adapt Chinese source content naturally (not literally)
- Social media best practices for Instagram, Facebook, TikTok, Telegram, LinkedIn

Rules:
- Russian and Uzbek captions must feel natural to local audiences, not translated
- Never transliterate Chinese brand names — adapt them naturally
- Short captions (≤150 chars) must be punchy and standalone
- Long captions (200-400 chars) tell a story and include a call-to-action
- Hashtags: mix Uzbek, Russian, and niche English tags — 10 to 15 total
- ALWAYS respond with ONLY valid JSON — no markdown, no preamble, no explanation
"""


def _build_brand_block(brand: dict | None) -> str:
    if not brand:
        return ""

    lines: list[str] = ["\nBRAND PROFILE:"]
    brand_name = (brand.get("brand_name") or brand.get("company_name") or "").strip()
    if brand_name:
        lines.append(f"- Brand name: {brand_name}")
    if brand.get("business_description"):
        lines.append(f"- Business: {brand['business_description'].strip()}")
    if brand.get("products_services"):
        lines.append(f"- Products/services: {brand['products_services'].strip()}")
    if brand.get("target_audience"):
        lines.append(f"- Target audience: {brand['target_audience'].strip()}")

    tone = brand.get("tone_of_voice") or "friendly"
    lines.append(f"- Tone of voice: {tone} — {TONE_DESC.get(tone, tone)}")

    preferred = brand.get("preferred_languages") or ["ru", "uz", "en"]
    if preferred:
        labels = [OUTPUT_LANG_LABELS.get(code, code.upper()) for code in preferred]
        lines.append(f"- Preferred output languages: {', '.join(labels)}")

    cta_parts = []
    if brand.get("cta_phone"):
        cta_parts.append(f"Phone: {brand['cta_phone'].strip()}")
    if brand.get("cta_telegram"):
        cta_parts.append(f"Telegram: {brand['cta_telegram'].strip()}")
    if brand.get("cta_website"):
        cta_parts.append(f"Website: {brand['cta_website'].strip()}")
    if brand.get("cta_address"):
        cta_parts.append(f"Address: {brand['cta_address'].strip()}")
    if cta_parts:
        lines.append(f"- Call-to-action details: {' | '.join(cta_parts)}")

    if brand.get("words_to_avoid"):
        lines.append(f"- Words/phrases to AVOID: {brand['words_to_avoid'].strip()}")
    if brand.get("hashtag_preferences"):
        lines.append(f"- Hashtag preferences: {brand['hashtag_preferences'].strip()}")

    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _build_prompt(
    company_name: str,
    business_category: str,
    content_style: str,
    source_language: str,
    source_text: str | None,
    context_hint: str | None,
    client_notes: str | None = None,
    brand_profile: dict | None = None,
    business_context: dict | None = None,
    knowledge_base_block: str | None = None,
) -> str:
    lang_display = LANG_NAMES.get(source_language, source_language)

    notes_block = ""
    if client_notes and client_notes.strip():
        notes_block = f"\nBRAND NOTES: {client_notes.strip()}"

    brand_block = _build_brand_block(brand_profile)
    preferred = (brand_profile or {}).get("preferred_languages") or ["ru", "uz", "en"]
    preferred_set = {code.lower() for code in preferred}
    lang_instruction = (
        "Generate captions in ALL of: Russian, Uzbek (Latin), and English."
        if preferred_set >= {"ru", "uz", "en"}
        else f"Prioritize captions for: {', '.join(OUTPUT_LANG_LABELS.get(c, c.upper()) for c in preferred)}."
    )
    if "cn" in preferred_set:
        lang_instruction += " Include Simplified Chinese where relevant."

    source_block = ""
    if source_text and source_text.strip():
        source_block = f"""

CLIENT'S SOURCE TEXT ({lang_display}):
\"\"\"
{source_text.strip()}
\"\"\"

Translate, adapt, and expand this text for social media. Do NOT translate literally — \
make it feel natural and engaging for the Uzbek market."""

    context_block = ""
    if context_hint and context_hint.strip():
        context_block = f"\n\nEXTRA CONTEXT: {context_hint.strip()}"

    tone = (brand_profile or {}).get("tone_of_voice") or content_style
    tone_display = TONE_DESC.get(tone, STYLE_DESC.get(content_style, content_style))

    context_ai_block = ""
    if business_context and float(business_context.get("confidence", 0)) >= 0.5:
        conf = float(business_context["confidence"])
        category = business_context.get("category") or business_context.get("business", business_category)
        style = business_context.get("style", content_style)
        override_note = " (manual override)" if business_context.get("overridden") else ""
        context_ai_block = f"""
DETECTED BUSINESS CONTEXT{override_note} (confidence {conf:.0%}):
- Category: {category}
- Writing style: {style}
Write captions ONLY for this category and what is shown in the source material.
Never invent unrelated products or industries (e.g. do NOT write about technology or software if category is auto_service or food).
Admin discount/instruction text is NOT the business type — follow visual/source context.
"""

    kb_block = ""
    if knowledge_base_block and knowledge_base_block.strip():
        kb_block = f"\n\n{knowledge_base_block.strip()}"

    return f"""\
COMPANY: {company_name}
CATEGORY: {business_category}
BRAND VOICE: {tone} — {tone_display}
SOURCE LANGUAGE: {lang_display}{notes_block}{brand_block}{kb_block}{source_block}{context_block}{context_ai_block}

{lang_instruction}
Use brand profile details, CTA info, and hashtag preferences when writing long captions.
Never use words/phrases listed as "AVOID".

Generate social media captions for ONE post. Return ONLY this JSON (no other text):
{{
  "caption_short_ru": "Short Russian caption ≤150 chars — punchy, standalone",
  "caption_short_uz": "Short Uzbek caption ≤150 chars — punchy, standalone",
  "caption_short_en": "Short English caption ≤150 chars — punchy, standalone",
  "caption_long_ru": "Full Russian post 200-400 chars with call-to-action",
  "caption_long_uz": "Full Uzbek post 200-400 chars with call-to-action",
  "caption_long_en": "Full English post 200-400 chars with call-to-action",
  "hashtags": "#tag1 #tag2 ... (10-15 tags, mix of UZ/RU/EN)"
}}"""


def _extract_json(text: str) -> dict:
    """Extract JSON from response — handles markdown code fences gracefully."""
    # Strip markdown fences if present
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    return json.loads(text)


def _make_demo_content(company_name: str, business_category: str) -> GeneratedContent:
    """
    Return plausible-looking demo content when DEMO_MODE=true in .env.
    Lets you test the full UI flow without a real OpenAI key.
    """
    return GeneratedContent(
        caption_short_ru=f"🌟 {company_name} — качество, которому доверяют!",
        caption_long_ru=(
            f"Откройте для себя лучшее от {company_name}! "
            f"Мы специализируемся в сфере {business_category} и предлагаем "
            f"только проверенное качество для жителей Ташкента. "
            f"Заходите к нам — убедитесь сами! 👉"
        ),
        caption_short_uz=f"🌟 {company_name} — ishonchli sifat!",
        caption_long_uz=(
            f"{company_name} — {business_category} sohasidagi eng yaxshi tanlov! "
            f"Toshkent aholisi uchun sifatli xizmat va mahsulotlar. "
            f"Bugun tashrif buyuring va o'zingiz ko'ring! 👉"
        ),
        caption_short_en=f"🌟 {company_name} — quality you can trust!",
        caption_long_en=(
            f"Discover the best of {company_name}! "
            f"We specialize in {business_category} and bring premium quality "
            f"to Tashkent. Visit us today and see the difference! 👉"
        ),
        hashtags=(
            f"#{company_name.replace(' ', '')} #Ташкент #Toshkent #Tashkent "
            f"#{business_category.replace(' ', '')} #качество #sifat #quality "
            f"#Узбекистан #Oʻzbekiston #Uzbekistan"
        ),
    )


async def generate_content(
    company_name: str,
    business_category: str,
    content_style: str,
    source_language: str = "zh",
    source_text: str | None = None,
    context_hint: str | None = None,
    client_notes: str | None = None,
    brand_profile: dict | None = None,
    context_signals: dict | None = None,
    knowledge_base_block: str | None = None,
) -> GeneratedContent:
    """
    Call OpenAI and return structured multilingual captions.

    Set DEMO_MODE=true in backend/.env to test the full flow without an API key.

    Raises:
        ValueError — API key not configured (and DEMO_MODE not enabled)
        RuntimeError — OpenAI call failed or returned invalid JSON
    """
    # Demo mode: skip OpenAI, return realistic-looking placeholder content
    if settings.DEMO_MODE:
        return _make_demo_content(company_name, business_category)

    _validate_api_key()

    business_context = None
    if context_signals:
        from app.services.context_ai_service import resolve_business_context_for_generation
        business_context = await resolve_business_context_for_generation(context_signals)

    prompt = _build_prompt(
        company_name=company_name,
        business_category=business_category,
        content_style=content_style,
        source_language=source_language,
        source_text=source_text,
        context_hint=context_hint,
        client_notes=client_notes,
        brand_profile=brand_profile,
        business_context=business_context,
        knowledge_base_block=knowledge_base_block,
    )

    openai = get_openai()

    # Try up to 2 times in case of malformed JSON on first attempt
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            response = await openai.chat.completions.create(
                model=settings.OPENAI_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user",   "content": prompt},
                ],
                temperature=0.72,
                max_tokens=1800,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
            data = _extract_json(raw)
            return GeneratedContent(**data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            last_error = e
            continue   # retry once
        except Exception as e:
            err_str = str(e)
            if "timeout" in err_str.lower() or "timed out" in err_str.lower():
                raise RuntimeError(
                    "OpenAI request timed out after 60 seconds. "
                    "Try with shorter source text or try again."
                ) from e
            raise RuntimeError(f"OpenAI API error: {e}") from e

    raise RuntimeError(
        f"AI returned invalid JSON after 2 attempts. Last error: {last_error}"
    )
