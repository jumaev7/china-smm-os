"""Persistence helpers for publish_write_coordination_registry (R2).

Repository owns fetch / lock / insert / conditional update / destination
lookups. State-machine policy lives in the service layer.

Lock ordering for mutating paths (service-enforced):
  1. destination advisory xact lock
  2. fetch/create registry row (FOR UPDATE)
  3. CAS / conditional update
  4. commit (caller-owned; never span provider I/O)
"""
from __future__ import annotations

from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy import Select, and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publish_write_coordination_registry import (
    PublishWriteCoordinationRegistry,
    build_logical_write_key,
)
from app.services.publish_write_coordination import DestinationIdentity

UNRESOLVED_REGISTRY_STATES: frozenset[str] = frozenset({"WRITE_STARTED", "AMBIGUOUS"})
DURABLE_SUCCESS_STATES: frozenset[str] = frozenset({"SUCCEEDED", "RESOLVED_SUCCEEDED"})


class PublishWriteCoordinationRegistryRepository:
    """Conflict-safe persistence for registry rows. No transition policy."""

    @staticmethod
    def logical_write_key_for(
        destination: DestinationIdentity,
        publication_intent_id: UUID,
    ) -> str:
        return build_logical_write_key(
            destination.tenant_id,
            destination.content_id,
            destination.platform_normalized,
            destination.account_id,
            publication_intent_id,
        )

    @classmethod
    async def get_by_id(
        cls,
        db: AsyncSession,
        registry_id: UUID,
        *,
        for_update: bool = False,
    ) -> PublishWriteCoordinationRegistry | None:
        stmt: Select[tuple[PublishWriteCoordinationRegistry]] = select(
            PublishWriteCoordinationRegistry
        ).where(PublishWriteCoordinationRegistry.id == registry_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def get_by_logical_write_key(
        cls,
        db: AsyncSession,
        logical_write_key: str,
        *,
        for_update: bool = False,
    ) -> PublishWriteCoordinationRegistry | None:
        stmt: Select[tuple[PublishWriteCoordinationRegistry]] = select(
            PublishWriteCoordinationRegistry
        ).where(
            PublishWriteCoordinationRegistry.logical_write_key == logical_write_key
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def get_by_destination_intent(
        cls,
        db: AsyncSession,
        destination: DestinationIdentity,
        publication_intent_id: UUID,
        *,
        for_update: bool = False,
    ) -> PublishWriteCoordinationRegistry | None:
        plat = destination.platform_normalized
        conds = [
            PublishWriteCoordinationRegistry.tenant_id == destination.tenant_id,
            PublishWriteCoordinationRegistry.content_id == destination.content_id,
            PublishWriteCoordinationRegistry.platform == plat,
            PublishWriteCoordinationRegistry.publication_intent_id
            == publication_intent_id,
        ]
        if destination.account_id is None:
            conds.append(PublishWriteCoordinationRegistry.account_id.is_(None))
        else:
            conds.append(
                PublishWriteCoordinationRegistry.account_id == destination.account_id
            )
        stmt: Select[tuple[PublishWriteCoordinationRegistry]] = select(
            PublishWriteCoordinationRegistry
        ).where(and_(*conds))
        if for_update:
            stmt = stmt.with_for_update()
        return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def insert_row(
        cls,
        db: AsyncSession,
        row: PublishWriteCoordinationRegistry,
    ) -> PublishWriteCoordinationRegistry:
        db.add(row)
        await db.flush()
        return row

    @classmethod
    async def cas_update_fields(
        cls,
        db: AsyncSession,
        row: PublishWriteCoordinationRegistry,
        *,
        expected_version: int,
        **fields: object,
    ) -> bool:
        """Apply in-memory field updates if ``row.version`` still matches.

        Caller must hold a locked row. Returns False on version mismatch
        without mutating. Successful mutation increments ``version`` by 1.
        """
        if row.version != expected_version:
            return False
        for key, value in fields.items():
            setattr(row, key, value)
        row.version = expected_version + 1
        await db.flush()
        return True

    @classmethod
    async def find_unresolved_for_destination(
        cls,
        db: AsyncSession,
        destination: DestinationIdentity,
    ) -> Sequence[PublishWriteCoordinationRegistry]:
        """Cross-intent / cross-version unresolved registry rows for destination.

        Read-only. Unsafe states: WRITE_STARTED, AMBIGUOUS.
        """
        plat = destination.platform_normalized
        conds = [
            PublishWriteCoordinationRegistry.tenant_id == destination.tenant_id,
            PublishWriteCoordinationRegistry.content_id == destination.content_id,
            PublishWriteCoordinationRegistry.platform == plat,
            PublishWriteCoordinationRegistry.state.in_(tuple(UNRESOLVED_REGISTRY_STATES)),
        ]
        if destination.account_id is None:
            conds.append(PublishWriteCoordinationRegistry.account_id.is_(None))
        else:
            conds.append(
                PublishWriteCoordinationRegistry.account_id == destination.account_id
            )
        stmt = (
            select(PublishWriteCoordinationRegistry)
            .where(and_(*conds))
            .order_by(PublishWriteCoordinationRegistry.updated_at.desc())
        )
        return (await db.execute(stmt)).scalars().all()

    @classmethod
    async def destination_has_unresolved_write(
        cls,
        db: AsyncSession,
        destination: DestinationIdentity,
    ) -> bool:
        rows = await cls.find_unresolved_for_destination(db, destination)
        return len(rows) > 0

    @classmethod
    async def find_durable_success_for_intent(
        cls,
        db: AsyncSession,
        *,
        destination: DestinationIdentity | None = None,
        publication_intent_id: UUID | None = None,
        logical_write_key: str | None = None,
    ) -> PublishWriteCoordinationRegistry | None:
        """Same-intent durable success (SUCCEEDED / RESOLVED_SUCCEEDED)."""
        if logical_write_key is None:
            if destination is None or publication_intent_id is None:
                raise ValueError(
                    "logical_write_key or (destination, publication_intent_id) required"
                )
            logical_write_key = cls.logical_write_key_for(
                destination, publication_intent_id
            )
        stmt = select(PublishWriteCoordinationRegistry).where(
            PublishWriteCoordinationRegistry.logical_write_key == logical_write_key,
            PublishWriteCoordinationRegistry.state.in_(tuple(DURABLE_SUCCESS_STATES)),
        )
        return (await db.execute(stmt)).scalar_one_or_none()

    @classmethod
    async def same_intent_has_durable_success(
        cls,
        db: AsyncSession,
        *,
        destination: DestinationIdentity | None = None,
        publication_intent_id: UUID | None = None,
        logical_write_key: str | None = None,
    ) -> bool:
        row = await cls.find_durable_success_for_intent(
            db,
            destination=destination,
            publication_intent_id=publication_intent_id,
            logical_write_key=logical_write_key,
        )
        return row is not None

    @classmethod
    def lease_is_active(
        cls,
        row: PublishWriteCoordinationRegistry,
        *,
        now: datetime,
    ) -> bool:
        if row.state != "RESERVED":
            return False
        if row.lease_expires_at is None:
            # Fail closed: RESERVED without expiry is treated as live.
            return True
        return row.lease_expires_at > now
