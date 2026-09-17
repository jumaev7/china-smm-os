"""I2b — intent-only publication request acceptance schemas.

Acceptance creates a durable request + publication_intent_id.
It does NOT authorize or execute provider writes.
"""
from __future__ import annotations

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

PublicationRequestOperation = Literal["initial_publish", "intentional_republish"]


class IntentionalPublicationRequestCreate(BaseModel):
    """Body for POST /publishing/intentional-publication-requests."""

    content_id: UUID
    platform: str = Field(..., min_length=1, max_length=20)
    account_id: Optional[UUID] = None
    operation: PublicationRequestOperation
    client_idempotency_key: str = Field(..., min_length=1, max_length=255)
    expected_publish_version: str = Field(..., min_length=1, max_length=64)

    @field_validator("platform")
    @classmethod
    def _normalize_platform(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if not normalized:
            raise ValueError("platform is required")
        return normalized

    @field_validator("client_idempotency_key")
    @classmethod
    def _require_nonempty_key(cls, value: str) -> str:
        key = (value or "").strip()
        if not key:
            raise ValueError("client_idempotency_key must be non-empty")
        return key

    @field_validator("expected_publish_version")
    @classmethod
    def _require_version(cls, value: str) -> str:
        version = (value or "").strip()
        if not version:
            raise ValueError("expected_publish_version must be non-empty")
        return version


class IntentionalPublicationRequestResponse(BaseModel):
    """Accepted-operation response — never a provider success claim."""

    request_id: UUID
    publication_intent_id: UUID
    status: Literal["accepted"] = "accepted"
    accepted: bool = True
    idempotent_replay: bool
    operation: PublicationRequestOperation
    content_id: UUID
    platform: str
    account_id: Optional[UUID] = None
    publish_version: str
    request_fingerprint: str
    # Explicitly false forever in I2b — write auth is a later stage.
    write_authorized: bool = False
    prior_live_success: bool = False
    acceptance_note: str = (
        "Request accepted as a durable business intention only. "
        "Acceptance does not authorize provider write, republishing, "
        "registry mutation, or publication execution."
    )
