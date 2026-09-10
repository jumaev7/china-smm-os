"""Staging fake worker bootstrap (Phase 3C.1C-D2-B2b1-A).

Owns the ONLY path that may approve ``backend=fake`` for the long-running
PublishRetryCommandWorker:

  verify backend=fake request
  → RetryCommandStagingIdentityGuard (live current_database)
  → VerifiedRetryCommandStagingContext
  → StagingSyntheticRetryEligibility
  → DurableFakeInvocationSink
  → process-global fake RetryCommandProviderPort
  → immutable RetryCommandWorkerExecutionContext

Any failure must abort BEFORE worker construction / poll / claim.

Generic PublishRetryCommandWorker must not import this module's identity
policy (APP_ENV / DB names / provider-secret checks). It only consumes the
frozen execution context after bootstrap succeeds.
"""
from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession

from app.core.config import settings
from app.services.publish_retry_command_eligibility import (
    RetryCommandEligibilityEvaluator,
    StagingSyntheticRetryEligibility,
)
from app.services.publish_retry_command_executor import (
    ExecutorHooks,
    ExecutorResult,
    PublishRetryCommandExecutor,
    StopBeforeBarrierFn,
)
from app.services.publish_retry_command_fake_sink import DurableFakeInvocationSink
from app.services.publish_retry_command_provider_port import RetryCommandProviderPort
from app.services.publish_retry_command_staging_fake_factory import (
    PublishRetryCommandStagingFakeFactory,
    parse_fake_outcome_mode,
)
from app.services.publish_retry_command_staging_identity import (
    StagingIdentityError,
    VerifiedRetryCommandStagingContext,
    assert_verified_staging_context,
    RetryCommandStagingIdentityGuard,
)

logger = logging.getLogger(__name__)

REQUIRED_FAKE_BATCH_SIZE: Literal[1] = 1


class StagingWorkerBootstrapError(RuntimeError):
    """Fail-closed staging worker bootstrap denial (before claim)."""

    def __init__(self, reason: str, *, detail: str | None = None) -> None:
        self.reason = reason
        self.detail = detail
        message = reason if detail is None else f"{reason}: {detail}"
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class RetryCommandWorkerExecutionContext:
    """Immutable verified fake-execution context for one worker process.

    Half-valid fake contexts are not constructible outside bootstrap.
    ``backend=none`` workers use ``execution=None`` instead.
    """

    execution_backend: Literal["fake"]
    staging_context: VerifiedRetryCommandStagingContext
    eligibility_evaluator: RetryCommandEligibilityEvaluator
    provider: RetryCommandProviderPort
    sink: DurableFakeInvocationSink | None
    hooks: ExecutorHooks | None

    def __post_init__(self) -> None:
        if self.execution_backend != "fake":
            raise StagingWorkerBootstrapError(
                "execution_backend_not_fake",
                detail=f"got {self.execution_backend!r}",
            )
        try:
            assert_verified_staging_context(
                self.staging_context,
                what="RetryCommandWorkerExecutionContext",
            )
        except StagingIdentityError as exc:
            raise StagingWorkerBootstrapError(
                exc.reason,
                detail=exc.detail,
            ) from exc
        if self.eligibility_evaluator is None or self.provider is None:
            raise StagingWorkerBootstrapError("incomplete_fake_execution_context")

    async def execute_claimed(
        self,
        session_factory,
        *,
        command_id: UUID,
        worker_id: str,
        correlation_id: str | None = None,
        should_stop_before_barrier: StopBeforeBarrierFn | None = None,
    ) -> ExecutorResult:
        """Worker→executor handoff. Reloads canonical state inside executor."""
        return await PublishRetryCommandExecutor.execute(
            session_factory,
            command_id=command_id,
            worker_id=worker_id,
            provider=self.provider,
            correlation_id=correlation_id,
            eligibility_evaluator=self.eligibility_evaluator,
            hooks=self.hooks,
            should_stop_before_barrier=should_stop_before_barrier,
        )


