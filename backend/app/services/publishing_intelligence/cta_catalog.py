"""Versioned multilingual CTA phrase catalog (deterministic, no LLM)."""
from __future__ import annotations

import re
from dataclasses import dataclass

CTA_CATALOG_VERSION = "1.0.0"

# Normalized action families → phrases by language (lowercase match).
# Use trailing commas for single-element tuples.
_CTA_PHRASES: dict[str, dict[str, tuple[str, ...]]] = {
    "contact": {
        "en": ("contact us", "get in touch", "reach out", "message us"),
        "ru": ("свяжитесь с нами", "напишите нам", "обратитесь к нам"),
        "uz": ("biz bilan bog'laning", "bizga yozing", "aloqa qiling"),
        "zh": ("联系我们", "立即联系", "在线咨询"),
    },
    "request_quote": {
        "en": ("request a quote", "get a quote", "ask for quote", "request quote"),
        "ru": ("запросить цену", "получить предложение", "запросить квоту"),
        "uz": ("narx so'rang", "taklif oling"),
        "zh": ("获取报价", "询价", "索取报价"),
    },
    "buy": {
        "en": ("buy now", "shop now", "order now", "purchase"),
        "ru": ("купить", "заказать сейчас", "оформить заказ"),
        "uz": ("hozir sotib oling", "buyurtma bering"),
        "zh": ("立即购买", "马上订购", "下单"),
    },
    "register": {
        "en": ("register now", "sign up", "join now", "create account"),
        "ru": ("зарегистрируйтесь", "запишитесь", "присоединяйтесь"),
        "uz": ("ro'yxatdan o'ting", "qo'shiling"),
        "zh": ("立即注册", "马上报名", "注册"),
    },
    "download": {
        "en": ("download now", "get the file", "download"),
        "ru": ("скачать", "загрузить файл"),
        "uz": ("yuklab oling",),
        "zh": ("立即下载", "下载"),
    },
    "learn_more": {
        "en": ("learn more", "read more", "find out more", "discover more"),
        "ru": ("узнать больше", "подробнее", "читать далее"),
        "uz": ("batafsil", "ko'proq bilib oling"),
        "zh": ("了解更多", "查看详情"),
    },
    "book_demo": {
        "en": ("book a demo", "schedule a demo", "request a demo"),
        "ru": ("записаться на демо", "заказать демо"),
        "uz": ("demo band qiling",),
        "zh": ("预约演示", "申请演示"),
    },
    "subscribe": {
        "en": ("subscribe", "follow us", "join our channel"),
        "ru": ("подпишитесь", "подписаться", "следите за нами"),
        "uz": ("obuna bo'ling", "kanalimizga qo'shiling"),
        "zh": ("订阅", "关注我们", "加入频道"),
    },
    "visit_link": {
        "en": ("click here", "see link", "open the link", "visit our"),
        "ru": ("перейдите по ссылке", "нажмите здесь", "откройте ссылку"),
        "uz": ("havolani oching", "bu yerni bosing"),
        "zh": ("点击链接", "访问链接", "打开链接"),
    },
    "send_message": {
        "en": ("send a message", "dm us", "write to us", "text us"),
        "ru": ("отправьте сообщение", "напишите в лс"),
        "uz": ("xabar yuboring",),
        "zh": ("发送消息", "私信我们"),
    },
}

# Content types for which CTA may be not_applicable.
INFORMATIONAL_MARKERS = (
    "announcement",
    "告知",
    "объявление",
    "e'lon",
    "fyi",
    "for your information",
)


@dataclass(frozen=True)
class CtaMatch:
    family: str
    phrase: str
    language: str
    start: int
    end: int


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    """Word-aware match for Latin phrases; substring match for CJK."""
    if re.search(r"[\u4e00-\u9fff]", phrase):
        return re.compile(re.escape(phrase))
    return re.compile(rf"(?<!\w){re.escape(phrase)}(?!\w)", re.IGNORECASE)


def detect_ctas(text: str) -> list[CtaMatch]:
    """Find CTA phrases in text using the versioned catalog."""
    if not text or not text.strip():
        return []
    lowered = text.lower()
    matches: list[CtaMatch] = []
    for family, by_lang in _CTA_PHRASES.items():
        for lang, phrases in by_lang.items():
            for phrase in phrases:
                if not isinstance(phrase, str) or len(phrase.strip()) < 2:
                    continue
                pattern = _phrase_pattern(phrase.lower())
                for m in pattern.finditer(lowered):
                    matches.append(
                        CtaMatch(
                            family=family,
                            phrase=phrase,
                            language=lang,
                            start=m.start(),
                            end=m.end(),
                        )
                    )
    matches.sort(key=lambda m: (-(m.end - m.start), m.start, m.family))
    deduped: list[CtaMatch] = []
    occupied: list[tuple[int, int]] = []
    for m in matches:
        if any(not (m.end <= a or m.start >= b) for a, b in occupied):
            continue
        deduped.append(m)
        occupied.append((m.start, m.end))
    deduped.sort(key=lambda m: m.start)
    return deduped


def looks_informational(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in INFORMATIONAL_MARKERS)


def catalog_summary() -> dict:
    return {
        "version": CTA_CATALOG_VERSION,
        "families": sorted(_CTA_PHRASES.keys()),
        "languages": ["en", "ru", "uz", "zh"],
    }
