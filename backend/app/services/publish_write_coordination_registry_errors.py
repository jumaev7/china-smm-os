"""Domain conflicts for the dormant publish-write coordination registry (R2).

No provider payloads or credentials are attached to these types.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID


class PublishWriteCoordinationError(Exception):
    """Base coordination conflict / policy failure."""

    code: str = "publish_write_coordination_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})
        self.registry_id: UUID | None = self.details.get("registry_id")
        self.logical_write_key: str | None = self.details.get("logical_write_key")
        self.state: str | None = self.details.get("state")
        self.generation: int | None = self.details.get("generation")
        self.version: int | None = self.details.get("version")


class AuthorityAlreadyReserved(PublishWriteCoordinationError):
    code = "authority_already_reserved"


class LeaseStillActive(PublishWriteCoordinationError):
    code = "lease_still_active"


class UnresolvedWriteConflict(PublishWriteCoordinationError):
    code = "unresolved_write_conflict"


class AlreadySucceeded(PublishWriteCoordinationError):
    code = "already_succeeded"


class IntentSuperseded(PublishWriteCoordinationError):
    code = "intent_superseded"


class StaleGeneration(PublishWriteCoordinationError):
    code = "stale_generation"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.expected_generation: int | None = self.details.get("expected_generation")


class StaleVersion(PublishWriteCoordinationError):
    code = "stale_version"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.expected_version: int | None = self.details.get("expected_version")


class OwnerMismatch(PublishWriteCoordinationError):
    code = "owner_mismatch"


class InvalidStateTransition(PublishWriteCoordinationError):
    code = "invalid_state_transition"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details=details)
        self.from_state: str | None = self.details.get("from_state")
        self.to_state: str | None = self.details.get("to_state")


class RegistryRowNotFound(PublishWriteCoordinationError):
    code = "registry_row_not_found"
