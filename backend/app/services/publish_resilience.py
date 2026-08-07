"""Publish attempt resilience — classification, scrubbing, claiming, backoff."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.models.publishing_account import PublishingAccount
from app.services.automation_domain_events import scrub_payload

logger = logging.getLogger(__name__)

# Attempt statuses
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_IN_PROGRESS = "in_progress"
STATUS_RETRYING = "retrying"
STATUS_OPERATOR_REVIEW = "operator_review"
STATUS_EXHAUSTED = "exhausted"

ACTIVE_CLAIM_STATUSES = frozenset({STATUS_IN_PROGRESS})
TERMINAL_SUCCESS_STATUSES = frozenset({STATUS_SUCCESS})
OPS_LIST_STATUSES = frozenset({
    STATUS_FAILED,
    STATUS_RETRYING,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_EXHAUSTED,
})

# Meta Graph transient / rate-limit style codes
_META_TRANSIENT_CODES = frozenset({1, 2, 4, 17, 32, 613})
_META_AUTH_CODES = frozenset({190, 102, 463, 467})
_META_PERMISSION_CODES = frozenset({10, 200, 294, 3})

_SECRET_RE = re.compile(
    r"(?i)(access[_-]?token|page[_-]?access[_-]?token|authorization|bearer\s+\S+|"
    r"client_secret|app_secret|webhook[_-]?secret|password)\s*[:=]\s*\S+"
)
_TOKENISH_RE = re.compile(r"(?i)\b(EAA[A-Za-z0-9]+|sk-[A-Za-z0-9]{20,}|ya29\.[A-Za-z0-9._-]+)\b")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_error_message(error: str | None, *, limit: int = 480) -> str | None:
    """Remove secrets/tokens from operator-visible error text."""
    if not error:
        return None
    text = _SECRET_RE.sub(r"\1=[redacted]", str(error))
    text = _TOKENISH_RE.sub("[redacted]", text)
    text = text.replace("\x00", "")
    return text[:limit]


def scrub_publish_result(result: dict[str, Any] | None) -> dict[str, Any]:
    """Scrub adapter result before JSON persistence."""
    clean = scrub_payload(result or {})
    if "error" in clean:
        clean["error"] = sanitize_error_message(str(clean.get("error") or ""))
    # Never persist raw provider blobs that may include tokens.
    clean.pop("raw", None)
    clean.pop("page_access_token", None)
    clean.pop("access_token", None)
    return clean


def compute_publish_version(item: ContentItem, payload: dict[str, Any] | None = None) -> str:
    """Stable version for this content snapshot (caption + media identity)."""
    payload = payload or {}
    parts = [
        str(item.id),
        (item.caption_long_ru or "")[:200],
        (item.caption_long_en or "")[:200],
        (item.caption_short_ru or "")[:120],
        (item.hashtags or "")[:120],
        str(item.media_file_id or ""),
        str(payload.get("media_url") or ""),
        str(payload.get("generated_final_video_url") or ""),
        ",".join(sorted(item.platforms or [])),
        (item.updated_at.isoformat() if getattr(item, "updated_at", None) else ""),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"pv_{digest}"


def build_idempotency_key(
    *,
    content_id: UUID,
    platform: str,
    account_id: UUID | None,
    publish_version: str,
) -> str:
    account_part = str(account_id) if account_id else "none"
    return f"{content_id}:{platform}:{account_part}:{publish_version}"


def classify_publish_failure(
    error: str | None,
    *,
    http_status: int | None = None,
    meta_code: int | None = None,
    meta_subcode: int | None = None,
    is_timeout: bool = False,
    is_connection_error: bool = False,
) -> tuple[str, str, bool]:
    """Return (failure_code, failure_category, retryable)."""
    text = (error or "").lower()

    if is_timeout or "timeout" in text or "timed out" in text or "interrupted" in text:
        return "publish_timeout", "timeout", True
    if is_connection_error or any(
        token in text for token in ("connection", "connecterror", "network", "temporarily unavailable")
    ):
        return "connection_error", "network", True

    if http_status == 429 or meta_code in _META_TRANSIENT_CODES or "rate" in text or "throttle" in text:
        return "rate_limited", "provider", True
    if http_status is not None and 500 <= http_status < 600:
        return "provider_unavailable", "provider", True

    if meta_code in _META_AUTH_CODES or meta_subcode in _META_AUTH_CODES:
        return "auth_or_permission", "auth", False
    if meta_code in _META_PERMISSION_CODES:
        return "auth_or_permission", "auth", False

    if any(
        token in text
        for token in (
            "oauth", "access token", "invalid token", "session has expired",
            "permission", "permissions", "(#190)", "(#10)", "(#200)",
        )
    ):
        return "auth_or_permission", "auth", False

    if any(
        token in text
        for token in (
            "unsupported media", "aspect ratio", "invalid media", "validation",
            "caption too long", "image format", "video format", "not allowed",
        )
    ):
        return "validation_error", "validation", False

    if "account" in text or "not found" in text or "no connected" in text:
        return "account_unavailable", "account", False

    if "live publish is disabled" in text or "blocked" in text:
        return "publish_blocked", "config", False

    # Unknown Meta/provider errors are treated as retryable only when clearly transient.
    if "meta graph api" in text and any(t in text for t in ("try again", "temporary", "later")):
        return "provider_transient", "provider", True

    return "adapter_failure", "provider", True


def compute_backoff_seconds(
    attempt_number: int,
    *,
    retry_after_seconds: int | None = None,
) -> int:
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return min(int(retry_after_seconds), settings.PUBLISH_RETRY_MAX_SECONDS)
    base = max(1, int(settings.PUBLISH_RETRY_BASE_SECONDS))
    capped = min(
        settings.PUBLISH_RETRY_MAX_SECONDS,
        int(base * math.pow(2, max(0, attempt_number - 1))),
    )
    return max(base, capped)


@dataclass
class ClaimResult:
    attempt: PublishAttempt | None
    skip: bool
    reason: str | None = None
    result: dict[str, Any] | None = None


class PublishResilienceService:
    @staticmethod
    def max_attempts() -> int:
        return max(1, int(settings.PUBLISH_MAX_ATTEMPTS))

    @staticmethod
    def stale_minutes() -> int:
        return max(1, int(settings.PUBLISH_STALE_ATTEMPT_MINUTES))

    @staticmethod
    def lease_seconds() -> int:
        return max(30, int(settings.PUBLISH_ATTEMPT_LEASE_SECONDS))

    @classmethod
    async def next_attempt_number(cls, db: AsyncSession, idempotency_key: str) -> int:
        result = await db.execute(
            select(func.coalesce(func.max(PublishAttempt.attempt_number), 0)).where(
                PublishAttempt.idempotency_key == idempotency_key,
            )
        )
        return int(result.scalar_one() or 0) + 1

    @classmethod
    async def find_live_success(
        cls,
        db: AsyncSession,
        *,
        idempotency_key: str | None = None,
        content_id: UUID | None = None,
        platform: str | None = None,
        account_id: UUID | None = None,
    ) -> PublishAttempt | None:
        query = select(PublishAttempt).where(
            PublishAttempt.status == STATUS_SUCCESS,
            or_(
                PublishAttempt.external_post_id.isnot(None),
                PublishAttempt.response.isnot(None),
            ),
        ).order_by(PublishAttempt.created_at.desc())
        if idempotency_key:
            query = query.where(PublishAttempt.idempotency_key == idempotency_key)
        else:
            if content_id is None or platform is None:
                return None
            query = query.where(
                PublishAttempt.content_id == content_id,
                PublishAttempt.platform == platform,
            )
            if account_id is not None:
                query = query.where(PublishAttempt.account_id == account_id)
        result = await db.execute(query)
        for attempt in result.scalars().all():
            post_id = attempt.external_post_id
            if not post_id and attempt.response:
                try:
                    payload = json.loads(attempt.response)
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                if isinstance(payload, dict):
                    if payload.get("mock") is True or payload.get("test") is True:
                        continue
                    post_id = payload.get("platform_post_id")
            if post_id:
                return attempt
        return None

    @classmethod
    async def find_active_claim(
        cls,
        db: AsyncSession,
        idempotency_key: str,
        *,
        now: datetime | None = None,
    ) -> PublishAttempt | None:
        now = now or utc_now()
        result = await db.execute(
            select(PublishAttempt).where(
                PublishAttempt.idempotency_key == idempotency_key,
                PublishAttempt.status == STATUS_IN_PROGRESS,
            )
        )
        attempt = result.scalar_one_or_none()
        if not attempt:
            return None
        if attempt.lease_expires_at and attempt.lease_expires_at < now:
            return None
        return attempt

    @classmethod
    async def begin_attempt(
        cls,
        db: AsyncSession,
        *,
        content_id: UUID,
        platform: str,
        account: PublishingAccount | None,
        publish_version: str,
        lease_owner: str | None = None,
        test_mode: bool = False,
    ) -> ClaimResult:
        """Claim a destination for publishing or return a skip reason."""
        if test_mode:
            return ClaimResult(attempt=None, skip=False, reason=None)

        account_id = account.id if account else None
        key = build_idempotency_key(
            content_id=content_id,
            platform=platform,
            account_id=account_id,
            publish_version=publish_version,
        )
        now = utc_now()

        prior = await cls.find_live_success(db, idempotency_key=key)
        if prior is None:
            # Also suppress duplicates across older versions when a live post exists
            # for the same content+platform+account.
            prior = await cls.find_live_success(
                db,
                content_id=content_id,
                platform=platform,
                account_id=account_id,
            )
        if prior is not None:
            post_id = prior.external_post_id
            post_url = prior.external_post_url
            if not post_id and prior.response:
                try:
                    payload = json.loads(prior.response)
                except (json.JSONDecodeError, TypeError):
                    payload = {}
                if isinstance(payload, dict):
                    post_id = payload.get("platform_post_id")
                    post_url = post_url or payload.get("post_url")
            return ClaimResult(
                attempt=prior,
                skip=True,
                reason="already_published",
                result={
                    "platform": platform,
                    "success": True,
                    "platform_post_id": post_id,
                    "post_url": post_url,
                    "mock": False,
                    "deduplicated": True,
                    "message": "Already published; duplicate suppressed",
                    "account_id": str(account_id) if account_id else None,
                    "account_name": account.account_name if account else None,
                    "attempt_id": str(prior.id),
                },
            )

        active = await cls.find_active_claim(db, key, now=now)
        if active is not None:
            return ClaimResult(
                attempt=active,
                skip=True,
                reason="in_progress",
                result={
                    "platform": platform,
                    "success": False,
                    "error": "Publish already in progress for this destination",
                    "platform_post_id": None,
                    "mock": account.status == "mock" if account else True,
                    "account_id": str(account_id) if account_id else None,
                    "account_name": account.account_name if account else None,
                    "failure_code": "concurrent_claim",
                    "failure_category": "concurrency",
                    "retryable": True,
                    "attempt_id": str(active.id),
                },
            )

        attempt_number = await cls.next_attempt_number(db, key)
        if attempt_number > cls.max_attempts():
            return ClaimResult(
                attempt=None,
                skip=True,
                reason="max_attempts",
                result={
                    "platform": platform,
                    "success": False,
                    "error": f"Maximum publish attempts ({cls.max_attempts()}) exhausted",
                    "platform_post_id": None,
                    "mock": account.status == "mock" if account else True,
                    "account_id": str(account_id) if account_id else None,
                    "account_name": account.account_name if account else None,
                    "failure_code": "max_attempts_exhausted",
                    "failure_category": "exhausted",
                    "retryable": False,
                },
            )

        # Supersede prior retrying rows for this destination so the scheduler
        # does not keep re-selecting them after a fresh claim.
        prior_retrying = list(
            (
                await db.scalars(
                    select(PublishAttempt).where(
                        PublishAttempt.idempotency_key == key,
                        PublishAttempt.status == STATUS_RETRYING,
                    )
                )
            ).all()
        )
        for row in prior_retrying:
            row.status = STATUS_FAILED
            row.next_retry_at = None
            row.finished_at = now
            row.error = sanitize_error_message(
                row.error or "Superseded by new publish attempt"
            )

        owner = lease_owner or f"worker:{uuid4().hex[:12]}"
        attempt = PublishAttempt(
            content_id=content_id,
            platform=platform,
            account_id=account_id,
            status=STATUS_IN_PROGRESS,
            response=None,
            error=None,
            idempotency_key=key,
            publish_version=publish_version,
            attempt_number=attempt_number,
            started_at=now,
            lease_owner=owner,
            lease_expires_at=now + timedelta(seconds=cls.lease_seconds()),
        )
        try:
            async with db.begin_nested():
                db.add(attempt)
                await db.flush()
        except IntegrityError:
            active = await cls.find_active_claim(db, key, now=utc_now())
            prior = await cls.find_live_success(db, idempotency_key=key)
            if prior is not None:
                post_id = prior.external_post_id
                post_url = prior.external_post_url
                return ClaimResult(
                    attempt=prior,
                    skip=True,
                    reason="already_published",
                    result={
                        "platform": platform,
                        "success": True,
                        "platform_post_id": post_id,
                        "post_url": post_url,
                        "mock": False,
                        "deduplicated": True,
                        "message": "Already published; duplicate suppressed",
                        "account_id": str(account_id) if account_id else None,
                        "account_name": account.account_name if account else None,
                        "attempt_id": str(prior.id),
                    },
                )
            return ClaimResult(
                attempt=active,
                skip=True,
                reason="in_progress",
                result={
                    "platform": platform,
                    "success": False,
                    "error": "Publish already claimed by another worker",
                    "platform_post_id": None,
                    "mock": account.status == "mock" if account else True,
                    "account_id": str(account_id) if account_id else None,
                    "account_name": account.account_name if account else None,
                    "failure_code": "concurrent_claim",
                    "failure_category": "concurrency",
                    "retryable": True,
                    "attempt_id": str(active.id) if active else None,
                },
            )

        logger.info(
            "[PublishResilience] claimed: key=%s attempt=%s number=%s",
            key,
            attempt.id,
            attempt_number,
        )
        return ClaimResult(attempt=attempt, skip=False)

    @classmethod
    async def finalize_attempt(
        cls,
        db: AsyncSession,
        attempt: PublishAttempt,
        result: dict[str, Any],
        *,
        http_status: int | None = None,
        meta_code: int | None = None,
        meta_subcode: int | None = None,
        retry_after_seconds: int | None = None,
        is_timeout: bool = False,
        is_connection_error: bool = False,
    ) -> PublishAttempt:
        now = utc_now()
        clean = scrub_publish_result(result)
        success = bool(clean.get("success"))
        error = sanitize_error_message(clean.get("error"))
        post_id = clean.get("platform_post_id")
        post_url = clean.get("post_url")

        attempt.response = json.dumps(clean, ensure_ascii=False, default=str)
        attempt.error = error
        attempt.finished_at = now
        attempt.lease_owner = None
        attempt.lease_expires_at = None
        attempt.retry_after_seconds = retry_after_seconds

        if success and post_id and not clean.get("mock") and not clean.get("test"):
            attempt.status = STATUS_SUCCESS
            attempt.external_post_id = str(post_id)
            attempt.external_post_url = str(post_url) if post_url else None
            attempt.failure_code = None
            attempt.failure_category = None
            attempt.retryable = False
            attempt.next_retry_at = None
            await db.flush()
            await cls._notify_alert(db, attempt, previous_status=STATUS_IN_PROGRESS)
            return attempt

        if success:
            # Mock/test success — record without blocking real publishes.
            attempt.status = STATUS_SUCCESS
            attempt.external_post_id = str(post_id) if post_id else None
            attempt.external_post_url = str(post_url) if post_url else None
            attempt.retryable = False
            attempt.next_retry_at = None
            await db.flush()
            await cls._notify_alert(db, attempt, previous_status=STATUS_IN_PROGRESS)
            return attempt

        code, category, retryable = classify_publish_failure(
            error,
            http_status=http_status or clean.get("http_status"),
            meta_code=meta_code if meta_code is not None else clean.get("meta_code"),
            meta_subcode=meta_subcode if meta_subcode is not None else clean.get("meta_subcode"),
            is_timeout=is_timeout or bool(clean.get("is_timeout")),
            is_connection_error=is_connection_error or bool(clean.get("is_connection_error")),
        )
        # Prefer structured fields from the adapter result when present.
        if clean.get("failure_code"):
            code = str(clean["failure_code"])
        if clean.get("failure_category"):
            category = str(clean["failure_category"])
        if "retryable" in clean and clean["retryable"] is not None:
            retryable = bool(clean["retryable"])

        attempt.failure_code = code
        attempt.failure_category = category
        attempt.retryable = retryable

        effective_retry_after = retry_after_seconds or clean.get("retry_after_seconds")
        if isinstance(effective_retry_after, str) and effective_retry_after.isdigit():
            effective_retry_after = int(effective_retry_after)

        if retryable and attempt.attempt_number < cls.max_attempts():
            delay = compute_backoff_seconds(
                attempt.attempt_number,
                retry_after_seconds=int(effective_retry_after) if effective_retry_after else None,
            )
            attempt.status = STATUS_RETRYING
            attempt.next_retry_at = now + timedelta(seconds=delay)
            attempt.retry_after_seconds = int(effective_retry_after) if effective_retry_after else delay
        elif retryable and attempt.attempt_number >= cls.max_attempts():
            attempt.status = STATUS_EXHAUSTED
            attempt.retryable = False
            attempt.next_retry_at = None
        else:
            attempt.status = STATUS_FAILED
            attempt.next_retry_at = None

        await db.flush()
        await cls._notify_alert(db, attempt, previous_status=STATUS_IN_PROGRESS)
        return attempt

    @classmethod
    async def _notify_alert(
        cls,
        db: AsyncSession,
        attempt: PublishAttempt,
        *,
        previous_status: str | None = None,
    ) -> None:
        """Best-effort operator alert; never affects publishing outcome."""
        try:
            from app.services.publish_operator_alert_service import PublishOperatorAlertService

            await PublishOperatorAlertService.on_attempt_transition(
                db, attempt, previous_status=previous_status,
            )
        except Exception:
            logger.exception(
                "[PublishResilience] alert notify failed attempt_id=%s status=%s",
                getattr(attempt, "id", None),
                getattr(attempt, "status", None),
            )

    @classmethod
    async def recover_stale_attempts(
        cls,
        db: AsyncSession,
        *,
        content_id: UUID | None = None,
    ) -> int:
        """Reconcile in_progress attempts past the stale timeout."""
        now = utc_now()
        cutoff = now - timedelta(minutes=cls.stale_minutes())
        query = select(PublishAttempt).where(
            PublishAttempt.status == STATUS_IN_PROGRESS,
            or_(
                and_(PublishAttempt.lease_expires_at.isnot(None), PublishAttempt.lease_expires_at < now),
                and_(
                    PublishAttempt.started_at.isnot(None),
                    PublishAttempt.started_at < cutoff,
                ),
                and_(
                    PublishAttempt.started_at.is_(None),
                    PublishAttempt.created_at < cutoff,
                ),
            ),
        )
        if content_id:
            query = query.where(PublishAttempt.content_id == content_id)
        result = await db.execute(query)
        attempts = list(result.scalars().all())
        recovered = 0
        for attempt in attempts:
            # If a success already exists for this key, close as failed duplicate claim.
            if attempt.idempotency_key:
                prior = await cls.find_live_success(db, idempotency_key=attempt.idempotency_key)
                if prior is not None and prior.id != attempt.id:
                    attempt.status = STATUS_FAILED
                    attempt.error = sanitize_error_message(
                        "Stale in-progress claim closed — destination already published"
                    )
                    attempt.failure_code = "stale_after_success"
                    attempt.failure_category = "concurrency"
                    attempt.retryable = False
                    attempt.finished_at = now
                    attempt.lease_owner = None
                    attempt.lease_expires_at = None
                    recovered += 1
                    continue

            previous_status = attempt.status
            # Meta platforms: unsafe to auto-repost after ambiguous in-progress timeout.
            if attempt.platform in ("facebook", "instagram"):
                attempt.status = STATUS_OPERATOR_REVIEW
                attempt.error = sanitize_error_message(
                    "Publishing timed out while in progress — operator review required "
                    "before retrying to avoid duplicate posts"
                )
                attempt.failure_code = "stale_in_progress"
                attempt.failure_category = "timeout"
                attempt.retryable = False
                attempt.next_retry_at = None
            else:
                attempt.status = STATUS_RETRYING
                attempt.error = sanitize_error_message("Publishing timeout — scheduled for safe retry")
                attempt.failure_code = "publish_timeout"
                attempt.failure_category = "timeout"
                attempt.retryable = True
                delay = compute_backoff_seconds(attempt.attempt_number or 1)
                attempt.next_retry_at = now + timedelta(seconds=delay)
            attempt.finished_at = now
            attempt.lease_owner = None
            attempt.lease_expires_at = None
            recovered += 1
            logger.warning(
                "[PublishResilience] stale attempt: id=%s platform=%s status=%s",
                attempt.id,
                attempt.platform,
                attempt.status,
            )
            await cls._notify_alert(db, attempt, previous_status=previous_status)
        if recovered:
            await db.flush()
        return recovered

    @classmethod
    async def claim_due_retries(
        cls,
        db: AsyncSession,
        *,
        limit: int = 20,
        lease_owner: str | None = None,
    ) -> list[PublishAttempt]:
        """Atomically claim due retrying attempts for worker processing."""
        now = utc_now()
        owner = lease_owner or f"retry:{uuid4().hex[:12]}"
        rows = list(
            (
                await db.scalars(
                    select(PublishAttempt)
                    .where(
                        PublishAttempt.status == STATUS_RETRYING,
                        PublishAttempt.retryable.is_(True),
                        PublishAttempt.next_retry_at.isnot(None),
                        PublishAttempt.next_retry_at <= now,
                        PublishAttempt.attempt_number < cls.max_attempts(),
                    )
                    .order_by(PublishAttempt.next_retry_at.asc())
                    .limit(max(1, limit))
                    .with_for_update(skip_locked=True),
                )
            ).all()
        )
        claimed: list[PublishAttempt] = []
        for row in rows:
            # Skip if a live success already exists.
            if row.idempotency_key:
                prior = await cls.find_live_success(db, idempotency_key=row.idempotency_key)
                if prior is not None:
                    row.status = STATUS_FAILED
                    row.error = sanitize_error_message(
                        "Retry cancelled — destination already published"
                    )
                    row.retryable = False
                    row.next_retry_at = None
                    row.finished_at = now
                    continue
            # Convert retrying row into a fresh in_progress claim via new row.
            # Mark the due retrying row as superseded by creating a new claim.
            row.status = STATUS_FAILED
            row.error = sanitize_error_message(
                row.error or "Superseded by automatic retry claim"
            )
            row.next_retry_at = None
            row.finished_at = now
            claimed.append(row)
        await db.flush()

        # Return content-level work items (unique content ids) for republish.
        return claimed

    @classmethod
    def serialize_attempt(cls, attempt: PublishAttempt) -> dict[str, Any]:
        return {
            "id": attempt.id,
            "content_id": attempt.content_id,
            "platform": attempt.platform,
            "account_id": attempt.account_id,
            "account_name": attempt.account.account_name if attempt.account else None,
            "status": attempt.status,
            "response": attempt.response,
            "error": attempt.error,
            "idempotency_key": attempt.idempotency_key,
            "publish_version": attempt.publish_version,
            "attempt_number": attempt.attempt_number,
            "failure_code": attempt.failure_code,
            "failure_category": attempt.failure_category,
            "retryable": attempt.retryable,
            "next_retry_at": attempt.next_retry_at,
            "started_at": attempt.started_at,
            "finished_at": attempt.finished_at,
            "external_post_id": attempt.external_post_id,
            "external_post_url": attempt.external_post_url,
            "platform_post_id": attempt.external_post_id,
            "post_url": attempt.external_post_url,
            "created_at": attempt.created_at,
            "manual_retry_allowed": cls.manual_retry_allowed(attempt)[0],
            "manual_retry_blocked_reason": cls.manual_retry_allowed(attempt)[1],
        }

    @classmethod
    def manual_retry_allowed(cls, attempt: PublishAttempt) -> tuple[bool, str | None]:
        if attempt.status == STATUS_SUCCESS and attempt.external_post_id:
            return False, "Destination already published — retry would create a duplicate"
        if attempt.status == STATUS_IN_PROGRESS:
            return False, "Publish is currently in progress — wait for completion or stale recovery"
        if attempt.status == STATUS_RETRYING and attempt.next_retry_at and attempt.next_retry_at > utc_now():
            return False, f"Automatic retry already scheduled for {attempt.next_retry_at.isoformat()}"
        if attempt.status == STATUS_EXHAUSTED:
            # Manual retry allowed after exhaustion (operator override), but only if no live success.
            return True, None
        if attempt.status == STATUS_OPERATOR_REVIEW:
            return True, None
        if attempt.status in (STATUS_FAILED, STATUS_RETRYING):
            return True, None
        if attempt.status == STATUS_SUCCESS:
            return False, "Attempt already succeeded"
        return False, f"Cannot retry attempt with status={attempt.status}"
