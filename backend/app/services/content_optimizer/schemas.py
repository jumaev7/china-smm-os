"""Internal dataclasses and limits for the deterministic Content Optimizer.

These are *not* API schemas — they are the in-process contracts shared between
the normalizer, transformation engine, provenance validator and the service
orchestrator. Everything here is deterministic and side-effect free.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

# --- Hard limits (input validation + fan-out guards) -----------------------
MAX_SOURCE_TEXT_LENGTH = 20000
MAX_HASHTAGS = 50
MAX_PLATFORMS_PER_RUN = 5
MAX_LOCALES_PER_RUN = 4
MAX_LENGTH_PROFILES_PER_RUN = 3
MAX_VARIANTS_PER_RUN = 45
MAX_TRANSFORMATIONS_PER_VARIANT = 40
MAX_TEMPLATE_LENGTH = 500
MAX_TEMPLATE_COUNT = 100

# Locales with ContentItem caption columns. Chinese (zh) punctuation is still
# handled by the sentence segmenter inside any of these caption bodies.
SUPPORTED_LOCALES = ("en", "ru", "uz")
LENGTH_PROFILES = ("short", "standard", "extended")

# Minimum lexical signal required to optimize at all.
MIN_SOURCE_CHARS = 12
MIN_SOURCE_WORDS = 2

# ContentItem locale attribute mapping.
LOCALE_CAPTION_FIELDS: dict[str, tuple[str, str]] = {
    "ru": ("caption_short_ru", "caption_long_ru"),
    "uz": ("caption_short_uz", "caption_long_uz"),
    "en": ("caption_short_en", "caption_long_en"),
}


@dataclass
class SourceSection:
    """A single paragraph block of the source with its ordered sentences."""

    kind: str  # "paragraph"
    index: int
    text: str
    sentences: list[str] = field(default_factory=list)


@dataclass
class LocaleSource:
    """Normalized per-locale view of the source caption."""

    locale: str
    short_text: str
    long_text: str
    text: str  # long preferred, else short — the canonical body
    paragraphs: list[str] = field(default_factory=list)
    sections: list[SourceSection] = field(default_factory=list)
    sentences: list[str] = field(default_factory=list)
    disclosure: str | None = None


@dataclass
class NormalizedSource:
    """Deterministic, immutable snapshot of a content item ready to optimize."""

    content_id: UUID
    tenant_id: UUID
    content_type: str
    primary_locale: str | None
    locales: list[str]
    platforms: list[str]
    locale_sources: dict[str, LocaleSource]
    hashtags: list[str]  # normalized, no leading '#', order-preserved + deduped
    hashtags_raw: str
    keywords: list[str]
    links: list[str]
    title: str | None
    description: str | None

    def caption_for(self, locale: str) -> str:
        ls = self.locale_sources.get(locale)
        return ls.text if ls else ""

    def has_locale(self, locale: str) -> bool:
        ls = self.locale_sources.get(locale)
        return bool(ls and ls.text.strip())


@dataclass
class TransformationRecord:
    """One explainable, allowlisted operation applied while building a variant."""

    sequence: int
    operation_key: str
    category: str
    reason_key: str
    reason_params: dict[str, Any] = field(default_factory=dict)
    source_excerpt_hash: str | None = None
    result_excerpt_hash: str | None = None
    source_position: dict[str, Any] | None = None
    policy_key: str | None = None
    policy_version: str | None = None
    result_summary: str | None = None


@dataclass
class VariantDraft:
    """Mutable working document threaded through the transformation pipeline."""

    platform: str
    locale: str
    length_profile: str
    paragraphs: list[str]
    hashtags: list[str]
    cta: str | None = None
    link: str | None = None
    protect_first_paragraph: bool = False
    protect_last_cta: bool = False

    def clone(self) -> "VariantDraft":
        return VariantDraft(
            platform=self.platform,
            locale=self.locale,
            length_profile=self.length_profile,
            paragraphs=list(self.paragraphs),
            hashtags=list(self.hashtags),
            cta=self.cta,
            link=self.link,
            protect_first_paragraph=self.protect_first_paragraph,
            protect_last_cta=self.protect_last_cta,
        )

    def caption_text(self) -> str:
        return "\n\n".join(p for p in self.paragraphs if p.strip()).strip()


@dataclass
class VariantBuildResult:
    """Outcome of building a single platform × locale × profile variant."""

    platform: str
    locale: str
    length_profile: str
    caption: str
    hashtags: list[str]
    cta: str | None
    link: str | None
    variant_fingerprint: str
    transformations: list[TransformationRecord]
    status: str  # "generated" | "failed"
    provenance_ok: bool
    unsupported_reason: str | None = None


@dataclass
class OptimizeRequest:
    """Validated request to generate a run's worth of variants."""

    content_id: UUID
    platforms: list[str] | None = None
    locales: list[str] | None = None
    length_profiles: list[str] | None = None
    configuration: dict[str, Any] | None = None
    created_by: UUID | None = None
