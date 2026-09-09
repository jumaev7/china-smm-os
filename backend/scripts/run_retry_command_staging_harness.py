"""Staging-only full fake retry-command integration harness (D2-B2a).

verify staging identity
→ create synthetic fixture
→ claim command (optional if already claimed)
→ construct staging eligibility evaluator
→ construct staging fake provider
→ execute canonical PublishRetryCommandExecutor
→ inspect command + attempt + sink evidence
→ exit

NOT a long-running worker. NO HTTP endpoint. NO real providers.
Worker remains non-executing for backend=fake (D2-B1 preserved).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import PublishRetryCommand
from app.services.publish_retry_command_claim_service import (
    PublishRetryCommandClaimService,
)
from app.services.publish_retry_command_eligibility import (
    StagingSyntheticRetryEligibility,
)
from app.services.publish_retry_command_executor import (
    ExecutorHooks,
    ExecutorResult,
    PublishRetryCommandExecutor,
)
from app.services.publish_retry_command_fake_sink import DurableFakeInvocationSink
from app.services.publish_retry_command_provider_port import FakeProviderMode
from app.services.publish_retry_command_staging_fake_factory import (
    PublishRetryCommandStagingFakeFactory,
    parse_fake_outcome_mode,
)
from app.services.publish_retry_command_staging_fixture import (
    PublishRetryCommandStagingFixtureBuilder,
    StagingRetryFixture,
)
from app.services.publish_retry_command_staging_identity import (
    RetryCommandStagingIdentityGuard,
    StagingIdentityError,
    VerifiedRetryCommandStagingContext,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class StagingHarnessResult:
    """Scrubbed harness outcome for CLI / tests."""

    executor: ExecutorResult
    command_status: str | None
    attempt_status: str | None
    attempt_retryable: bool | None
    attempt_next_retry_at_is_null: bool | None
    external_post_id: str | None
    sink_count: int
    fixture_command_id: UUID
    fixture_correlation_id: str


class PublishRetryCommandStagingHarness:
    """One-shot staging fake execution campaign."""

    def __init__(
        self,
        *,
        staging_context: VerifiedRetryCommandStagingContext,
        session_factory: async_sessionmaker[AsyncSession],
        sink_path: str | Path | None = None,
        mode: FakeProviderMode | str | None = None,
        worker_id: str | None = None,
        hooks: ExecutorHooks | None = None,
    ) -> None:
        self.staging_context = staging_context
        self.session_factory = session_factory
        self.mode = (
            parse_fake_outcome_mode(mode)
            if isinstance(mode, str) or mode is None
            else mode
        )
        if mode is None:
            self.mode = parse_fake_outcome_mode(
                settings.PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE,
            )
        self.worker_id = worker_id
        self.hooks = hooks
        if sink_path is None:
            sink_dir = Path(tempfile.gettempdir()) / "china-smm-os-staging-fake-sink"
            sink_dir.mkdir(parents=True, exist_ok=True)
            sink_path = sink_dir / "fake-invocations.jsonl"
        self.sink = DurableFakeInvocationSink(sink_path)

    async def run(
        self,
        *,
        create_fixture: bool = True,
        command_id: UUID | None = None,
        claim: bool = True,
    ) -> StagingHarnessResult:
        eligibility = StagingSyntheticRetryEligibility(self.staging_context)
        factory = PublishRetryCommandStagingFakeFactory(self.staging_context)
        provider = factory.create(mode=self.mode, sink=self.sink)

        fixture: StagingRetryFixture | None = None
        if create_fixture:
            async with self.session_factory() as db:
                builder = PublishRetryCommandStagingFixtureBuilder(self.staging_context)
                fixture = await builder.create(
                    db,
                    command_status="pending",
                    worker_id=self.worker_id,
                    commit=True,
                )
            command_id = fixture.command_id
            worker_id = fixture.worker_id
            correlation_id = fixture.correlation_id
        else:
            if command_id is None:
                raise ValueError("command_id required when create_fixture=False")
            worker_id = self.worker_id or f"staging-harness:1:{command_id}"
            correlation_id = None

        if claim and fixture is not None:
            async with self.session_factory() as db:
                # ClaimService requires gates; harness sets staging flags externally.
                results = await PublishRetryCommandClaimService.claim_batch(
                    db,
                    worker_id=worker_id,
                    batch=1,
                    commit=True,
                )
            claimed_ids = {
                r.command_id for r in results if r.kind in ("claimed", "reclaimed")
            }
            if command_id not in claimed_ids:
                # Fixture may already be claimable — force lease via direct claim path
                # by re-reading; if still pending, claim_batch should have taken it.
                async with self.session_factory() as db:
                    cmd = await db.get(PublishRetryCommand, command_id)
                    if cmd is None:
                        raise RuntimeError("fixture command missing after create")
                    if cmd.status == "pending":
                        raise RuntimeError(
                            "claim_batch did not claim synthetic fixture "
                            "(check CLAIM/WORKER/COMMANDS flags)",
                        )
                    worker_id = cmd.lease_owner or worker_id
                    correlation_id = cmd.correlation_id
        elif command_id is not None:
            async with self.session_factory() as db:
                cmd = await db.get(PublishRetryCommand, command_id)
                if cmd is None:
                    raise RuntimeError(f"command not found: {command_id}")
                worker_id = cmd.lease_owner or worker_id
                correlation_id = correlation_id or cmd.correlation_id

        assert command_id is not None
        exec_result = await PublishRetryCommandExecutor.execute(
            self.session_factory,
            command_id=command_id,
            worker_id=worker_id,
            provider=provider,
            correlation_id=correlation_id,
            eligibility_evaluator=eligibility,
            hooks=self.hooks,
        )

        async with self.session_factory() as db:
            cmd = await db.get(PublishRetryCommand, command_id)
            attempt = None
            if cmd and cmd.resulting_attempt_id:
                attempt = await db.get(PublishAttempt, cmd.resulting_attempt_id)
            return StagingHarnessResult(
                executor=exec_result,
                command_status=cmd.status if cmd else None,
                attempt_status=attempt.status if attempt else None,
                attempt_retryable=attempt.retryable if attempt else None,
                attempt_next_retry_at_is_null=(
                    attempt.next_retry_at is None if attempt else None
                ),
                external_post_id=attempt.external_post_id if attempt else None,
                sink_count=self.sink.count_for_command(command_id),
                fixture_command_id=command_id,
                fixture_correlation_id=correlation_id or "",
            )


async def _verify_and_build_harness(
    *,
    database_url: str,
    sink_path: str | None,
    mode: str | None,
) -> tuple[PublishRetryCommandStagingHarness, Any]:
    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.connect() as conn:
        staging = await RetryCommandStagingIdentityGuard.verify(conn)
    harness = PublishRetryCommandStagingHarness(
        staging_context=staging,
        session_factory=session_factory,
        sink_path=sink_path,
        mode=mode,
    )
    return harness, engine


async def amain(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Staging-only retry-command fake execution harness (D2-B2a)",
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override DATABASE_URL (must resolve to china_smm_os_staging)",
    )
    parser.add_argument(
        "--sink-path",
        default=None,
        help="Append-only fake invocation sink path (staging/test only)",
    )
    parser.add_argument(
        "--mode",
        default=None,
        help="Fake outcome mode (success|definitive_failure|ambiguous|...)",
    )
    parser.add_argument(
        "--command-id",
        default=None,
        help="Reuse existing claimed/pending command UUID (skip fixture create)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    database_url = args.database_url or settings.DATABASE_URL
    try:
        harness, engine = await _verify_and_build_harness(
            database_url=database_url,
            sink_path=args.sink_path,
            mode=args.mode,
        )
    except StagingIdentityError as exc:
        logger.error("[StagingHarness] identity failed: %s", exc)
        return 2

    try:
        if args.command_id:
            result = await harness.run(
                create_fixture=False,
                command_id=UUID(args.command_id),
                claim=False,
            )
        else:
            result = await harness.run(create_fixture=True, claim=True)
    finally:
        await engine.dispose()

    payload = {
        "executor_outcome": result.executor.outcome,
        "executor_ok": result.executor.ok,
        "command_status": result.command_status,
        "attempt_status": result.attempt_status,
        "retryable": result.attempt_retryable,
        "next_retry_at_is_null": result.attempt_next_retry_at_is_null,
        "external_post_id": result.external_post_id,
        "sink_count": result.sink_count,
        "command_id": str(result.fixture_command_id),
        "correlation_id": result.fixture_correlation_id,
        "provider_invoked": result.executor.provider_invoked,
        "provider_invocation_count": result.executor.provider_invocation_count,
    }
    print(payload)
    return 0 if result.executor.ok else 1


def main() -> None:
    raise SystemExit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
