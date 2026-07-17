"""Prompt-injection heuristics and safety policy gates."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


SAFETY_POLICY_VERSION = "1.0.0"

_SUSPICIOUS_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ignore_instructions", re.compile(r"(?i)\bignore\s+(all\s+)?(previous|prior|above)\s+instructions?\b")),
    ("system_prompt", re.compile(r"(?i)\b(system\s+prompt|developer\s+message)\b")),
    ("reveal_secrets", re.compile(r"(?i)\b(reveal|show|print)\s+(your\s+)?(secrets?|api\s*keys?|system\s+prompt)\b")),
    ("api_key_probe", re.compile(r"(?i)\bapi\s*key\b")),
    ("execute_code", re.compile(r"(?i)\b(execute\s+code|run\s+shell|eval\()\b")),
]


@dataclass
class InjectionScanResult:
    flagged: bool
    categories: list[str] = field(default_factory=list)
    match_count: int = 0


def scan_untrusted_text(text: str) -> InjectionScanResult:
    """Flag instruction-like content. Never log matched substrings."""
    if not text:
        return InjectionScanResult(flagged=False)
    cats: list[str] = []
    count = 0
    for name, pattern in _SUSPICIOUS_PATTERNS:
        found = list(pattern.finditer(text))
        if found:
            cats.append(name)
            count += len(found)
    return InjectionScanResult(flagged=bool(cats), categories=cats, match_count=count)


def should_block_injection(*, flagged: bool, policy_block: bool = False) -> bool:
    """Phase 2B: flag by default; block only when tenant/safety policy requires it."""
    return flagged and policy_block
