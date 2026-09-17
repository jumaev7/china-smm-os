"""I2b — durable idempotent intent-only publication-request acceptance.

Implements request acceptance (A) only:

* mint one ``publication_intent_id`` per genuinely new authorized request
* never call providers, PublishService execution, registry mutation, retry,
  scheduler, or attempt creation

Tenant integrity is enforced in the service layer (content→client→tenant and
account.tenant_id). PostgreSQL FKs alone do not prove cross-tenant ownership.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.config import settings
from app.models.content import ContentItem
from app.models.publish_intentional_publication_request import (
    PUBLICATION_REQUEST_OPERATIONS,
    PublishIntentionalPublicationRequest,
    build_request_fingerprint,
)
from app.models.publishing_account import PublishingAccount
from app.services.admin_rbac_service import CurrentAdminUser
from app.services.publish_destination_identity import (
    PROVEN_DISTINCT_DESTINATION,
    SAME_DESTINATION,
    UNRESOLVED_DESTINATION,
    compare_publication_destinations,
    extract_external_destination,
    normalize_platform,
)
from app.services.publish_resilience import (
    STATUS_IN_PROGRESS,
    compute_publish_version,
    evaluate_live_success_identity,
)
from app.services.publish_write_coordination import (
    DestinationIdentity,
    acquire_destination_xact_lock,
    assert_content_tenant_owns,
    find_unresolved_destination_write,
    normalize_destination,
)
from app.services.publishing_account_service import PublishingAccountService
from app.services.publishing_tenant_scope import resolve_publishing_tenant_id
from app.services.tenant_auth_service import CurrentTenantUser

logger = logging.getLogger(__name__)

INTENT_MODE = "mint_new"

# Stable failure codes (no sensitive cross-tenant disclosure).
FAILURE_FEATURE_DISABLED = "intentional_publication_requests_disabled"
FAILURE_MISSING_KEY = "missing_client_idempotency_key"
FAILURE_FINGERPRINT_CONFLICT = "request_fingerprint_conflict"
FAILURE_VERSION_MISMATCH = "publish_version_mismatch"
FAILURE_DESTINATION_UNRESOLVED = "destination_identity_unresolved"
FAILURE_UNRESOLVED_PRIOR_WRITE = "unresolved_prior_write"
FAILURE_IDENTITY_CONFLICT = "provider_identity_conflict"
FAILURE_PLATFORM_ACCOUNT_MISMATCH = "platform_account_mismatch"
FAILURE_TENANT_OWNERSHIP = "tenant_ownership_rejected"
FAILURE_UNAUTHORIZED_OPERATION = "unauthorized_operation"

_REPUBLISH_ROLES = frozenset({"owner", "manager"})
_ACCEPT_ROLES = frozenset({"owner", "manager", "operator"})

_ACCEPTANCE_NOTE = (
    "Request accepted as a durable business intention only. "
    "Acceptance does not authorize provider write, republishing, "
    "registry mutation, or publication execution."
)
_ACCEPTANCE_NOTE_PRIOR_SUCCESS = (
    "Request accepted as a durable business intention only. "
    "A prior live success exists at this destination; acceptance does not "
    "authorize republishing or any provider write."
)


@dataclass(frozen=True)
class AcceptResult:
    request: PublishIntentionalPublicationRequest
    idempotent_replay: bool
    prior_live_success: bool
    acceptance_note: str


class PublishIntentionalPublicationRequestService:
    """Find-or-create intentional publication requests (intent mint only)."""

    @staticmethod
    def feature_enabled() -> bool:
        return bool(
            getattr(settings, "PUBLISH_INTENTIONAL_PUBLICATION_REQUESTS_ENABLED", False)
        )

    @staticmethod
    def require_feature_enabled() -> None:
        if not PublishIntentionalPublicationRequestService.feature_enabled():
            raise HTTPException(status_code=404, detail="Not found")

    @staticmethod
    def resolve_tenant_id(
        user: CurrentTenantUser | None,
        admin: CurrentAdminUser | None,
        tenant_id: UUID | None,
    ) -> UUID:
        return resolve_publishing_tenant_id(user, admin, tenant_id)

    @staticmethod
    def assert_actor_authorized(
        *,
        user: CurrentTenantUser | None,
        admin: CurrentAdminUser | None,
        operation: str,
    ) -> None:
        if admin is not None:
            return
        if user is None:
            raise HTTPException(status_code=401, detail="Authentication required")
        role = getattr(user, "role", None)
        if operation == "intentional_republish":
            if role not in _REPUBLISH_ROLES and not getattr(
                user, "has_permission", lambda _p: False
            )("tenant.full"):
                raise HTTPException(
                    status_code=403,
                    detail={
                        "failure_code": FAILURE_UNAUTHORIZED_OPERATION,
                        "message": (
                            "intentional_republish requires tenant owner or manager"
                        ),
                    },
                )
            return
        if role not in _ACCEPT_ROLES and not getattr(
            user, "has_permission", lambda _p: False
        )("tenant.full"):
            raise HTTPException(
                status_code=403,
                detail={
                    "failure_code": FAILURE_UNAUTHORIZED_OPERATION,
                    "message": f"Role '{role}' is not allowed to accept publication intents",
                },
            )

    @classmethod
    async def accept(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        content_id: UUID,
        platform: str,
        account_id: UUID | None,
        operation: str,
        client_idempotency_key: str,
        expected_publish_version: str,
        user: CurrentTenantUser | None = None,
        admin: CurrentAdminUser | None = None,
    ) -> AcceptResult:
        """Accept one destination intent. Never executes publication."""
        cls.require_feature_enabled()
        cls.assert_actor_authorized(user=user, admin=admin, operation=operation)

        key = (client_idempotency_key or "").strip()
        if not key:
            raise HTTPException(
                status_code=400,
                detail={
                    "failure_code": FAILURE_MISSING_KEY,
                    "message": "client_idempotency_key is required",
                },
            )

        if operation not in PUBLICATION_REQUEST_OPERATIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported operation: {operation}",
            )

        plat = normalize_platform(platform)
        if not plat:
            raise HTTPException(status_code=400, detail="platform is required")

        # --- ownership + snapshot under one transaction ---
        item = await cls._lock_content_for_tenant(
            db, content_id=content_id, tenant_id=tenant_id
        )
        actual_version = compute_publish_version(item)
        if actual_version != expected_publish_version.strip():
            raise HTTPException(
                status_code=409,
                detail={
                    "failure_code": FAILURE_VERSION_MISMATCH,
                    "message": (
                        "expected_publish_version does not match current content snapshot"
                    ),
                },
            )

        account = await cls._resolve_account(
            db,
            tenant_id=tenant_id,
            platform=plat,
            account_id=account_id,
        )
        resolved_account_id = account.id if account is not None else None

        identity = normalize_destination(
            tenant_id=tenant_id,
            content_id=content_id,
            platform=plat,
            account_id=resolved_account_id,
        )
        await acquire_destination_xact_lock(db, identity)

        prior_live_success, safety_note = await cls._destination_safety_gate(
            db,
            identity=identity,
            account=account,
        )

        fingerprint = build_request_fingerprint(
            tenant_id=tenant_id,
            content_id=content_id,
            platform=plat,
            account_id=resolved_account_id,
            operation=operation,
            publish_version=actual_version,
            intent_mode=INTENT_MODE,
        )

        result = await cls._find_or_create(
            db,
            tenant_id=tenant_id,
            content_id=content_id,
            platform=plat,
            account_id=resolved_account_id,
            operation=operation,
            client_idempotency_key=key,
            request_fingerprint=fingerprint,
            publish_version=actual_version,
        )

        note = (
            safety_note
            if prior_live_success
            else result.acceptance_note
        )
        return AcceptResult(
            request=result.request,
            idempotent_replay=result.idempotent_replay,
            prior_live_success=prior_live_success,
            acceptance_note=note,
        )

    @staticmethod
    async def _lock_content_for_tenant(
        db: AsyncSession,
        *,
        content_id: UUID,
        tenant_id: UUID,
    ) -> ContentItem:
        """Lock content row and prove tenant ownership via client relationship."""
        try:
            await assert_content_tenant_owns(
                db, content_id=content_id, tenant_id=tenant_id
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "failure_code": FAILURE_TENANT_OWNERSHIP,
                    "message": "Content is not owned by the authenticated tenant",
                },
            ) from exc

        result = await db.execute(
            select(ContentItem)
            .options(
                load_only(
                    ContentItem.id,
                    ContentItem.client_id,
                    ContentItem.caption_long_ru,
                    ContentItem.caption_long_en,
                    ContentItem.caption_short_ru,
                    ContentItem.hashtags,
                    ContentItem.media_file_id,
                    ContentItem.platforms,
                    ContentItem.updated_at,
                )
            )
            .where(ContentItem.id == content_id)
            .with_for_update()
        )
        item = result.scalar_one_or_none()
        if item is None:
            raise HTTPException(
                status_code=404,
                detail="Content not found",
            )
        # Re-check ownership after lock (client reassignment race).
        try:
            await assert_content_tenant_owns(
                db, content_id=content_id, tenant_id=tenant_id
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=403,
                detail={
                    "failure_code": FAILURE_TENANT_OWNERSHIP,
                    "message": "Content is not owned by the authenticated tenant",
                },
            ) from exc
        return item

    @staticmethod
    async def _resolve_account(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        platform: str,
        account_id: UUID | None,
    ) -> PublishingAccount | None:
        """Resolve selected account under tenant scope; NULL stays NULL.

        Explicit NULL is a valid destination token (I2a NULLS NOT DISTINCT).
        Do not silently substitute a default account when the caller omitted
        account_id — that would change request-key scope.
        """
        if account_id is None:
            return None
        try:
            account = await PublishingAccountService.get(db, tenant_id, account_id)
        except HTTPException as exc:
            if exc.status_code == 404:
                raise HTTPException(
                    status_code=403,
                    detail={
                        "failure_code": FAILURE_TENANT_OWNERSHIP,
                        "message": "Publishing account is not owned by the authenticated tenant",
                    },
                ) from exc
            raise
        if normalize_platform(account.platform) != platform:
            raise HTTPException(
                status_code=400,
                detail={
                    "failure_code": FAILURE_PLATFORM_ACCOUNT_MISMATCH,
                    "message": (
                        f"Account is for {account.platform}, not {platform}"
                    ),
                },
            )
        return account

    @classmethod
    async def _destination_safety_gate(
        cls,
        db: AsyncSession,
        *,
        identity: DestinationIdentity,
        account: PublishingAccount | None,
    ) -> tuple[bool, str]:
        """Fail closed on unresolved / ambiguous destination evidence.

        Prior live success does not block acceptance, but the response must
        state that acceptance does not authorize republishing.
        """
        # Exact-account unresolved retry command (coordination helper).
        unresolved_cmd = await find_unresolved_destination_write(db, identity)
        if unresolved_cmd is not None:
            raise HTTPException(
                status_code=422,
                detail={
                    "failure_code": FAILURE_UNRESOLVED_PRIOR_WRITE,
                    "message": (
                        "Unresolved prior write at destination; "
                        "acceptance refused"
                    ),
                },
            )

        # Alias-aware unresolved commands / in-progress attempts.
        await cls._reject_alias_unresolved_or_inflight(
            db, identity=identity, account=account
        )

        from app.services.publish_resilience import PublishResilienceService

        prior, comparison = await PublishResilienceService.find_destination_live_success(
            db,
            content_id=identity.content_id,
            platform=identity.platform_normalized,
            account_id=identity.account_id,
            account=account,
        )
        if prior is None:
            # Intended account itself must be resolvable when concrete, else
            # later write stages cannot prove destination. Prefer reject when
            # a concrete account lacks established external identity AND we
            # would otherwise invent a destination token.
            if account is not None:
                ref = extract_external_destination(
                    account, platform=identity.platform_normalized
                )
                # tiktok/linkedin have no established field — leave acceptance
                # allowed (intent-only) but still no write auth. Historical
                # NULL / alias cases are handled above via comparison.
                _ = ref
            return False, _ACCEPTANCE_NOTE

        if comparison == UNRESOLVED_DESTINATION:
            raise HTTPException(
                status_code=422,
                detail={
                    "failure_code": FAILURE_DESTINATION_UNRESOLVED,
                    "message": (
                        "Destination identity unresolved relative to prior "
                        "publication evidence; acceptance refused"
                    ),
                },
            )

        identity_eval = evaluate_live_success_identity(prior)
        if getattr(identity_eval, "identity_conflict", False):
            raise HTTPException(
                status_code=422,
                detail={
                    "failure_code": FAILURE_IDENTITY_CONFLICT,
                    "message": (
                        "Conflicting provider identity on prior success; "
                        "acceptance refused"
                    ),
                },
            )

        if comparison == SAME_DESTINATION and identity_eval.suppresses:
            return True, _ACCEPTANCE_NOTE_PRIOR_SUCCESS

        return False, _ACCEPTANCE_NOTE

    @classmethod
    async def _reject_alias_unresolved_or_inflight(
        cls,
        db: AsyncSession,
        *,
        identity: DestinationIdentity,
        account: PublishingAccount | None,
    ) -> None:
        """Block acceptance when an alias destination has unresolved risk."""
        from app.models.publish_attempt import PublishAttempt
        from app.models.publish_retry_command import PublishRetryCommand
        from app.services.publish_resilience import PublishResilienceService

        plat = identity.platform_normalized
        cmd_rows = (
            await db.execute(
                select(PublishRetryCommand).where(
                    PublishRetryCommand.tenant_id == identity.tenant_id,
                    PublishRetryCommand.content_id == identity.content_id,
                    PublishRetryCommand.platform == plat,
                    PublishRetryCommand.status.in_(
                        ("provider_write_started", "ambiguous")
                    ),
                )
            )
        ).scalars().all()

        attempt_rows = (
            await db.execute(
                select(PublishAttempt).where(
                    PublishAttempt.content_id == identity.content_id,
                    PublishAttempt.platform == plat,
                    PublishAttempt.status == STATUS_IN_PROGRESS,
                )
            )
        ).scalars().all()

        prior_ids = {
            aid
            for aid in (
                *(getattr(c, "publishing_account_id", None) for c in cmd_rows),
                *(getattr(a, "account_id", None) for a in attempt_rows),
            )
            if aid is not None
        }
        accounts_by_id = await PublishResilienceService._load_publishing_accounts(
            db, prior_ids
        )

        for cmd in cmd_rows:
            prior_aid = getattr(cmd, "publishing_account_id", None)
            prior_acct = accounts_by_id.get(prior_aid) if prior_aid else None
            comparison = compare_publication_destinations(
                platform=plat,
                intended_account_id=identity.account_id,
                intended_account=account,
                prior_account_id=prior_aid,
                prior_account=prior_acct,
            )
            if comparison != PROVEN_DISTINCT_DESTINATION:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "failure_code": FAILURE_UNRESOLVED_PRIOR_WRITE,
                        "message": (
                            "Unresolved prior write at same or unresolved "
                            "destination; acceptance refused"
                        ),
                    },
                )

        for attempt in attempt_rows:
            prior_aid = getattr(attempt, "account_id", None)
            prior_acct = accounts_by_id.get(prior_aid) if prior_aid else None
            comparison = compare_publication_destinations(
                platform=plat,
                intended_account_id=identity.account_id,
                intended_account=account,
                prior_account_id=prior_aid,
                prior_account=prior_acct,
            )
            if comparison != PROVEN_DISTINCT_DESTINATION:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "failure_code": FAILURE_UNRESOLVED_PRIOR_WRITE,
                        "message": (
                            "In-progress publication at same or unresolved "
                            "destination; acceptance refused"
                        ),
                    },
                )

    @classmethod
    async def _find_or_create(
        cls,
        db: AsyncSession,
        *,
        tenant_id: UUID,
        content_id: UUID,
        platform: str,
        account_id: UUID | None,
        operation: str,
        client_idempotency_key: str,
        request_fingerprint: str,
        publish_version: str,
    ) -> AcceptResult:
        """Transaction-safe replay-before-create (INSERT ON CONFLICT)."""
        existing = await cls._load_by_request_key(
            db,
            tenant_id=tenant_id,
            content_id=content_id,
            platform=platform,
            account_id=account_id,
            operation=operation,
            client_idempotency_key=client_idempotency_key,
        )
        if existing is not None:
            return cls._replay_or_conflict(existing, request_fingerprint)

        new_id = uuid4()
        intent_id = uuid4()
        stmt = (
            insert(PublishIntentionalPublicationRequest)
            .values(
                id=new_id,
                tenant_id=tenant_id,
                content_id=content_id,
                platform=platform,
                account_id=account_id,
                operation=operation,
                client_idempotency_key=client_idempotency_key,
                request_fingerprint=request_fingerprint,
                publication_intent_id=intent_id,
                publish_version=publish_version,
                status="accepted",
            )
            .on_conflict_do_nothing(
                index_elements=[
                    "tenant_id",
                    "content_id",
                    "platform",
                    "account_id",
                    "operation",
                    "client_idempotency_key",
                ]
            )
            .returning(PublishIntentionalPublicationRequest.id)
        )
        try:
            async with db.begin_nested():
                inserted_id = (await db.execute(stmt)).scalar_one_or_none()
                await db.flush()
        except IntegrityError:
            # Unique conflict / aborted statement inside savepoint — do not
            # reuse a failed SQLAlchemy transaction; reload committed row.
            inserted_id = None

        if inserted_id is not None:
            row = await db.get(PublishIntentionalPublicationRequest, inserted_id)
            if row is None:
                raise HTTPException(
                    status_code=500,
                    detail="Request acceptance failed after insert",
                )
            logger.info(
                "[I2b] accepted publication request id=%s intent=%s "
                "tenant=%s content=%s platform=%s op=%s",
                row.id,
                row.publication_intent_id,
                tenant_id,
                content_id,
                platform,
                operation,
            )
            return AcceptResult(
                request=row,
                idempotent_replay=False,
                prior_live_success=False,
                acceptance_note=_ACCEPTANCE_NOTE,
            )

        # Lost the race — reload committed winner; never mint replacement.
        existing = await cls._load_by_request_key(
            db,
            tenant_id=tenant_id,
            content_id=content_id,
            platform=platform,
            account_id=account_id,
            operation=operation,
            client_idempotency_key=client_idempotency_key,
        )
        if existing is None:
            raise HTTPException(
                status_code=500,
                detail="Request acceptance conflict without durable row",
            )
        return cls._replay_or_conflict(existing, request_fingerprint)

    @staticmethod
    def _replay_or_conflict(
        existing: PublishIntentionalPublicationRequest,
        request_fingerprint: str,
    ) -> AcceptResult:
        if existing.request_fingerprint != request_fingerprint:
            raise HTTPException(
                status_code=409,
                detail={
                    "failure_code": FAILURE_FINGERPRINT_CONFLICT,
                    "message": (
                        "client_idempotency_key already bound to a different "
                        "request fingerprint; no new intent minted"
                    ),
                    "existing_request_id": str(existing.id),
                    "existing_publication_intent_id": str(
                        existing.publication_intent_id
                    ),
                },
            )
        return AcceptResult(
            request=existing,
            idempotent_replay=True,
            prior_live_success=False,
            acceptance_note=_ACCEPTANCE_NOTE,
        )

    @staticmethod
    async def _load_by_request_key(
        db: AsyncSession,
        *,
        tenant_id: UUID,
        content_id: UUID,
        platform: str,
        account_id: UUID | None,
        operation: str,
        client_idempotency_key: str,
    ) -> PublishIntentionalPublicationRequest | None:
        """Load by uniqueness scope; NULL account uses IS NULL."""
        stmt = select(PublishIntentionalPublicationRequest).where(
            PublishIntentionalPublicationRequest.tenant_id == tenant_id,
            PublishIntentionalPublicationRequest.content_id == content_id,
            PublishIntentionalPublicationRequest.platform == platform,
            PublishIntentionalPublicationRequest.operation == operation,
            PublishIntentionalPublicationRequest.client_idempotency_key
            == client_idempotency_key,
        )
        if account_id is None:
            stmt = stmt.where(
                PublishIntentionalPublicationRequest.account_id.is_(None)
            )
        else:
            stmt = stmt.where(
                PublishIntentionalPublicationRequest.account_id == account_id
            )
        return (await db.execute(stmt)).scalar_one_or_none()

    @staticmethod
    def serialize(result: AcceptResult) -> dict[str, Any]:
        row = result.request
        return {
            "request_id": row.id,
            "publication_intent_id": row.publication_intent_id,
            "status": "accepted",
            "accepted": True,
            "idempotent_replay": result.idempotent_replay,
            "operation": row.operation,
            "content_id": row.content_id,
            "platform": row.platform,
            "account_id": row.account_id,
            "publish_version": row.publish_version,
            "request_fingerprint": row.request_fingerprint,
            "write_authorized": False,
            "prior_live_success": result.prior_live_success,
            "acceptance_note": result.acceptance_note,
        }
