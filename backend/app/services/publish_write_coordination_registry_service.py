"""Dormant publish-write coordination registry state machine (R2).

Coordination primitive only. Does NOT:
  - call providers, enqueue work, execute retries
  - create retry/replacement commands
  - mint publication_intent_id
  - wire into PublishService / scheduler / executor
  - perform automatic reconciliation

Lock ordering for mutating operations:
  1. destination advisory xact lock (Follow-up B helper)
  2. fetch/create registry row under FOR UPDATE
  3. CAS / version-checked mutation
  4. commit (optional; never hold across provider I/O)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publish_write_coordination_registry import (
    PublishWriteCoordinationRegistry,
)
from app.repositories.publish_write_coordination_registry_repository import (
    DURABLE_SUCCESS_STATES,
    UNRESOLVED_REGISTRY_STATES,
    PublishWriteCoordinationRegistryRepository as RegistryRepo,
)
from app.services.publish_write_coordination import (
    DestinationIdentity,
    acquire_destination_xact_lock,
    normalize_destination,
)
from app.services.publish_write_coordination_registry_errors import (
    AlreadySucceeded,
    AuthorityAlreadyReserved,
    IntentSuperseded,
    InvalidStateTransition,
    LeaseStillActive,
    OwnerMismatch,
    PublishWriteCoordinationError,
    RegistryRowNotFound,
    StaleGeneration,
    StaleVersion,
    UnresolvedWriteConflict,
)

logger = logging.getLogger(__name__)

# First successful acquire uses generation=1 (R0.1). Schema permits >= 0.
INITIAL_GENERATION = 1

DEFAULT_LEASE_SECONDS = 120
_MIN_LEASE_SECONDS = 5
_MAX_LEASE_SECONDS = 3600

AcquireableSource = Literal[
    "no_row",
    "FAILED_SAFE",
    "RESOLVED_FAILED",
    "RESERVED_RECLAIM",
    "RESERVED_SAME_OWNER",
]

ResolveTarget = Literal["RESOLVED_SUCCEEDED", "RESOLVED_FAILED"]


@dataclass(frozen=True)
class WriteAuthority:
    """Pre-I/O write authority returned by a successful acquire."""

    registry_id: UUID
    logical_write_key: str
    publication_intent_id: UUID
    generation: int
    version: int
    owner_type: str
    owner_id: str
    lease_expires_at: datetime | None
    state: str
    tenant_id: UUID
    content_id: UUID
    platform: str
    account_id: UUID | None


@dataclass(frozen=True)
class RegistryTransitionResult:
    """Outcome of a successful state-changing mutation."""

    registry_id: UUID
    logical_write_key: str
    publication_intent_id: UUID
    state: str
    generation: int
    version: int
    external_post_id: str | None = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_lease_expires_at(
    *,
    now: datetime,
    lease_duration: timedelta | None,
    lease_expires_at: datetime | None,
    lease_seconds: int | None,
) -> datetime:
    if lease_expires_at is not None:
        return lease_expires_at
    seconds = DEFAULT_LEASE_SECONDS
    if lease_duration is not None:
        seconds = int(lease_duration.total_seconds())
    elif lease_seconds is not None:
        seconds = int(lease_seconds)
    seconds = max(_MIN_LEASE_SECONDS, min(seconds, _MAX_LEASE_SECONDS))
    return now + timedelta(seconds=seconds)


def _row_details(row: PublishWriteCoordinationRegistry) -> dict:
    return {
        "registry_id": row.id,
        "logical_write_key": row.logical_write_key,
        "state": row.state,
        "generation": row.generation,
        "version": row.version,
    }


def _authority_from_row(row: PublishWriteCoordinationRegistry) -> WriteAuthority:
    return WriteAuthority(
        registry_id=row.id,
        logical_write_key=row.logical_write_key,
        publication_intent_id=row.publication_intent_id,
        generation=row.generation,
        version=row.version,
        owner_type=row.owner_type or "",
        owner_id=row.owner_id or "",
        lease_expires_at=row.lease_expires_at,
        state=row.state,
        tenant_id=row.tenant_id,
        content_id=row.content_id,
        platform=row.platform,
        account_id=row.account_id,
    )


class PublishWriteCoordinationRegistryService:
    """Coordination state machine. Dormant — unused by live publish paths."""

    repo = RegistryRepo

    # ------------------------------------------------------------------
    # Read-only queries
    # ------------------------------------------------------------------

    @classmethod
    async def destination_has_unresolved_write(
        cls,
        db: AsyncSession,
        destination: DestinationIdentity,
    ) -> bool:
        dest = normalize_destination(
            tenant_id=destination.tenant_id,
            content_id=destination.content_id,
            platform=destination.platform,
            account_id=destination.account_id,
        )
        return await cls.repo.destination_has_unresolved_write(db, dest)

    @classmethod
    async def same_intent_has_durable_success(
        cls,
        db: AsyncSession,
        *,
        destination: DestinationIdentity | None = None,
        publication_intent_id: UUID | None = None,
        logical_write_key: str | None = None,
    ) -> bool:
        if destination is not None:
            destination = normalize_destination(
                tenant_id=destination.tenant_id,
                content_id=destination.content_id,
                platform=destination.platform,
                account_id=destination.account_id,
            )
        return await cls.repo.same_intent_has_durable_success(
            db,
            destination=destination,
            publication_intent_id=publication_intent_id,
            logical_write_key=logical_write_key,
        )

    # ------------------------------------------------------------------
    # Acquire
    # ------------------------------------------------------------------

    @classmethod
    async def acquire_write_authority(
        cls,
        db: AsyncSession,
        *,
        destination: DestinationIdentity,
        publication_intent_id: UUID,
        owner_type: str,
        owner_id: str,
        lease_duration: timedelta | None = None,
        lease_expires_at: datetime | None = None,
        lease_seconds: int | None = None,
        attempt_id: UUID | None = None,
        command_id: UUID | None = None,
        root_intent_id: UUID | None = None,
        now: datetime | None = None,
        commit: bool = True,
    ) -> WriteAuthority:
        """Atomically acquire pre-I/O write authority for a caller-supplied intent.

        Does NOT mint publication_intent_id.
        """
        if not owner_type or not owner_id:
            raise ValueError("owner_type and owner_id are required")

        dest = normalize_destination(
            tenant_id=destination.tenant_id,
            content_id=destination.content_id,
            platform=destination.platform,
            account_id=destination.account_id,
        )
        clock = now or _utcnow()
        expires = _coerce_lease_expires_at(
            now=clock,
            lease_duration=lease_duration,
            lease_expires_at=lease_expires_at,
            lease_seconds=lease_seconds,
        )
        key = cls.repo.logical_write_key_for(dest, publication_intent_id)

        # 1) destination advisory xact lock
        await acquire_destination_xact_lock(db, dest)

        # 2) fetch or create under row lock
        row = await cls.repo.get_by_logical_write_key(db, key, for_update=True)
        if row is None:
            created = await cls._try_insert_reserved(
                db,
                destination=dest,
                publication_intent_id=publication_intent_id,
                logical_write_key=key,
                owner_type=owner_type,
                owner_id=owner_id,
                lease_acquired_at=clock,
                lease_expires_at=expires,
                attempt_id=attempt_id,
                command_id=command_id,
                root_intent_id=root_intent_id or publication_intent_id,
            )
            if created is not None:
                if commit:
                    await db.commit()
                    await db.refresh(created)
                return _authority_from_row(created)
            # Uniqueness race: peer won INSERT; continue with locked peer row.
            row = await cls.repo.get_by_logical_write_key(db, key, for_update=True)
            if row is None:
                raise PublishWriteCoordinationError(
                    "Failed to create or load registry row after insert race",
                    details={"logical_write_key": key},
                )

        return await cls._acquire_existing(
            db,
            row=row,
            owner_type=owner_type,
            owner_id=owner_id,
            lease_acquired_at=clock,
            lease_expires_at=expires,
            attempt_id=attempt_id,
            command_id=command_id,
            now=clock,
            commit=commit,
        )

    @classmethod
    async def _try_insert_reserved(
        cls,
        db: AsyncSession,
        *,
        destination: DestinationIdentity,
        publication_intent_id: UUID,
        logical_write_key: str,
        owner_type: str,
        owner_id: str,
        lease_acquired_at: datetime,
        lease_expires_at: datetime,
        attempt_id: UUID | None,
        command_id: UUID | None,
        root_intent_id: UUID,
    ) -> PublishWriteCoordinationRegistry | None:
        row = PublishWriteCoordinationRegistry(
            id=uuid.uuid4(),
            logical_write_key=logical_write_key,
            tenant_id=destination.tenant_id,
            content_id=destination.content_id,
            platform=destination.platform_normalized,
            account_id=destination.account_id,
            publication_intent_id=publication_intent_id,
            root_intent_id=root_intent_id,
            state="RESERVED",
            generation=INITIAL_GENERATION,
            version=0,
            owner_type=owner_type,
            owner_id=owner_id,
            lease_acquired_at=lease_acquired_at,
            lease_expires_at=lease_expires_at,
            current_attempt_id=attempt_id,
            current_command_id=command_id,
        )
        try:
            async with db.begin_nested():
                await cls.repo.insert_row(db, row)
            return row
        except IntegrityError:
            return None
    @classmethod
    async def _acquire_existing(
        cls,
        db: AsyncSession,
        *,
        row: PublishWriteCoordinationRegistry,
        owner_type: str,
        owner_id: str,
        lease_acquired_at: datetime,
        lease_expires_at: datetime,
        attempt_id: UUID | None,
        command_id: UUID | None,
        now: datetime,
        commit: bool,
    ) -> WriteAuthority:
        details = _row_details(row)

        if row.state in UNRESOLVED_REGISTRY_STATES:
            raise UnresolvedWriteConflict(
                f"Cannot acquire while registry state is {row.state}",
                details=details,
            )
        if row.state in DURABLE_SUCCESS_STATES:
            raise AlreadySucceeded(
                f"Cannot acquire; intent already succeeded ({row.state})",
                details=details,
            )
        if row.state == "SUPERSEDED":
            raise IntentSuperseded(
                "Cannot acquire a superseded publication intent",
                details=details,
            )
        if row.state == "RESERVED":
            if cls.repo.lease_is_active(row, now=now):
                if row.owner_type == owner_type and row.owner_id == owner_id:
                    # Idempotent same-owner re-acquire: return live authority.
                    if commit:
                        await db.commit()
                    return _authority_from_row(row)
                raise LeaseStillActive(
                    "RESERVED lease still active for another owner",
                    details=details,
                )
            # Expired RESERVED → reclaim (generation bump).
            ok = await cls.repo.cas_update_fields(
                db,
                row,
                expected_version=row.version,
                state="RESERVED",
                generation=row.generation + 1,
                owner_type=owner_type,
                owner_id=owner_id,
                lease_acquired_at=lease_acquired_at,
                lease_expires_at=lease_expires_at,
                provider_write_started_at=None,
                current_attempt_id=attempt_id,
                current_command_id=command_id,
            )
            if not ok:
                raise StaleVersion(
                    "Stale version during RESERVED reclaim",
                    details={**details, "expected_version": row.version},
                )
            if commit:
                await db.commit()
                await db.refresh(row)
            return _authority_from_row(row)

        if row.state in ("FAILED_SAFE", "RESOLVED_FAILED"):
            ok = await cls.repo.cas_update_fields(
                db,
                row,
                expected_version=row.version,
                state="RESERVED",
                generation=row.generation + 1,
                owner_type=owner_type,
                owner_id=owner_id,
                lease_acquired_at=lease_acquired_at,
                lease_expires_at=lease_expires_at,
                provider_write_started_at=None,
                resolved_at=None,
                external_post_id=None,
                current_attempt_id=attempt_id,
                current_command_id=command_id,
            )
            if not ok:
                raise StaleVersion(
                    "Stale version during re-acquire",
                    details={**details, "expected_version": row.version},
                )
            if commit:
                await db.commit()
                await db.refresh(row)
            return _authority_from_row(row)

        raise InvalidStateTransition(
            f"Acquire not allowed from state {row.state}",
            details={**details, "from_state": row.state, "to_state": "RESERVED"},
        )

    # ------------------------------------------------------------------
    # Owner-gated transitions
    # ------------------------------------------------------------------

    @classmethod
    async def mark_write_started(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        owner_type: str,
        owner_id: str,
        generation: int,
        expected_version: int,
        now: datetime | None = None,
        commit: bool = True,
    ) -> RegistryTransitionResult:
        row = await cls._lock_owned_row(
            db,
            registry_id=registry_id,
            owner_type=owner_type,
            owner_id=owner_id,
            generation=generation,
            expected_version=expected_version,
            allowed_states=("RESERVED",),
            to_state="WRITE_STARTED",
        )
        clock = now or _utcnow()
        ok = await cls.repo.cas_update_fields(
            db,
            row,
            expected_version=expected_version,
            state="WRITE_STARTED",
            provider_write_started_at=clock,
        )
        if not ok:
            raise StaleVersion(
                "Stale version on mark_write_started",
                details={**_row_details(row), "expected_version": expected_version},
            )
        if commit:
            await db.commit()
            await db.refresh(row)
        return RegistryTransitionResult(
            registry_id=row.id,
            logical_write_key=row.logical_write_key,
            publication_intent_id=row.publication_intent_id,
            state=row.state,
            generation=row.generation,
            version=row.version,
        )

    @classmethod
    async def record_safe_failure(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        owner_type: str,
        owner_id: str,
        generation: int,
        expected_version: int,
        commit: bool = True,
    ) -> RegistryTransitionResult:
        """RESERVED → FAILED_SAFE only. WRITE_STARTED → FAILED_SAFE is impossible."""
        row = await cls._lock_owned_row(
            db,
            registry_id=registry_id,
            owner_type=owner_type,
            owner_id=owner_id,
            generation=generation,
            expected_version=expected_version,
            allowed_states=("RESERVED",),
            to_state="FAILED_SAFE",
        )
        ok = await cls.repo.cas_update_fields(
            db,
            row,
            expected_version=expected_version,
            state="FAILED_SAFE",
            owner_type=None,
            owner_id=None,
            lease_acquired_at=None,
            lease_expires_at=None,
            current_attempt_id=None,
            current_command_id=None,
        )
        if not ok:
            raise StaleVersion(
                "Stale version on record_safe_failure",
                details={**_row_details(row), "expected_version": expected_version},
            )
        if commit:
            await db.commit()
            await db.refresh(row)
        return RegistryTransitionResult(
            registry_id=row.id,
            logical_write_key=row.logical_write_key,
            publication_intent_id=row.publication_intent_id,
            state=row.state,
            generation=row.generation,
            version=row.version,
        )

    @classmethod
    async def record_success(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        owner_type: str,
        owner_id: str,
        generation: int,
        expected_version: int,
        external_post_id: str,
        commit: bool = True,
    ) -> RegistryTransitionResult:
        if not external_post_id:
            raise ValueError("external_post_id evidence is required for success")
        row = await cls._lock_owned_row(
            db,
            registry_id=registry_id,
            owner_type=owner_type,
            owner_id=owner_id,
            generation=generation,
            expected_version=expected_version,
            allowed_states=("WRITE_STARTED",),
            to_state="SUCCEEDED",
        )
        ok = await cls.repo.cas_update_fields(
            db,
            row,
            expected_version=expected_version,
            state="SUCCEEDED",
            external_post_id=external_post_id,
            lease_acquired_at=None,
            lease_expires_at=None,
            # Keep owner_* as forensic identity of the succeeding generation.
        )
        if not ok:
            raise StaleVersion(
                "Stale version on record_success",
                details={**_row_details(row), "expected_version": expected_version},
            )
        if commit:
            await db.commit()
            await db.refresh(row)
        return RegistryTransitionResult(
            registry_id=row.id,
            logical_write_key=row.logical_write_key,
            publication_intent_id=row.publication_intent_id,
            state=row.state,
            generation=row.generation,
            version=row.version,
            external_post_id=row.external_post_id,
        )

    @classmethod
    async def record_ambiguous(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        owner_type: str,
        owner_id: str,
        generation: int,
        expected_version: int,
        commit: bool = True,
    ) -> RegistryTransitionResult:
        row = await cls._lock_owned_row(
            db,
            registry_id=registry_id,
            owner_type=owner_type,
            owner_id=owner_id,
            generation=generation,
            expected_version=expected_version,
            allowed_states=("WRITE_STARTED",),
            to_state="AMBIGUOUS",
        )
        ok = await cls.repo.cas_update_fields(
            db,
            row,
            expected_version=expected_version,
            state="AMBIGUOUS",
            lease_acquired_at=None,
            lease_expires_at=None,
        )
        if not ok:
            raise StaleVersion(
                "Stale version on record_ambiguous",
                details={**_row_details(row), "expected_version": expected_version},
            )
        if commit:
            await db.commit()
            await db.refresh(row)
        return RegistryTransitionResult(
            registry_id=row.id,
            logical_write_key=row.logical_write_key,
            publication_intent_id=row.publication_intent_id,
            state=row.state,
            generation=row.generation,
            version=row.version,
        )

    @classmethod
    async def surface_stranded_write(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        expected_version: int,
        owner_liveness_valid: bool,
        commit: bool = True,
    ) -> RegistryTransitionResult:
        """WRITE_STARTED → AMBIGUOUS when caller asserts owner is not live.

        Does not infer provider outcome. Not invoked by any scanner in R2.
        """
        if owner_liveness_valid:
            raise InvalidStateTransition(
                "Cannot surface stranded write while owner liveness is valid",
                details={
                    "registry_id": registry_id,
                    "from_state": "WRITE_STARTED",
                    "to_state": "AMBIGUOUS",
                },
            )
        row = await cls.repo.get_by_id(db, registry_id, for_update=True)
        if row is None:
            raise RegistryRowNotFound(
                "Registry row not found",
                details={"registry_id": registry_id},
            )
        details = _row_details(row)
        if row.state != "WRITE_STARTED":
            raise InvalidStateTransition(
                f"surface_stranded_write requires WRITE_STARTED, got {row.state}",
                details={**details, "from_state": row.state, "to_state": "AMBIGUOUS"},
            )
        if row.version != expected_version:
            raise StaleVersion(
                "Stale version on surface_stranded_write",
                details={**details, "expected_version": expected_version},
            )
        ok = await cls.repo.cas_update_fields(
            db,
            row,
            expected_version=expected_version,
            state="AMBIGUOUS",
            lease_acquired_at=None,
            lease_expires_at=None,
        )
        if not ok:
            raise StaleVersion(
                "Stale version on surface_stranded_write",
                details={**details, "expected_version": expected_version},
            )
        if commit:
            await db.commit()
            await db.refresh(row)
        return RegistryTransitionResult(
            registry_id=row.id,
            logical_write_key=row.logical_write_key,
            publication_intent_id=row.publication_intent_id,
            state=row.state,
            generation=row.generation,
            version=row.version,
        )

    @classmethod
    async def resolve_ambiguous(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        expected_version: int,
        target: ResolveTarget,
        resolution_evidence: str,
        resolver_id: str,
        external_post_id: str | None = None,
        now: datetime | None = None,
        commit: bool = True,
    ) -> RegistryTransitionResult:
        if target not in ("RESOLVED_SUCCEEDED", "RESOLVED_FAILED"):
            raise ValueError(f"Invalid resolve target: {target}")
        if not resolution_evidence or not resolver_id:
            raise ValueError("resolution_evidence and resolver_id are required")
        if target == "RESOLVED_SUCCEEDED" and not external_post_id:
            raise ValueError(
                "external_post_id evidence is required for RESOLVED_SUCCEEDED"
            )

        row = await cls.repo.get_by_id(db, registry_id, for_update=True)
        if row is None:
            raise RegistryRowNotFound(
                "Registry row not found",
                details={"registry_id": registry_id},
            )
        details = _row_details(row)
        if row.state != "AMBIGUOUS":
            raise InvalidStateTransition(
                f"resolve_ambiguous requires AMBIGUOUS, got {row.state}",
                details={**details, "from_state": row.state, "to_state": target},
            )
        if row.version != expected_version:
            raise StaleVersion(
                "Stale version on resolve_ambiguous",
                details={**details, "expected_version": expected_version},
            )

        clock = now or _utcnow()
        fields: dict = {
            "state": target,
            "resolved_at": clock,
            "lease_acquired_at": None,
            "lease_expires_at": None,
        }
        if target == "RESOLVED_SUCCEEDED":
            fields["external_post_id"] = external_post_id
        # Evidence/resolver are required for the operation contract; R1 schema
        # has no dedicated columns — do not invent persistence here.

        ok = await cls.repo.cas_update_fields(
            db, row, expected_version=expected_version, **fields
        )
        if not ok:
            raise StaleVersion(
                "Stale version on resolve_ambiguous",
                details={**details, "expected_version": expected_version},
            )
        if commit:
            await db.commit()
            await db.refresh(row)
        logger.debug(
            "[WriteCoordRegistry] resolve_ambiguous id=%s target=%s resolver=%s",
            row.id,
            target,
            resolver_id,
        )
        return RegistryTransitionResult(
            registry_id=row.id,
            logical_write_key=row.logical_write_key,
            publication_intent_id=row.publication_intent_id,
            state=row.state,
            generation=row.generation,
            version=row.version,
            external_post_id=row.external_post_id,
        )

    @classmethod
    async def supersede_intent(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        expected_version: int,
        commit: bool = True,
    ) -> RegistryTransitionResult:
        """Mark an eligible prior intent SUPERSEDED. Does not mint a new intent."""
        allowed = (
            "SUCCEEDED",
            "RESOLVED_SUCCEEDED",
            "FAILED_SAFE",
            "RESOLVED_FAILED",
        )
        row = await cls.repo.get_by_id(db, registry_id, for_update=True)
        if row is None:
            raise RegistryRowNotFound(
                "Registry row not found",
                details={"registry_id": registry_id},
            )
        details = _row_details(row)
        if row.state in ("RESERVED", "WRITE_STARTED", "AMBIGUOUS"):
            raise InvalidStateTransition(
                f"Cannot SUPERSEDE while unresolved/active ({row.state})",
                details={**details, "from_state": row.state, "to_state": "SUPERSEDED"},
            )
        if row.state not in allowed:
            raise InvalidStateTransition(
                f"SUPERSEDE not allowed from {row.state}",
                details={**details, "from_state": row.state, "to_state": "SUPERSEDED"},
            )
        if row.version != expected_version:
            raise StaleVersion(
                "Stale version on supersede_intent",
                details={**details, "expected_version": expected_version},
            )
        ok = await cls.repo.cas_update_fields(
            db,
            row,
            expected_version=expected_version,
            state="SUPERSEDED",
            lease_acquired_at=None,
            lease_expires_at=None,
        )
        if not ok:
            raise StaleVersion(
                "Stale version on supersede_intent",
                details={**details, "expected_version": expected_version},
            )
        if commit:
            await db.commit()
            await db.refresh(row)
        return RegistryTransitionResult(
            registry_id=row.id,
            logical_write_key=row.logical_write_key,
            publication_intent_id=row.publication_intent_id,
            state=row.state,
            generation=row.generation,
            version=row.version,
            external_post_id=row.external_post_id,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @classmethod
    async def _lock_owned_row(
        cls,
        db: AsyncSession,
        *,
        registry_id: UUID,
        owner_type: str,
        owner_id: str,
        generation: int,
        expected_version: int,
        allowed_states: tuple[str, ...],
        to_state: str,
    ) -> PublishWriteCoordinationRegistry:
        row = await cls.repo.get_by_id(db, registry_id, for_update=True)
        if row is None:
            raise RegistryRowNotFound(
                "Registry row not found",
                details={"registry_id": registry_id},
            )
        details = _row_details(row)
        if row.state not in allowed_states:
            raise InvalidStateTransition(
                f"Transition to {to_state} not allowed from {row.state}",
                details={
                    **details,
                    "from_state": row.state,
                    "to_state": to_state,
                },
            )
        if row.version != expected_version:
            raise StaleVersion(
                "Stale version before transition",
                details={**details, "expected_version": expected_version},
            )
        if row.generation != generation:
            raise StaleGeneration(
                "Stale generation before transition",
                details={**details, "expected_generation": generation},
            )
        if row.owner_type != owner_type or row.owner_id != owner_id:
            raise OwnerMismatch(
                "Owner identity does not match registry owner",
                details=details,
            )
        return row


# Re-export common symbols for tests / future integration imports.
__all__ = [
    "INITIAL_GENERATION",
    "PublishWriteCoordinationRegistryService",
    "RegistryTransitionResult",
    "WriteAuthority",
    "AlreadySucceeded",
    "AuthorityAlreadyReserved",
    "IntentSuperseded",
    "InvalidStateTransition",
    "LeaseStillActive",
    "OwnerMismatch",
    "PublishWriteCoordinationError",
    "RegistryRowNotFound",
    "StaleGeneration",
    "StaleVersion",
    "UnresolvedWriteConflict",
]
