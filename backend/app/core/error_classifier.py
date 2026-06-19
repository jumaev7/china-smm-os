"""Classify API errors for diagnostics (read-only)."""
from __future__ import annotations

import re
from typing import Literal

ErrorCategory = Literal[
    "schema_error",
    "migration_error",
    "validation_error",
    "api_error",
    "frontend_error",
    "unknown",
]

_SCHEMA_PATTERNS = re.compile(
    r"(undefinedcolumn|undefinedtable|relation .+ does not exist|"
    r"column .+ does not exist|no such table|missing column|schema drift)",
    re.I,
)
_MIGRATION_PATTERNS = re.compile(r"(alembic|migration|revision|upgrade head)", re.I)


def classify_error(
    *,
    method: str,
    path: str,
    status: int,
    error_summary: str | None = None,
) -> ErrorCategory:
    text = (error_summary or "").lower()

    if status == 422 or "validation error" in text or "field required" in text:
        return "validation_error"

    if _SCHEMA_PATTERNS.search(text):
        return "schema_error"

    if _MIGRATION_PATTERNS.search(text) or "migration_drift" in text:
        return "migration_error"

    if status == 0 or "cannot reach" in text or "econnaborted" in text or "network" in text:
        return "frontend_error"

    if path.startswith("/api/") or status >= 400:
        return "api_error"

    return "unknown"