def build_staging_marker_hooks(marker_dir: str | Path) -> ExecutorHooks:
    """DI-only file markers for external SIGTERM coordination (staging).

    Written only when bootstrap injects these hooks after verified identity.
    Not failpoints; not read by prep/barrier/finalizer/executor control flow.
    """
    root = Path(marker_dir)
    root.mkdir(parents=True, exist_ok=True)

    def _marker(name: str) -> Callable[[], None]:
        def _write() -> None:
            path = root / name
            path.write_text("1\n", encoding="utf-8")

        return _write

    return ExecutorHooks(
        after_prepare=_marker("after_prepare"),
        after_barrier=_marker("after_barrier"),
        before_provider=_marker("before_provider"),
        after_provider=_marker("after_provider"),
        before_finalize=_marker("before_finalize"),
    )


def _default_sink_path() -> Path:
    sink_dir = Path(tempfile.gettempdir()) / "china-smm-os-staging-fake-sink"
    sink_dir.mkdir(parents=True, exist_ok=True)
    return sink_dir / "fake-invocations.jsonl"


def _resolve_sink_path(explicit: str | Path | None) -> Path:
    if explicit is not None:
        return Path(explicit)
    configured = getattr(settings, "PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH", None)
    if configured is not None and str(configured).strip():
        return Path(str(configured).strip())
    return _default_sink_path()


async def bootstrap_staging_fake_worker_execution(
    connectable: AsyncSession | AsyncConnection | AsyncEngine,
    *,
    requested_backend: str | None = None,
    sink_path: str | Path | None = None,
    hooks: ExecutorHooks | None = None,
    settings_obj: Any | None = None,
    environ: dict[str, str] | None = None,
    create_sink: bool = True,
) -> RetryCommandWorkerExecutionContext:
    """Build immutable fake execution context or fail before claim.

    Requires authoritative staging identity via live ``current_database()``.
    Constructs one process-global fake provider + staging eligibility instance.
    """
    cfg = settings_obj if settings_obj is not None else settings
    backend_raw = (
        requested_backend
        if requested_backend is not None
        else getattr(cfg, "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND", None)
    )
    backend = str(backend_raw or "").strip().lower()
    if backend != "fake":
        raise StagingWorkerBootstrapError(
            "backend_not_fake",
            detail=f"bootstrap requires backend=fake (got {backend!r})",
        )

    batch = int(getattr(cfg, "PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE", 1) or 0)
    if batch != REQUIRED_FAKE_BATCH_SIZE:
        raise StagingWorkerBootstrapError(
            "batch_size_not_one",
            detail=(
                "staging fake worker requires "
                f"PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE={REQUIRED_FAKE_BATCH_SIZE} "
                f"(got {batch})"
            ),
        )

    try:
        staging_context = await RetryCommandStagingIdentityGuard.verify(
            connectable,
            execution_backend="fake",
            settings_obj=cfg,
            environ=environ,
        )
    except StagingIdentityError as exc:
        raise StagingWorkerBootstrapError(
            exc.reason,
            detail=exc.detail,
        ) from exc

    # Marker hooks only after verified identity (DI; not env failpoints).
    resolved_hooks = hooks
    if resolved_hooks is None:
        marker_raw = getattr(cfg, "PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR", None)
        if marker_raw is not None and str(marker_raw).strip():
            resolved_hooks = build_staging_marker_hooks(str(marker_raw).strip())

    eligibility = StagingSyntheticRetryEligibility(staging_context)
    sink: DurableFakeInvocationSink | None = None
    if create_sink:
        sink = DurableFakeInvocationSink(_resolve_sink_path(sink_path))

    mode = parse_fake_outcome_mode(
        getattr(cfg, "PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE", "success"),
    )
    provider = PublishRetryCommandStagingFakeFactory(staging_context).create(
        mode=mode,
        sink=sink,
    )

    context = RetryCommandWorkerExecutionContext(
        execution_backend="fake",
        staging_context=staging_context,
        eligibility_evaluator=eligibility,
        provider=provider,
        sink=sink,
        hooks=resolved_hooks,
    )
    logger.info(
        "[RetryCommandStagingBootstrap] verified fake worker context "
        "db=%s mode=%s batch=%s",
        staging_context.current_database,
        mode.value,
        batch,
    )
    return context
