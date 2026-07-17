"""No-invention provenance validator.

Guarantees a generated variant introduces no lexical token absent from the
approved corpus (source captions + tenant-approved template texts). Tokenization
is deterministic and multilingual:

* URLs, hashtags and numbers are treated as single atomic tokens.
* Latin / Cyrillic words are tokens (case-folded).
* CJK characters are tokenized individually (character runs).
* Pure formatting — whitespace and punctuation that does not carry a lexical
  token — is ignored, so restructuring/normalization is always allowed.

Validation is a multiset (count-aware) subset check: the output may drop or
reorder tokens, but may never contain a token — or more copies of a token — than
the approved corpus provides.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"#[^\s#.,;:!?)（）]+", re.UNICODE)
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)*")
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uff66-\uff9f]"
)


@dataclass
class ProvenanceResult:
    ok: bool
    extras: dict[str, int] = field(default_factory=dict)
    output_token_count: int = 0
    corpus_token_count: int = 0


def tokenize(text: str | None) -> Counter[str]:
    """Return a multiset of lexical tokens with type prefixes to avoid collisions."""
    counter: Counter[str] = Counter()
    if not text:
        return counter
    working = text

    for match in _URL_RE.finditer(working):
        counter[f"u:{match.group(0).casefold()}"] += 1
    working = _URL_RE.sub(" ", working)

    for match in _HASHTAG_RE.finditer(working):
        counter[f"h:{match.group(0).lstrip('#').casefold()}"] += 1
    working = _HASHTAG_RE.sub(" ", working)

    for match in _NUMBER_RE.finditer(working):
        counter[f"n:{match.group(0)}"] += 1
    working = _NUMBER_RE.sub(" ", working)

    for match in _CJK_RE.finditer(working):
        counter[f"c:{match.group(0)}"] += 1
    working = _CJK_RE.sub(" ", working)

    for match in _WORD_RE.finditer(working):
        counter[f"w:{match.group(0).casefold()}"] += 1

    return counter


def build_corpus(texts: list[str]) -> Counter[str]:
    corpus: Counter[str] = Counter()
    for text in texts:
        corpus.update(tokenize(text))
    return corpus


def validate_tokens(output_texts: list[str], corpus: Counter[str]) -> ProvenanceResult:
    output: Counter[str] = Counter()
    for text in output_texts:
        output.update(tokenize(text))

    extras: dict[str, int] = {}
    for token, count in output.items():
        allowed = corpus.get(token, 0)
        if count > allowed:
            extras[token] = count - allowed

    return ProvenanceResult(
        ok=not extras,
        extras=extras,
        output_token_count=sum(output.values()),
        corpus_token_count=sum(corpus.values()),
    )


def validate_variant(
    *,
    caption: str,
    hashtags: list[str],
    cta: str | None,
    link: str | None,
    corpus: Counter[str],
) -> ProvenanceResult:
    """Validate a variant against the approved corpus.

    The caption body, hashtags and link are the actually-rendered surface and are
    checked cumulatively (count-aware) — they may never contain more copies of a
    token than the corpus provides. The CTA is stored as a *pointer* to existing
    approved wording (it is already part of the caption or an approved template),
    so it is validated by presence only to avoid false-positive double counting.
    """
    output_texts: list[str] = [caption]
    output_texts.extend(f"#{tag}" for tag in hashtags)
    if link:
        output_texts.append(link)
    result = validate_tokens(output_texts, corpus)
    if not result.ok:
        return result

    if cta:
        for token in tokenize(cta):
            if corpus.get(token, 0) <= 0:
                result.extras[token] = 1
        result.ok = not result.extras
    return result
