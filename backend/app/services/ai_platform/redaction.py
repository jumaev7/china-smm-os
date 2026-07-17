"""Secret / credential redaction before provider submission."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("api_key", re.compile(r"(?i)\b(sk-[A-Za-z0-9_-]{16,}|api[_-]?key\s*[:=]\s*\S+)\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("bearer", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9\-._~+/]+=*\b")),
    ("password", re.compile(r"(?i)\b(password|passwd|pwd)\s*[:=]\s*\S+")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("db_url", re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb)://\S+")),
    ("signed_url", re.compile(r"(?i)[?&](X-Amz-Signature|Signature|sig|token)=[^\s&]+")),
]

# Patterns that block AI adaptation entirely if essential to caption.
_BLOCKING_CATEGORIES = frozenset({"api_key", "jwt", "bearer", "private_key", "db_url", "password"})


@dataclass
class RedactionResult:
    text: str
    redaction_count: int = 0
    categories: list[str] = field(default_factory=list)
    blocked: bool = False
    block_categories: list[str] = field(default_factory=list)


def redact_text(text: str, *, block_secrets: bool = True) -> RedactionResult:
    if not text:
        return RedactionResult(text="")
    out = text
    categories: list[str] = []
    count = 0
    blocked_cats: list[str] = []
    for category, pattern in _PATTERNS:
        matches = list(pattern.finditer(out))
        if not matches:
            continue
        categories.append(category)
        count += len(matches)
        if block_secrets and category in _BLOCKING_CATEGORIES:
            blocked_cats.append(category)
        out = pattern.sub(f"[REDACTED:{category.upper()}]", out)
    return RedactionResult(
        text=out,
        redaction_count=count,
        categories=sorted(set(categories)),
        blocked=bool(blocked_cats),
        block_categories=sorted(set(blocked_cats)),
    )


def redact_mapping(data: dict[str, Any], *, block_secrets: bool = True) -> tuple[dict[str, Any], RedactionResult]:
    """Recursively redact string values in a dict; returns redacted copy + aggregate result."""
    categories: list[str] = []
    count = 0
    blocked = False
    block_categories: list[str] = []

    def _walk(value: Any) -> Any:
        nonlocal count, blocked
        if isinstance(value, str):
            r = redact_text(value, block_secrets=block_secrets)
            count += r.redaction_count
            categories.extend(r.categories)
            if r.blocked:
                blocked = True
                block_categories.extend(r.block_categories)
            return r.text
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, dict):
            return {k: _walk(v) for k, v in value.items()}
        return value

    redacted = _walk(data)
    return redacted, RedactionResult(
        text="",
        redaction_count=count,
        categories=sorted(set(categories)),
        blocked=blocked,
        block_categories=sorted(set(block_categories)),
    )


def fingerprint_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()
