"""Narrow provider execution port for retry-command D2-A (fake-only).

Production executor receives an explicit ``RetryCommandProviderPort`` dependency.
No global ADAPTERS registry. No Telegram/Facebook/Instagram/HTTP clients.

Tests inject ``FakeProviderExecutor``. Real adapters are out of scope until a
later phase after Phase E reconciliation and F0 selector hard-exclusions.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, Protocol, runtime_checkable
from uuid import UUID

ProviderOutcome = Literal["success", "definitive_failure", "ambiguous"]


@dataclass(frozen=True)
class ProviderExecutionResult:
    """Normalized provider result. Scrubbed/minimal — no tokens or raw payloads."""

    outcome: ProviderOutcome
    external_post_id: str | None = None
    external_post_url: str | None = None
    failure_code: str | None = None
    safe_message: str | None = None
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderExecutionRequest:
    """Minimal request context for the fake/test provider boundary."""

    command_id: UUID
    resulting_attempt_id: UUID
    platform: str
    tenant_id: UUID | None = None
    correlation_id: str | None = None


@runtime_checkable
class RetryCommandProviderPort(Protocol):
    """Explicit dependency injected into the executor. No global lookup."""

    async def execute(
        self,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        """Perform exactly one provider-side action for this request.

        Implementations must not perform network I/O in D2-A fake mode.
        Callers must invoke this at most once per barrier crossing.
        """
        ...


class FakeProviderMode(str, Enum):
    """Deterministic fake-provider behaviors for tests."""

    SUCCESS = "success"
    DEFINITIVE_FAILURE = "definitive_failure"
    AMBIGUOUS = "ambiguous"
    TIMEOUT = "timeout"
    EXCEPTION = "exception"
    MALFORMED = "malformed"
    SUCCESS_MISSING_EXTERNAL_ID = "success_missing_external_id"


class FakeProviderTimeoutError(TimeoutError):
    """Trusted fake timeout — treated as ambiguous by the executor."""


class FakeProviderException(RuntimeError):
    """Generic fake provider exception — treated as ambiguous."""


class FakeProviderExecutor:
    """In-memory fake provider. No network I/O. Invocation-counted."""

    def __init__(
        self,
        mode: FakeProviderMode = FakeProviderMode.SUCCESS,
        *,
        external_post_id: str = "fake-post-1",
        external_post_url: str | None = "https://example.test/p/fake-post-1",
        failure_code: str = "fake_definitive_failure",
        safe_message: str = "Fake provider definitive failure",
        malformed_payload: Any = None,
    ) -> None:
        self.mode = mode
        self.external_post_id = external_post_id
        self.external_post_url = external_post_url
        self.failure_code = failure_code
        self.safe_message = safe_message
        self.malformed_payload = malformed_payload
        self.invocation_count = 0
        self.requests: list[ProviderExecutionRequest] = []

    async def execute(
        self,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        self.invocation_count += 1
        self.requests.append(request)

        if self.mode is FakeProviderMode.TIMEOUT:
            raise FakeProviderTimeoutError("Fake provider timeout")
        if self.mode is FakeProviderMode.EXCEPTION:
            raise FakeProviderException("Fake provider unknown exception")
        if self.mode is FakeProviderMode.MALFORMED:
            # Intentionally violate the result contract; classifier must fail closed.
            return self.malformed_payload  # type: ignore[return-value]

        if self.mode is FakeProviderMode.SUCCESS:
            return ProviderExecutionResult(
                outcome="success",
                external_post_id=self.external_post_id,
                external_post_url=self.external_post_url,
                safe_message="Fake provider success",
                provider_metadata={"fake": True},
            )
        if self.mode is FakeProviderMode.SUCCESS_MISSING_EXTERNAL_ID:
            return ProviderExecutionResult(
                outcome="success",
                external_post_id=None,
                external_post_url=self.external_post_url,
                safe_message="Fake success missing external_post_id",
                provider_metadata={"fake": True},
            )
        if self.mode is FakeProviderMode.DEFINITIVE_FAILURE:
            return ProviderExecutionResult(
                outcome="definitive_failure",
                failure_code=self.failure_code,
                safe_message=self.safe_message,
                provider_metadata={"fake": True},
            )
        # AMBIGUOUS
        return ProviderExecutionResult(
            outcome="ambiguous",
            failure_code="fake_ambiguous",
            safe_message="Fake provider ambiguous result",
            provider_metadata={"fake": True},
        )
