"""Allowlisted, deterministic transformation operations.

Every operation is a pure function that only restructures, shortens, splits,
normalizes, selects or reorders text that already exists. None of them invent,
paraphrase, translate or semantically rewrite content. The engine runs an ordered
pipeline and records an explainable :class:`TransformationRecord` for every step
that actually changed the draft.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.content_optimizer import hashtag_optimizer as ht
from app.services.content_optimizer.cta_selector import select_existing_cta
from app.services.content_optimizer.schemas import (
    MAX_TRANSFORMATIONS_PER_VARIANT,
    TransformationRecord,
    VariantDraft,
)
from app.services.content_optimizer.sentence_segmenter import split_sentences

_WS_RUN_RE = re.compile(r"[ \t\u00a0\u3000]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{2,}")
_BULLET_RE = re.compile(r"^[\s]*[-*–—·▪◦‣]\s+", re.UNICODE)
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_DECORATIVE = "-–—*•·|>_=~^ \t"


@dataclass
class OperationContext:
    """Provenance-safe inputs available to every operation."""

    source_text: str = ""
    cta_templates: list[str] = field(default_factory=list)
    policy: dict[str, Any] = field(default_factory=dict)
    disclosure: str | None = None


# outcome: (new_draft, changed, reason_params, result_summary)
OperationOutcome = tuple[VariantDraft, bool, dict[str, Any], str | None]
OperationFunc = Callable[[VariantDraft, dict[str, Any], OperationContext], OperationOutcome]


@dataclass(frozen=True)
class OperationSpec:
    key: str
    category: str
    reason_key: str
    func: OperationFunc


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _rendered_overhead(draft: VariantDraft) -> int:
    overhead = 0
    if draft.cta:
        overhead += len(draft.cta) + 2
    if draft.link:
        overhead += len(draft.link) + 2
    if draft.hashtags:
        overhead += sum(len(ht.render_hashtag(t)) + 1 for t in draft.hashtags) + 1
    return overhead


def _ensure_disclosure(draft: VariantDraft, ctx: OperationContext) -> bool:
    """Guarantee a mandatory source disclosure survives selection/truncation."""
    disclosure = (ctx.disclosure or "").strip()
    if not disclosure:
        return False
    present = any(disclosure.casefold() in p.casefold() for p in draft.paragraphs)
    if present:
        return False
    draft.paragraphs.append(disclosure)
    return True


def _flatten_sentences(paragraphs: list[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for p_index, paragraph in enumerate(paragraphs):
        for sentence in split_sentences(paragraph):
            out.append((p_index, sentence))
    return out


# --- Normalization ---------------------------------------------------------

def _op_normalize_whitespace(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    changed = False
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        lines = [
            _WS_RUN_RE.sub(" ", line).strip()
            for line in paragraph.split("\n")
        ]
        collapsed = "\n".join(lines).strip()
        if collapsed != paragraph:
            changed = True
        rebuilt.append(collapsed)
    new.paragraphs = [p for p in rebuilt if p]
    if len(new.paragraphs) != len([p for p in draft.paragraphs if p]):
        changed = True
    return new, changed, {}, None


def _op_normalize_line_breaks(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    changed = False
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        collapsed = _MULTI_NEWLINE_RE.sub("\n", paragraph.replace("\r\n", "\n").replace("\r", "\n"))
        if collapsed != paragraph:
            changed = True
        rebuilt.append(collapsed)
    new.paragraphs = rebuilt
    return new, changed, {}, None


def _op_remove_duplicate_blank_lines(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    before = len(new.paragraphs)
    new.paragraphs = [p for p in new.paragraphs if p.strip()]
    changed = len(new.paragraphs) != before
    return new, changed, {"removed": before - len(new.paragraphs)}, None


def _op_trim_leading_trailing_punctuation(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    if not new.paragraphs:
        return new, False, {}, None
    changed = False
    first = new.paragraphs[0].lstrip(_DECORATIVE)
    if first != new.paragraphs[0]:
        new.paragraphs[0] = first
        changed = True
    last = new.paragraphs[-1].rstrip(_DECORATIVE)
    if last != new.paragraphs[-1]:
        new.paragraphs[-1] = last
        changed = True
    new.paragraphs = [p for p in new.paragraphs if p.strip()]
    return new, changed, {}, None


def _op_normalize_bullet_format(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    changed = False
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        lines: list[str] = []
        for line in paragraph.split("\n"):
            replaced = _BULLET_RE.sub("• ", line)
            if replaced != line:
                changed = True
            lines.append(replaced)
        rebuilt.append("\n".join(lines))
    new.paragraphs = rebuilt
    return new, changed, {}, None


def _op_apply_platform_line_breaks(draft, params, ctx) -> OperationOutcome:
    """Join intra-paragraph single newlines into spaces unless bullet lines."""
    new = draft.clone()
    changed = False
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        lines = paragraph.split("\n")
        if any(line.lstrip().startswith("• ") for line in lines):
            rebuilt.append(paragraph)
            continue
        joined = _WS_RUN_RE.sub(" ", " ".join(l.strip() for l in lines)).strip()
        if joined != paragraph:
            changed = True
        rebuilt.append(joined)
    new.paragraphs = [p for p in rebuilt if p]
    return new, changed, {}, None


def _op_join_short_lines(draft, params, ctx) -> OperationOutcome:
    min_chars = int(params.get("min_chars", 40))
    new = draft.clone()
    changed = False
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        lines = paragraph.split("\n")
        merged: list[str] = []
        buffer = ""
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if buffer:
                buffer = f"{buffer} {stripped}".strip()
            else:
                buffer = stripped
            terminated = buffer[-1] in ".!?;:。！？；" if buffer else True
            if len(buffer) >= min_chars or terminated:
                merged.append(buffer)
                buffer = ""
        if buffer:
            merged.append(buffer)
        joined = "\n".join(merged)
        if joined != paragraph:
            changed = True
        rebuilt.append(joined)
    new.paragraphs = rebuilt
    return new, changed, {"min_chars": min_chars}, None


def _op_split_long_paragraphs(draft, params, ctx) -> OperationOutcome:
    max_chars = int(params.get("max_chars", 600))
    new = draft.clone()
    changed = False
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        if len(paragraph) <= max_chars:
            rebuilt.append(paragraph)
            continue
        sentences = split_sentences(paragraph)
        if len(sentences) <= 1:
            rebuilt.append(paragraph)
            continue
        chunk = ""
        for sentence in sentences:
            candidate = f"{chunk} {sentence}".strip() if chunk else sentence
            if chunk and len(candidate) > max_chars:
                rebuilt.append(chunk)
                chunk = sentence
            else:
                chunk = candidate
        if chunk:
            rebuilt.append(chunk)
        changed = True
    new.paragraphs = rebuilt
    return new, changed, {"max_chars": max_chars}, None


# --- Deduplication ---------------------------------------------------------

def _op_deduplicate_exact_sentences(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    seen: set[str] = set()
    changed = False
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        sentences = split_sentences(paragraph)
        if not sentences:
            rebuilt.append(paragraph)
            continue
        kept: list[str] = []
        for sentence in sentences:
            key = sentence.casefold()
            if key in seen:
                changed = True
                continue
            seen.add(key)
            kept.append(sentence)
        if kept:
            rebuilt.append(" ".join(kept))
        elif not changed:
            rebuilt.append(paragraph)
    new.paragraphs = [p for p in rebuilt if p.strip()]
    return new, changed, {}, None


def _op_deduplicate_exact_hashtags(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    deduped = ht.dedupe_hashtags(new.hashtags)
    changed = deduped != new.hashtags
    new.hashtags = deduped
    return new, changed, {"removed": len(draft.hashtags) - len(deduped)}, None


def _op_remove_empty_sections(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    before = len(new.paragraphs)
    new.paragraphs = [p for p in new.paragraphs if p.strip()]
    changed = len(new.paragraphs) != before
    return new, changed, {}, None


def _op_remove_repeated_link(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    changed = False
    seen: set[str] = set()
    if new.link:
        seen.add(new.link)
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        def _dedupe(match: re.Match[str]) -> str:
            nonlocal changed
            url = match.group(0)
            if url in seen:
                changed = True
                return ""
            seen.add(url)
            return url

        replaced = _URL_RE.sub(_dedupe, paragraph)
        replaced = _WS_RUN_RE.sub(" ", replaced).strip()
        rebuilt.append(replaced)
    new.paragraphs = [p for p in rebuilt if p.strip()]
    return new, changed, {}, None


# --- Hashtag operations ----------------------------------------------------

def _op_move_hashtags_to_end(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    changed = False
    relocated: list[str] = []
    rebuilt: list[str] = []
    for paragraph in new.paragraphs:
        inline = ht.extract_inline_hashtags(paragraph)
        if not inline:
            rebuilt.append(paragraph)
            continue
        stripped = ht._INLINE_HASHTAG_RE.sub("", paragraph)
        stripped = _WS_RUN_RE.sub(" ", stripped).strip()
        stripped = re.sub(r"\s+([.,!?;:])", r"\1", stripped)
        relocated.extend(inline)
        changed = True
        if stripped:
            rebuilt.append(stripped)
    if relocated:
        new.hashtags = ht.dedupe_hashtags(new.hashtags + relocated)
    new.paragraphs = [p for p in rebuilt if p.strip()]
    return new, changed, {"moved": len(relocated)}, None


def _op_limit_hashtag_count(draft, params, ctx) -> OperationOutcome:
    max_count = int(params.get("max", ctx.policy.get("hashtag_recommended_max", 30)))
    new = draft.clone()
    limited = ht.limit_hashtags(new.hashtags, max_count)
    changed = limited != new.hashtags
    new.hashtags = limited
    return new, changed, {"max": max_count}, None


def _op_remove_unsupported_hashtags(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    supported = ht.filter_supported(new.hashtags)
    changed = supported != new.hashtags
    new.hashtags = supported
    return new, changed, {"removed": len(draft.hashtags) - len(supported)}, None


# --- Structure / selection -------------------------------------------------

def _op_preserve_first_paragraph(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    changed = not new.protect_first_paragraph
    new.protect_first_paragraph = True
    return new, changed, {}, None


def _op_preserve_last_cta(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    changed = not new.protect_last_cta
    new.protect_last_cta = True
    return new, changed, {}, None


def _op_select_first_n_sentences(draft, params, ctx) -> OperationOutcome:
    n = int(params.get("n", 1))
    new = draft.clone()
    flat = _flatten_sentences(new.paragraphs)
    if len(flat) <= n:
        return new, False, {"n": n}, None
    kept = flat[:n]
    # When the lead paragraph is protected, keep every sentence from paragraph 0
    # even if that exceeds n (structural guarantee, not a rewrite).
    if new.protect_first_paragraph and new.paragraphs:
        lead = [(p_index, s) for p_index, s in flat if p_index == 0]
        if lead and (not kept or kept[0][0] != 0):
            kept = lead + [pair for pair in kept if pair[0] != 0]
        elif lead:
            # Ensure all lead sentences are present.
            lead_set = set(lead)
            rest = [pair for pair in kept if pair not in lead_set]
            kept = lead + rest
            # Trim back to at least n while keeping lead intact.
            if len(kept) > max(n, len(lead)):
                kept = lead + rest[: max(0, n - len(lead))]
    grouped: dict[int, list[str]] = {}
    order: list[int] = []
    for p_index, sentence in kept:
        if p_index not in grouped:
            grouped[p_index] = []
            order.append(p_index)
        grouped[p_index].append(sentence)
    new.paragraphs = [" ".join(grouped[i]) for i in order]
    _ensure_disclosure(new, ctx)
    return new, True, {"n": n, "kept": len(kept)}, None


def _op_select_first_n_paragraphs(draft, params, ctx) -> OperationOutcome:
    n = int(params.get("n", 1))
    new = draft.clone()
    if new.protect_first_paragraph:
        n = max(n, 1)
    if len(new.paragraphs) <= n:
        return new, False, {"n": n}, None
    new.paragraphs = new.paragraphs[:n]
    _ensure_disclosure(new, ctx)
    return new, True, {"n": n}, None


# --- Length control --------------------------------------------------------

def _budget(draft: VariantDraft, max_chars: int) -> int:
    return max_chars - _rendered_overhead(draft)


def _op_truncate_at_sentence_boundary(draft, params, ctx) -> OperationOutcome:
    max_chars = int(params.get("max_chars", 0))
    if max_chars <= 0:
        return draft.clone(), False, {}, None
    new = draft.clone()
    budget = _budget(new, max_chars)
    if len(new.caption_text()) <= budget:
        return new, False, {"max_chars": max_chars}, None
    flat = _flatten_sentences(new.paragraphs)
    if not flat:
        return new, False, {"max_chars": max_chars}, None

    # Always retain the lead paragraph when protected, even if over budget.
    protected_lead: list[tuple[int, str]] = []
    if new.protect_first_paragraph:
        protected_lead = [(p_index, s) for p_index, s in flat if p_index == 0]

    kept: list[tuple[int, str]] = list(protected_lead)
    running = " ".join(s for _, s in protected_lead)
    for p_index, sentence in flat:
        if protected_lead and p_index == 0:
            continue
        candidate = f"{running}\n\n{sentence}".strip() if running else sentence
        if kept and len(candidate) > budget:
            break
        kept.append((p_index, sentence))
        running = candidate
    if not kept:
        kept = [flat[0]]

    grouped: dict[int, list[str]] = {}
    order: list[int] = []
    for p_index, sentence in kept:
        if p_index not in grouped:
            grouped[p_index] = []
            order.append(p_index)
        grouped[p_index].append(sentence)
    new.paragraphs = [" ".join(grouped[i]) for i in order]
    disclosure_added = _ensure_disclosure(new, ctx)
    changed = len(kept) != len(flat) or disclosure_added
    return new, changed, {"max_chars": max_chars, "kept": len(kept)}, None


def _op_truncate_at_paragraph_boundary(draft, params, ctx) -> OperationOutcome:
    max_chars = int(params.get("max_chars", 0))
    if max_chars <= 0:
        return draft.clone(), False, {}, None
    new = draft.clone()
    budget = _budget(new, max_chars)
    if len(new.caption_text()) <= budget:
        return new, False, {"max_chars": max_chars}, None
    kept: list[str] = []
    running = ""
    for idx, paragraph in enumerate(new.paragraphs):
        # Protected lead paragraph is always retained.
        if new.protect_first_paragraph and idx == 0:
            kept.append(paragraph)
            running = paragraph
            continue
        candidate = f"{running}\n\n{paragraph}".strip() if running else paragraph
        if kept and len(candidate) > budget:
            break
        kept.append(paragraph)
        running = candidate
    if not kept and new.paragraphs:
        kept = [new.paragraphs[0]]
    original_count = len(new.paragraphs)
    new.paragraphs = kept
    disclosure_added = _ensure_disclosure(new, ctx)
    changed = len(kept) != original_count or disclosure_added
    return new, changed, {"max_chars": max_chars, "kept": len(kept)}, None


# --- CTA -------------------------------------------------------------------

def _op_select_existing_cta(draft, params, ctx) -> OperationOutcome:
    new = draft.clone()
    max_len = params.get("max_len")
    prefer = params.get("prefer", "last")
    selected = select_existing_cta(
        ctx.source_text,
        ctx.cta_templates,
        max_len=int(max_len) if max_len is not None else None,
        prefer=str(prefer),
    )
    if not selected or selected == new.cta:
        return new, False, {}, None
    new.cta = selected
    return new, True, {"prefer": prefer}, selected[:120]


OPERATIONS: dict[str, OperationSpec] = {
    spec.key: spec
    for spec in (
        OperationSpec("normalize_whitespace", "normalize", "whitespace_normalized", _op_normalize_whitespace),
        OperationSpec("normalize_line_breaks", "normalize", "line_breaks_normalized", _op_normalize_line_breaks),
        OperationSpec("remove_duplicate_blank_lines", "normalize", "blank_lines_removed", _op_remove_duplicate_blank_lines),
        OperationSpec("trim_leading_trailing_punctuation", "normalize", "edge_punctuation_trimmed", _op_trim_leading_trailing_punctuation),
        OperationSpec("normalize_bullet_format", "normalize", "bullets_normalized", _op_normalize_bullet_format),
        OperationSpec("apply_platform_line_breaks", "normalize", "platform_line_breaks_applied", _op_apply_platform_line_breaks),
        OperationSpec("join_short_lines", "normalize", "short_lines_joined", _op_join_short_lines),
        OperationSpec("split_long_paragraphs", "normalize", "long_paragraphs_split", _op_split_long_paragraphs),
        OperationSpec("deduplicate_exact_sentences", "dedupe", "duplicate_sentences_removed", _op_deduplicate_exact_sentences),
        OperationSpec("deduplicate_exact_hashtags", "dedupe", "duplicate_hashtags_removed", _op_deduplicate_exact_hashtags),
        OperationSpec("remove_empty_sections", "dedupe", "empty_sections_removed", _op_remove_empty_sections),
        OperationSpec("remove_repeated_link", "dedupe", "repeated_link_removed", _op_remove_repeated_link),
        OperationSpec("move_hashtags_to_end", "hashtag", "hashtags_moved_to_end", _op_move_hashtags_to_end),
        OperationSpec("limit_hashtag_count", "hashtag", "hashtag_count_limited", _op_limit_hashtag_count),
        OperationSpec("remove_unsupported_hashtags", "hashtag", "unsupported_hashtags_removed", _op_remove_unsupported_hashtags),
        OperationSpec("preserve_first_paragraph", "structure", "first_paragraph_preserved", _op_preserve_first_paragraph),
        OperationSpec("preserve_last_cta", "structure", "last_cta_preserved", _op_preserve_last_cta),
        OperationSpec("select_first_n_sentences", "structure", "first_sentences_selected", _op_select_first_n_sentences),
        OperationSpec("select_first_n_paragraphs", "structure", "first_paragraphs_selected", _op_select_first_n_paragraphs),
        OperationSpec("truncate_at_sentence_boundary", "length", "truncated_at_sentence", _op_truncate_at_sentence_boundary),
        OperationSpec("truncate_at_paragraph_boundary", "length", "truncated_at_paragraph", _op_truncate_at_paragraph_boundary),
        OperationSpec("select_existing_cta", "cta", "existing_cta_selected", _op_select_existing_cta),
    )
}


def list_operations() -> list[dict[str, str]]:
    """Stable catalog of allowlisted operations exposed to clients."""
    return [
        {"key": spec.key, "category": spec.category, "reason_key": spec.reason_key}
        for spec in OPERATIONS.values()
    ]


def run_pipeline(
    draft: VariantDraft,
    steps: list[tuple[str, dict[str, Any]]],
    ctx: OperationContext,
) -> tuple[VariantDraft, list[TransformationRecord]]:
    """Execute an ordered pipeline, recording each mutating step deterministically."""
    records: list[TransformationRecord] = []
    current = draft.clone()
    sequence = 0
    for op_key, params in steps:
        spec = OPERATIONS.get(op_key)
        if spec is None:
            raise KeyError(f"Unknown transformation operation: {op_key}")
        before = current.caption_text()
        before_hashtags = list(current.hashtags)
        before_cta = current.cta
        result_draft, changed, reason_params, summary = spec.func(current, dict(params or {}), ctx)
        after = result_draft.caption_text()
        if changed and (
            after != before
            or result_draft.hashtags != before_hashtags
            or result_draft.cta != before_cta
            or op_key in ("preserve_first_paragraph", "preserve_last_cta")
        ):
            if len(records) >= MAX_TRANSFORMATIONS_PER_VARIANT:
                current = result_draft
                continue
            sequence += 1
            records.append(
                TransformationRecord(
                    sequence=sequence,
                    operation_key=op_key,
                    category=spec.category,
                    reason_key=spec.reason_key,
                    reason_params=reason_params,
                    source_excerpt_hash=_sha(before),
                    result_excerpt_hash=_sha(after),
                    result_summary=summary,
                )
            )
        current = result_draft
    return current, records
