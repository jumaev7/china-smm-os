"""Internal schemas for AI content adaptation."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


@dataclass
class AdaptRequest:
    content_id: UUID
    platforms: list[str] | None = None
    locales: list[str] | None = None
    length_profiles: list[str] | None = None
    brand_profile_version_id: UUID | None = None
    approved_template_ids: list[UUID] | None = None
    quality_mode: str | None = None
    idempotency_key: str | None = None


@dataclass
class ProtectedFact:
    category: str
    token: str
    mandatory: bool = False
    source_reference: str | None = None


@dataclass
class FactualValidationResult:
    status: str  # passed | failed | warnings
    checks: dict[str, str] = field(default_factory=dict)
    preserved: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class BuiltContext:
    messages: list[dict[str, str]]
    metadata: dict[str, Any]
    fingerprint: str
    redacted_snapshot: dict[str, Any]
    protected_facts: list[ProtectedFact]
    injection_flagged: bool
    injection_categories: list[str]
    redaction_categories: list[str]
    redaction_count: int
