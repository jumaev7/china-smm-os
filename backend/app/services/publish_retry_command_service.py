"""Durable publish-retry command foundation (Phase 3C.1B).

Creates / collapses operator retry intent without provider I/O, PublishService
calls, resulting attempts, alerts, or Telegram/Meta side effects.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.models.client import Client
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.models.publish_retry_command import (
    RETRY_COMMAND_ACTIVE_STATUSES,
    RETRY_COMMAND_SOURCES,
    RETRY_COMMAND_TERMINAL_STATUSES,
    PublishRetryCommand,
)
from app.services.manual_retry_eligibility import (
    build_manual_retry_live_state,
    evaluate_manual_retry_eligibility,
    log_manual_retry_denied,
)
from app.services.platform_audit_service import PlatformAuditService
from app.services.publishing_tenant_scope import tenant_id_for_content_optional

logger = logging.getLogger(__name__)

OutcomeKind = Literal[
    "created",
    "active_reuse",
    "terminal_reuse",
    "terminal_failed_closed",
    "denied",
    "disabled",
]


@dataclass(frozen=True)
class PublishRetryCommandResult:
    ok: bool
    outcome: OutcomeKind
    created: bool
    command: PublishRetryCommand | None = None
    reason_code: str | None = None
    message: str | None = None
    eligibility_reason_code: str | None = None
    safety_class: str | None = None


def build_retry_command_idempotency_key(
    *,
    tenant_id: UUID,
    content_id: UUID,
    platform: str,
    publishing_account_id: UUID | None,
    publish_version: str,
    original_attempt_id: UUID,
) -> str:
    """Server-owned deterministic command identity. Never trust client keys."""
    account_part = str(publishing_account_id) if publishing_account_id else "none"
    plat = (platform or "").strip().lower() or "unknown"
    version = (publish_version or "").strip() or "unknown"
    return (
        f"{tenant_id}:{content_id}:{plat}:{account_part}:{version}:{original_attempt_id}"
    )


def build_destination_key(*, platform: str, publishing_account_id: UUID | None) -> str:
    account_part = str(publishing_account_id) if publishing_account_id else "none"
    plat = (platform or "").strip().lower() or "unknown"
    return f"{plat}:{account_part}"


def serialize_retry_command(command: PublishRetryCommand) -> dict[str, Any]:
    """Safe client-facing command metadata (no lease owner, secrets, or raw traces)."""
    return {
        "command_id": command.id,
        "status": command.status,
        "platform": command.platform,
        "original_attempt_id": command.original_attempt_id,
        "resulting_attempt_id": command.resulting_attempt_id,
        "content_id": command.content_id,
        "client_id": command.client_id,
        "requested_source": command.requested_source,
        "reason_code": command.reason_code,
        "provider_outcome": command.provider_outcome,
        "publish_version": command.publish_version,
        "destination_key": command.destination_key,
        "correlation_id": command.correlation_id,
        "created_at": command.created_at,
        "claimed_at": command.claimed_at,
        "provider_write_started_at": command.provider_write_started_at,
        "finished_at": command.finished_at,
    }


class PublishRetryCommandService:
    """Create-or-get durable retry commands. No provider writes in 3C.1B."""

    @classmethod
    async def create_or_get_command(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        original_attempt_id: UUID,
        actor_id: UUID | None = None,
        source: str = "admin",
        actor_role: str | None = None,
        skip_eligibility: bool = False,
        commit: bool = True,
    ) -> PublishRetryCommandResult:
        """Persist retry intent when eligibility allows.

        Never calls PublishService, adapters, manual_retry, or alert/Telegram paths.
        ``resulting_attempt_id`` remains NULL.
        """
        if not settings.PUBLISH_RETRY_COMMANDS_ENABLED:
            return PublishRetryCommandResult(
                ok=False,
                outcome="disabled",
                created=False,
                reason_code="commands_disabled",
                message="Publish retry commands are disabled",
            )

        src = (source or "admin").strip().lower()
        if src not in RETRY_COMMAND_SOURCES:
            src = "api"

        attempt, content, client = await cls._load_attempt_bundle(
            db, original_attempt_id, tenant_id=tenant_id,
        )

        if client.tenant_id != tenant_id:
            raise HTTPException(status_code=404, detail="Publish attempt not found")
        if content.client_id != client.id:
            raise HTTPException(status_code=404, detail="Publish attempt not found")
        if attempt.content_id != content.id:
            raise HTTPException(status_code=404, detail="Publish attempt not found")

        if not skip_eligibility:
            live_state = await build_manual_retry_live_state(db, attempt, content=content)
            eligibility = evaluate_manual_retry_eligibility(
                attempt,
                live_state,
                source=src if src != "api" else "admin",
                actor_role=actor_role,
            )
            if not eligibility.allowed:
                log_manual_retry_denied(
                    eligibility,
                    attempt_id=original_attempt_id,
                    tenant_id=tenant_id,
                    source=src,
                )
                return PublishRetryCommandResult(
                    ok=False,
                    outcome="denied",
                    created=False,
                    reason_code=eligibility.reason_code,
                    message=eligibility.operator_message or "Manual retry unavailable",
                    eligibility_reason_code=eligibility.reason_code,
                    safety_class=eligibility.safety_class,
                )

        publish_version = (attempt.publish_version or "").strip() or "unknown"
        platform = (attempt.platform or "").strip().lower()
        account_id = attempt.account_id
        idempotency_key = build_retry_command_idempotency_key(
            tenant_id=tenant_id,
            content_id=attempt.content_id,
            platform=platform,
            publishing_account_id=account_id,
            publish_version=publish_version,
            original_attempt_id=attempt.id,
        )
        destination_key = build_destination_key(
            platform=platform,
            publishing_account_id=account_id,
        )

        existing = await cls._find_by_idempotency(db, tenant_id, idempotency_key)
        if existing is not None:
            return cls._result_for_existing(existing)

        command = PublishRetryCommand(
            id=uuid4(),
            tenant_id=tenant_id,
            client_id=client.id,
            content_id=attempt.content_id,
            original_attempt_id=attempt.id,
            resulting_attempt_id=None,
            platform=platform,
            publishing_account_id=account_id,
            publish_version=publish_version,
            destination_key=destination_key,
            requested_by=actor_id,
            requested_source=src,
            idempotency_key=idempotency_key,
            status="pending",
            reason_code=None,
            provider_outcome=None,
            correlation_id=str(uuid4()),
        )

        try:
            begin_nested = getattr(db, "begin_nested", None)
            if begin_nested is not None:
                async with db.begin_nested():
                    db.add(command)
                    await db.flush()
            else:
                db.add(command)
                await db.flush()
        except IntegrityError:
            raced = await cls._find_by_idempotency(db, tenant_id, idempotency_key)
            if raced is None:
                # Active unique index only covers active statuses; reload any row.
                raced = await cls._find_any_by_idempotency(db, tenant_id, idempotency_key)
            if raced is None:
                raise
            logger.info(
                "[PublishRetryCommand] concurrent collapse key=%s command_id=%s status=%s",
                idempotency_key,
                raced.id,
                raced.status,
            )
            return cls._result_for_existing(raced)

        await PlatformAuditService.record(
            db,
            actor_type="tenant_user" if actor_id else "system",
            actor_id=actor_id,
            tenant_id=tenant_id,
            event_type="publishing.retry_command_created",
            resource_type="publish_retry_command",
            resource_id=str(command.id),
            details={
                "command_id": str(command.id),
                "original_attempt_id": str(attempt.id),
                "content_id": str(attempt.content_id),
                "platform": platform,
                "publishing_account_id": str(account_id) if account_id else None,
                "publish_version": publish_version,
                "source": src,
                "actor_id": str(actor_id) if actor_id else None,
                "status": "pending",
                "correlation_id": command.correlation_id,
            },
            commit=False,
        )

        if commit:
            await db.commit()
            await db.refresh(command)
        else:
            await db.flush()

        logger.info(
            "[PublishRetryCommand] created command_id=%s attempt=%s tenant=%s source=%s",
            command.id,
            attempt.id,
            tenant_id,
            src,
        )
        return PublishRetryCommandResult(
            ok=True,
            outcome="created",
            created=True,
            command=command,
        )

    @classmethod
    async def get_command(
        cls,
        db: AsyncSession,
        command_id: UUID,
        *,
        tenant_id: UUID,
    ) -> PublishRetryCommand:
        row = (
            await db.execute(
                select(PublishRetryCommand).where(
                    PublishRetryCommand.id == command_id,
                    PublishRetryCommand.tenant_id == tenant_id,
                ),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Retry command not found")
        return row

    @classmethod
    def _result_for_existing(cls, existing: PublishRetryCommand) -> PublishRetryCommandResult:
        status = existing.status
        if status in RETRY_COMMAND_ACTIVE_STATUSES:
            logger.info(
                "[PublishRetryCommand] active reuse command_id=%s status=%s",
                existing.id,
                status,
            )
            return PublishRetryCommandResult(
                ok=True,
                outcome="active_reuse",
                created=False,
                command=existing,
                reason_code="active_command_exists",
                message="Active retry command already exists",
            )
        if status == "failed":
            return PublishRetryCommandResult(
                ok=False,
                outcome="terminal_failed_closed",
                created=False,
                command=existing,
                reason_code="terminal_failed_command",
                message=(
                    "A failed retry command already exists for this identity; "
                    "automatic re-create is fail-closed in 3C.1B"
                ),
            )
        if status in RETRY_COMMAND_TERMINAL_STATUSES:
            return PublishRetryCommandResult(
                ok=True,
                outcome="terminal_reuse",
                created=False,
                command=existing,
                reason_code=f"terminal_{status}",
                message=f"Terminal retry command already exists ({status})",
            )
        # Unknown status — fail closed
        return PublishRetryCommandResult(
            ok=False,
            outcome="denied",
            created=False,
            command=existing,
            reason_code="unknown_command_status",
            message="Retry command is in an unexpected status",
        )

    @classmethod
    async def _find_by_idempotency(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> PublishRetryCommand | None:
        """Prefer active row; otherwise return any same-key row for terminal policy."""
        active = (
            await db.execute(
                select(PublishRetryCommand).where(
                    PublishRetryCommand.tenant_id == tenant_id,
                    PublishRetryCommand.idempotency_key == idempotency_key,
                    PublishRetryCommand.status.in_(tuple(RETRY_COMMAND_ACTIVE_STATUSES)),
                ),
            )
        ).scalar_one_or_none()
        if active is not None:
            return active
        return await cls._find_any_by_idempotency(db, tenant_id, idempotency_key)

    @classmethod
    async def _find_any_by_idempotency(
        cls,
        db: AsyncSession,
        tenant_id: UUID,
        idempotency_key: str,
    ) -> PublishRetryCommand | None:
        return (
            await db.execute(
                select(PublishRetryCommand)
                .where(
                    PublishRetryCommand.tenant_id == tenant_id,
                    PublishRetryCommand.idempotency_key == idempotency_key,
                )
                .order_by(PublishRetryCommand.created_at.desc()),
            )
        ).scalars().first()

    @classmethod
    async def _load_attempt_bundle(
        cls,
        db: AsyncSession,
        attempt_id: UUID,
        *,
        tenant_id: UUID,
    ) -> tuple[PublishAttempt, ContentItem, Client]:
        result = await db.execute(
            select(PublishAttempt, ContentItem, Client)
            .join(ContentItem, ContentItem.id == PublishAttempt.content_id)
            .join(Client, Client.id == ContentItem.client_id)
            .where(PublishAttempt.id == attempt_id)
            .where(Client.tenant_id == tenant_id)
            .options(selectinload(PublishAttempt.account))
        )
        row = result.one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Publish attempt not found")
        attempt, content, client = row
        content_tenant = await tenant_id_for_content_optional(db, content)
        if content_tenant != tenant_id:
            raise HTTPException(status_code=404, detail="Publish attempt not found")
        return attempt, content, client
