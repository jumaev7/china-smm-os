"""Staging-only fake provider factory (Phase 3C.1C-D2-B2a).

Requires VerifiedRetryCommandStagingContext. Returns RetryCommandProviderPort.
No factory resolution without verified capability. No ADAPTERS. No real
providers. No dynamic import by platform.

Worker must NOT use this factory in D2-B2a (harness only).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.config import settings
from app.services.publish_retry_command_fake_sink import (
    DurableFakeInvocationSink,
    FakeInvocationSinkError,
)
from app.services.publish_retry_command_provider_port import (
    FakeProviderException,
    FakeProviderExecutor,
    FakeProviderMode,
    FakeProviderTimeoutError,
    ProviderExecutionRequest,
    ProviderExecutionResult,
    RetryCommandProviderPort,
)
from app.services.publish_retry_command_staging_identity import (
    VerifiedRetryCommandStagingContext,
    assert_verified_staging_context,
)

FAKE_EXTERNAL_ID_PREFIX = "fake:retry-command:"


def build_fake_external_post_id(command_id: UUID, attempt_id: UUID) -> str:
    """Unmistakable fake success ID — never provider-like numeric."""
    return f"{FAKE_EXTERNAL_ID_PREFIX}{command_id}:{attempt_id}"


def parse_fake_outcome_mode(raw: str | None) -> FakeProviderMode:
    """Map env/CLI string to FakeProviderMode. Unknown → fail closed."""
    text = str(raw or "success").strip().lower()
    try:
        return FakeProviderMode(text)
    except ValueError as exc:
        raise ValueError(
            f"unsupported PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE={raw!r}",
        ) from exc


class StagingFakeProviderExecutor:
    """Staging fake provider with namespaced IDs + optional durable sink.

    Sink write happens BEFORE the modeled fake effect. If sink write fails,
    execution fails closed (ambiguous/exception) — no automatic retry.
    Sink is never consulted to authorize replay.
    """

    def __init__(
        self,
        *,
        staging_context: VerifiedRetryCommandStagingContext,
        mode: FakeProviderMode = FakeProviderMode.SUCCESS,
        sink: DurableFakeInvocationSink | None = None,
        fail_sink_before_effect: bool = False,
    ) -> None:
        self._staging = assert_verified_staging_context(
            staging_context,
            what="StagingFakeProviderExecutor",
        )
        self.mode = mode
        self.sink = sink
        self.fail_sink_before_effect = fail_sink_before_effect
        self.invocation_count = 0
        self.requests: list[ProviderExecutionRequest] = []
        # Inner fake for non-success ID modes; success IDs are overridden.
        self._inner = FakeProviderExecutor(mode=mode)

    async def execute(
        self,
        request: ProviderExecutionRequest,
    ) -> ProviderExecutionResult:
        self.invocation_count += 1
        self.requests.append(request)

        # Durable evidence BEFORE modeled effect (observation only).
        if self.sink is not None:
            if self.fail_sink_before_effect:
                raise FakeInvocationSinkError(
                    "injected sink failure before fake effect",
                )
            try:
                self.sink.append(
                    command_id=request.command_id,
                    attempt_id=request.resulting_attempt_id,
                    fake_mode=self.mode.value,
                    invocation_ordinal=self.invocation_count,
                )
            except FakeInvocationSinkError:
                # Cannot determine durable observation — fail closed, no retry.
                raise

        if self.mode is FakeProviderMode.TIMEOUT:
            raise FakeProviderTimeoutError("Fake provider timeout")
        if self.mode is FakeProviderMode.EXCEPTION:
            raise FakeProviderException("Fake provider unknown exception")
        if self.mode is FakeProviderMode.MALFORMED:
            return None  # type: ignore[return-value]

        if self.mode is FakeProviderMode.SUCCESS:
            return ProviderExecutionResult(
                outcome="success",
                external_post_id=build_fake_external_post_id(
                    request.command_id,
                    request.resulting_attempt_id,
                ),
                external_post_url=None,  # omit — no provider-like URL
                safe_message="Staging fake provider success",
                provider_metadata={"fake": True, "staging": True},
            )
        if self.mode is FakeProviderMode.SUCCESS_MISSING_EXTERNAL_ID:
            return ProviderExecutionResult(
                outcome="success",
                external_post_id=None,
                external_post_url=None,
                safe_message="Staging fake success missing external_post_id",
                provider_metadata={"fake": True, "staging": True},
            )
        if self.mode is FakeProviderMode.DEFINITIVE_FAILURE:
            return ProviderExecutionResult(
                outcome="definitive_failure",
                failure_code="fake_definitive_failure",
                safe_message="Staging fake provider definitive failure",
                provider_metadata={"fake": True, "staging": True},
            )
        return ProviderExecutionResult(
            outcome="ambiguous",
            failure_code="fake_ambiguous",
            safe_message="Staging fake provider ambiguous result",
            provider_metadata={"fake": True, "staging": True},
        )


class PublishRetryCommandStagingFakeFactory:
    """Construct staging fake providers only with verified capability."""

    def __init__(self, staging_context: VerifiedRetryCommandStagingContext) -> None:
        self._staging = assert_verified_staging_context(
            staging_context,
            what="PublishRetryCommandStagingFakeFactory",
        )

    @property
    def staging_context(self) -> VerifiedRetryCommandStagingContext:
        return self._staging

    def create(
        self,
        *,
        mode: FakeProviderMode | str | None = None,
        sink: DurableFakeInvocationSink | None = None,
        fail_sink_before_effect: bool = False,
    ) -> RetryCommandProviderPort:
        if isinstance(mode, FakeProviderMode):
            resolved = mode
        elif mode is None:
            resolved = parse_fake_outcome_mode(
                getattr(settings, "PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE", "success"),
            )
        elif isinstance(mode, str):
            resolved = parse_fake_outcome_mode(mode)
        else:
            raise TypeError(f"unsupported fake mode type: {type(mode)!r}")
        return StagingFakeProviderExecutor(
            staging_context=self._staging,
            mode=resolved,
            sink=sink,
            fail_sink_before_effect=fail_sink_before_effect,
        )


def resolve_staging_fake_backend(
    *,
    staging_context: VerifiedRetryCommandStagingContext | None,
    requested_backend: str | None = None,
) -> RetryCommandProviderPort | None:
    """Resolve fake backend ONLY through verified staging context.

    none → None (safe stop signal for callers)
    fake → requires verified context; returns provider port
    telegram/facebook/instagram/real → fail closed
    unknown → fail closed

    Does not import ADAPTERS or real publishers.
    """
    from app.services.publish_retry_command_execution_backend import (
        UNSUPPORTED_REAL_BACKENDS,
        normalize_execution_backend,
    )

    value = normalize_execution_backend(
        requested_backend
        if requested_backend is not None
        else settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND,
    )
    if value == "none":
        return None
    if value == "fake":
        ctx = assert_verified_staging_context(
            staging_context,
            what="fake backend resolution",
        )
        return PublishRetryCommandStagingFakeFactory(ctx).create()
    if value in UNSUPPORTED_REAL_BACKENDS:
        raise RuntimeError(f"real provider backend unsupported: {value}")
    raise RuntimeError(f"invalid execution backend: {value}")
