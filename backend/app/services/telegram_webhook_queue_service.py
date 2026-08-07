"""Durable PostgreSQL queue for Telegram webhook updates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.telegram_ingestion import TelegramWebhookEvent


class TelegramWebhookQueueService:
    MAX_ATTEMPTS = 5

    @staticmethod
    async def enqueue(db: AsyncSession, update: dict[str, Any]) -> tuple[UUID, bool]:
        update_id = update.get("update_id")
        if not isinstance(update_id, int):
            raise ValueError("Telegram update_id must be an integer")
        statement = (
            insert(TelegramWebhookEvent)
            .values(update_id=update_id, payload=update, status="pending")
            .on_conflict_do_nothing(index_elements=[TelegramWebhookEvent.update_id])
            .returning(TelegramWebhookEvent.id)
        )
        event_id = (await db.execute(statement)).scalar_one_or_none()
        if event_id is not None:
            return event_id, True
        existing = await db.scalar(
            select(TelegramWebhookEvent.id).where(TelegramWebhookEvent.update_id == update_id),
        )
        if existing is None:
            raise RuntimeError("Telegram webhook enqueue conflict could not be resolved")
        return existing, False

    @staticmethod
    async def claim_batch(
        db: AsyncSession,
        *,
        worker_id: str,
        batch_size: int = 10,
        lease_seconds: int = 180,
    ) -> list[tuple[UUID, dict[str, Any]]]:
        now = datetime.now(timezone.utc)
        eligible = or_(
            and_(
                TelegramWebhookEvent.status.in_(("pending", "retry")),
                TelegramWebhookEvent.available_at <= now,
            ),
            and_(
                TelegramWebhookEvent.status == "processing",
                TelegramWebhookEvent.lease_expires_at < now,
            ),
        )
        rows = list((await db.scalars(
            select(TelegramWebhookEvent)
            .where(eligible, TelegramWebhookEvent.attempts < TelegramWebhookQueueService.MAX_ATTEMPTS)
            .order_by(TelegramWebhookEvent.created_at.asc())
            .limit(max(1, batch_size))
            .with_for_update(skip_locked=True),
        )).all())
        lease_until = now + timedelta(seconds=max(30, lease_seconds))
        claimed: list[tuple[UUID, dict[str, Any]]] = []
        for row in rows:
            row.status = "processing"
            row.lease_owner = worker_id
            row.lease_expires_at = lease_until
            row.attempts += 1
            claimed.append((row.id, dict(row.payload)))
        await db.flush()
        return claimed

    @staticmethod
    async def mark_completed(db: AsyncSession, event_id: UUID, *, worker_id: str) -> None:
        row = await db.get(TelegramWebhookEvent, event_id)
        if row is None or row.lease_owner != worker_id:
            return
        row.status = "completed"
        row.processed_at = datetime.now(timezone.utc)
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error = None
        await db.flush()

    @staticmethod
    async def mark_failed(
        db: AsyncSession,
        event_id: UUID,
        *,
        worker_id: str,
        error: Exception,
    ) -> None:
        row = await db.get(TelegramWebhookEvent, event_id)
        if row is None or row.lease_owner != worker_id:
            return
        terminal = row.attempts >= TelegramWebhookQueueService.MAX_ATTEMPTS
        row.status = "failed" if terminal else "retry"
        row.available_at = datetime.now(timezone.utc) + timedelta(
            seconds=min(300, 2 ** max(1, row.attempts)),
        )
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error = type(error).__name__[:200]
        await db.flush()
