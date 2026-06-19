"""
OCR Service — extract text from images.

Strategy (in priority order):
1. GPT-4o vision  — best accuracy, handles Chinese/Russian/mixed perfectly.
                    Used when OPENAI_API_KEY is configured.
2. pytesseract     — zero-cost fallback, eng-only (no chi_sim pack in base image).
                    Used when no API key, or as emergency fallback.

The caller gets back a plain string (possibly empty) and never needs to know
which backend ran.
"""
import base64
import io
import logging

from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

# Maximum image size sent to the vision API (pixels on longest side).
# GPT-4o "high" detail mode tiles at 512px, so 1536 is a good cap.
_MAX_VISION_PX = 1536

# pytesseract is optional — only imported when needed
_tesseract_available: bool | None = None


def _check_tesseract() -> bool:
    global _tesseract_available
    if _tesseract_available is None:
        try:
            import pytesseract  # noqa: F401
            _tesseract_available = True
        except ImportError:
            _tesseract_available = False
    return _tesseract_available


def _resize_for_vision(image_bytes: bytes) -> tuple[bytes, str]:
    """
    Resize image so its longest side ≤ _MAX_VISION_PX.
    Returns (jpeg_bytes, mime_type).
    """
    img = Image.open(io.BytesIO(image_bytes))
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")

    w, h = img.size
    longest = max(w, h)
    if longest > _MAX_VISION_PX:
        scale = _MAX_VISION_PX / longest
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "image/jpeg"


async def _ocr_via_vision(image_bytes: bytes) -> str:
    """Use GPT-4o vision to extract text. Returns extracted text or ''."""
    from openai import AsyncOpenAI

    jpeg_bytes, mime = _resize_for_vision(image_bytes)
    b64 = base64.b64encode(jpeg_bytes).decode()

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=30.0)

    prompt = (
        "Extract ALL text visible in this image exactly as written. "
        "Include Chinese characters, Cyrillic, Latin — everything. "
        "Return ONLY the extracted text with no commentary, no formatting, "
        "no labels. If there is no text, return an empty string."
    )

    response = await client.chat.completions.create(
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
        max_tokens=500,
        temperature=0,
    )
    text = (response.choices[0].message.content or "").strip()
    logger.info("OCR (vision): extracted %d chars", len(text))
    return text


def _ocr_via_tesseract(image_bytes: bytes) -> str:
    """
    Tesseract fallback — eng only (no chi_sim in base Docker image).
    Still useful for images with Latin/Cyrillic product names or prices.
    """
    import pytesseract  # type: ignore

    img = Image.open(io.BytesIO(image_bytes))
    text = pytesseract.image_to_string(img, lang="eng", config="--psm 3")
    text = text.strip()
    logger.info("OCR (tesseract/eng): extracted %d chars", len(text))
    return text


async def extract_text(image_bytes: bytes) -> str:
    """
    Main entry point.  Returns extracted text (may be empty string).
    Never raises — logs errors and returns '' so callers are not disrupted.
    """
    if not image_bytes:
        return ""

    # Try vision first (best for Chinese)
    key = settings.OPENAI_API_KEY or ""
    if key and not key.startswith("sk-your"):
        logger.info("OCR started (vision / gpt-4o) — image size %d bytes", len(image_bytes))
        try:
            text = await _ocr_via_vision(image_bytes)
            if text:
                logger.info("OCR completed (vision) — extracted %d chars", len(text))
                return text
            logger.debug("OCR vision returned empty; falling through to tesseract")
        except Exception as exc:
            logger.warning("OCR vision failed (%s); trying tesseract fallback", exc)

    # Tesseract fallback
    if _check_tesseract():
        logger.info("OCR started (tesseract/eng) — image size %d bytes", len(image_bytes))
        try:
            text = _ocr_via_tesseract(image_bytes)
            logger.info("OCR completed (tesseract) — extracted %d chars", len(text))
            return text
        except Exception as exc:
            logger.warning("OCR tesseract failed: %s", exc)

    logger.info("OCR completed — no text extracted")
    return ""


async def describe_image(image_bytes: bytes, business_category: str = "") -> str:
    """
    Use GPT-4o vision to produce a short English scene description for images
    that have no caption. Includes visible business/industry cues when obvious.

    Returns "" if no API key or vision call fails — caller handles gracefully.
    """
    if not image_bytes:
        return ""

    key = settings.OPENAI_API_KEY or ""
    if not key or key.startswith("sk-your"):
        logger.info("describe_image: no API key — skipping image understanding")
        return ""

    jpeg_bytes, mime = _resize_for_vision(image_bytes)
    b64 = base64.b64encode(jpeg_bytes).decode()

    prompt = (
        "Look at this image and write ONE short English sentence (max 25 words) "
        "describing the main scene, products, or service shown for a social media post. "
        "Include the type of business if visually obvious "
        "(e.g. auto repair, cafe food, electronics, beauty salon). "
        "Describe what you SEE — do not assume an industry without visual evidence. "
        "Start with 'Detected:'. Examples: "
        "'Detected: car wheel and brake service in an auto repair garage' or "
        "'Detected: burger and fries on a cafe table' or "
        "'Detected: laptop and accessories in an electronics store'. "
        "Return ONLY that sentence, nothing else."
    )

    try:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=key, timeout=20.0)
        logger.info("describe_image: vision analysis started")
        response = await client.chat.completions.create(
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
                                "detail": "low",   # low = faster + cheaper for description
                            },
                        },
                    ],
                }
            ],
            max_tokens=60,
            temperature=0,
        )
        description = (response.choices[0].message.content or "").strip()
        logger.info("describe_image: completed — %s", description)
        return description
    except Exception as exc:
        logger.warning("describe_image: vision failed (%s) — continuing without description", exc)
        return ""
