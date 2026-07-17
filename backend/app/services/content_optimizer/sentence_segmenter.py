"""Deterministic multilingual sentence and paragraph segmentation.

No language model or heuristic "understanding" — pure rule-based scanning that is
stable across runs. Latin/Cyrillic sentences end on terminal punctuation followed
by whitespace/end; CJK sentences end on full-width terminators immediately. The
segmenter never rewrites, translates or reorders text: it only slices it.
"""
from __future__ import annotations

from app.services.content_optimizer.schemas import SourceSection

# Full-width / CJK sentence terminators — boundary applies immediately.
_CJK_TERMINATORS = frozenset("。！？；…‥")
# Latin/Cyrillic terminators — boundary requires trailing whitespace or end.
_LATIN_TERMINATORS = frozenset(".!?;")
# Closing quotes/brackets absorbed into the preceding sentence.
_CLOSERS = frozenset("\"'”’»)]}）】」』’›")
# Conservative abbreviation guard (lowercased, trailing dot stripped).
_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e",
    "no", "inc", "ltd", "co", "corp", "т.д", "т.п", "др", "напр", "рис", "стр",
})


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines; preserve single-newline lines inside a paragraph."""
    if not text:
        return []
    blocks: list[str] = []
    current: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line.strip() == "":
            if current:
                blocks.append("\n".join(current).strip())
                current = []
            continue
        current.append(line.rstrip())
    if current:
        blocks.append("\n".join(current).strip())
    return [b for b in blocks if b]


def _preceding_word(buf: list[str]) -> str:
    word: list[str] = []
    for ch in reversed(buf[:-1]):
        if ch.isalnum() or ch in "._":
            word.append(ch)
        else:
            break
    return "".join(reversed(word))


def _is_abbreviation_boundary(buf: list[str]) -> bool:
    word = _preceding_word(buf).rstrip(".").lower()
    if not word:
        return False
    if len(word) == 1 and word.isalpha():
        return True
    return word in _ABBREVIATIONS


def split_sentences(text: str) -> list[str]:
    """Split a text block into ordered sentences, terminators preserved."""
    stripped = (text or "").strip()
    if not stripped:
        return []

    sentences: list[str] = []
    buf: list[str] = []
    i = 0
    n = len(stripped)

    def flush() -> None:
        candidate = "".join(buf).strip()
        if candidate:
            sentences.append(candidate)
        buf.clear()

    while i < n:
        ch = stripped[i]
        buf.append(ch)

        if ch in _CJK_TERMINATORS:
            i += 1
            while i < n and stripped[i] in _CLOSERS:
                buf.append(stripped[i])
                i += 1
            flush()
            continue

        if ch in _LATIN_TERMINATORS:
            if ch == "." and _is_abbreviation_boundary(buf):
                i += 1
                continue
            j = i + 1
            while j < n and stripped[j] in _LATIN_TERMINATORS:
                buf.append(stripped[j])
                j += 1
            while j < n and stripped[j] in _CLOSERS:
                buf.append(stripped[j])
                j += 1
            if j >= n or stripped[j].isspace():
                i = j
                flush()
                continue
            i = j
            continue

        i += 1

    if buf:
        flush()
    return sentences


def segment(text: str) -> list[SourceSection]:
    """Return ordered paragraph sections, each carrying its sentences."""
    sections: list[SourceSection] = []
    for index, paragraph in enumerate(split_paragraphs(text)):
        sections.append(
            SourceSection(
                kind="paragraph",
                index=index,
                text=paragraph,
                sentences=split_sentences(paragraph),
            )
        )
    return sections


def first_meaningful_sentence(text: str) -> str | None:
    """First sentence with at least one alphanumeric/CJK character."""
    for sentence in split_sentences(text):
        if any(c.isalnum() for c in sentence):
            return sentence
    return None
