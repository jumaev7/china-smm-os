"""Operator Workspace Actions Phase 1 — derive and route safe canonical mutations.

Workspace remains a projection/aggregation layer. All mutations delegate to existing
domain services (alerts, publishing, content). No duplicate business logic.
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.api_auth_context import get_auth_context
from app.core.client_scope_guard import guard_resource_client_id
from app.models.content import ContentItem
from app.models.publish_attempt import PublishAttempt
from app.models.publish_operator_alert import PublishOperatorAlert
from app.schemas.operator_workspace import (
    OperatorAttentionItem,
    OperatorWorkspaceAction,
    OperatorWorkspaceActionResult,
)
from app.services.content_review_service import (
    CLIENT_REVIEW_CHANGES,
    CLIENT_REVIEW_PENDING,
)
from app.services.content_service import ContentService
from app.services.operator_workspace_metrics import OperatorWorkspaceMetricsService
from app.services.operator_workspace_service import INTERNAL_REVIEW_STATUSES
from app.services.publish_attempt_ops_service import PublishAttemptOpsService
from app.services.publish_operator_alert_service import PublishOperatorAlertService
from app.services.publish_resilience import (
    STATUS_EXHAUSTED,
    STATUS_FAILED,
    STATUS_IN_PROGRESS,
    STATUS_OPERATOR_REVIEW,
    STATUS_RETRYING,
    STATUS_SUCCESS,
    PublishResilienceService,
)

logger = logging.getLogger(__name__)

# Stable action IDs — never expose raw enums to end users; frontend localizes labels.
ACTION_OPEN = "open"
ACTION_ACKNOWLEDGE_ALERT = "acknowledge_alert"
ACTION_RESOLVE_ALERT = "resolve_alert"
ACTION_RETRY_PUBLISH = "retry_publish"
ACTION_APPROVE_CONTENT = "approve_content"

MUTATION_ACTIONS = frozenset({
    ACTION_ACKNOWLEDGE_ALERT,
    ACTION_RESOLVE_ALERT,
    ACTION_RETRY_PUBLISH,
    ACTION_APPROVE_CONTENT,
})

# Workspace is stricter than PublishResilienceService.manual_retry_allowed:
# operator_review requires human verification of ambiguous Meta outcomes — no
# one-click retry from the daily queue.
_WORKSPACE_RETRY_STATUSES = frozenset({STATUS_FAILED, STATUS_EXHAUSTED, STATUS_RETRYING})

_ATTENTION_PREFIXES = frozenset({
    "content-review",
    "waiting-client",
    "publish-attempt",
    "stuck-publishing",
    "schedule-overdue",
    "integration",
    "telegram",
    "automation",
    "publish-alert",
})


def parse_attention_id(attention_id: str) -> tuple[str, str]:
    if ":" not in attention_id:
        raise HTTPException(status_code=400, detail="Invalid attention item id")
    prefix, resource_key = attention_id.split(":", 1)
    if prefix not in _ATTENTION_PREFIXES or not resource_key:
        raise HTTPException(status_code=400, detail="Invalid attention item id")
    return prefix, resource_key


def _open_action(href: str, *, label: str = "Open") -> OperatorWorkspaceAction:
    return OperatorWorkspaceAction(
        action_id=ACTION_OPEN,
        label=label,
        action_type="navigation",
        enabled=True,
        requires_confirmation=False,
        destructive=False,
        external_side_effect=False,
        href=href,
        primary=False,
    )


def _mutation(
    action_id: str,
    *,
    label: str,
    enabled: bool = True,
    requires_confirmation: bool = False,
    confirmation_message: str | None = None,
    disabled_reason: str | None = None,
    destructive: bool = False,
    external_side_effect: bool = False,
    target_resource: str | None = None,
    primary: bool = False,
) -> OperatorWorkspaceAction:
    return OperatorWorkspaceAction(
        action_id=action_id,
        label=label,
        action_type="mutation",
        enabled=enabled,
        requires_confirmation=requires_confirmation,
        confirmation_message=confirmation_message,
        disabled_reason=disabled_reason,
        destructive=destructive,
        external_side_effect=external_side_effect,
        target_resource=target_resource,
        primary=primary,
    )


def workspace_retry_allowed(attempt: PublishAttempt) -> tuple[bool, str | None]:
    """Stricter than canonical manual_retry_allowed — blocks operator_review."""
    if attempt.status == STATUS_OPERATOR_REVIEW:
        return False, "Ambiguous publish outcome requires operator verification before retry"
    if attempt.status == STATUS_IN_PROGRESS:
        return False, "Publish is currently in progress"
    if attempt.status == STATUS_SUCCESS and attempt.external_post_id:
        return False, "Destination already published"
    if attempt.status not in _WORKSPACE_RETRY_STATUSES:
        return False, f"Retry not available for status={attempt.status}"
    allowed, reason = PublishResilienceService.manual_retry_allowed(attempt)
    if not allowed:
        return False, reason
    return True, None


class OperatorWorkspaceActionService:
    """Derive action metadata and execute Phase 1 safe mutations via canonical services."""

    @classmethod
    def derive_actions(cls, item: OperatorAttentionItem) -> list[OperatorWorkspaceAction]:
        prefix = item.id.split(":", 1)[0] if ":" in item.id else ""
        href = item.action_path or "/"

        if prefix == "publish-alert":
            alert_id = item.resource_id or (item.metadata or {}).get("alert_id")
            target = f"alert:{alert_id}" if alert_id else None
            state = (item.current_state or "").lower()
            actions: list[OperatorWorkspaceAction] = []
            if state == "open":
                actions.append(
                    _mutation(
                        ACTION_ACKNOWLEDGE_ALERT,
                        label="Acknowledge",
                        enabled=True,
                        requires_confirmation=False,
                        target_resource=target,
                        primary=True,
                    ),
                )
            actions.append(
                _mutation(
                    ACTION_RESOLVE_ALERT,
                    label="Resolve",
                    enabled=state in ("open", "acknowledged"),
                    requires_confirmation=True,
                    confirmation_message="This will mark the alert resolved and remove it from the attention queue.",
                    disabled_reason=None if state in ("open", "acknowledged") else "Alert is not open",
                    target_resource=target,
                    primary=state == "acknowledged",
                ),
            )
            actions.append(_open_action(href, label="Open alert"))
            return actions

        if prefix == "publish-attempt":
            status = item.current_state or ""
            attempt_id = item.resource_id or (item.metadata or {}).get("attempt_id")
            target = f"attempt:{attempt_id}" if attempt_id else None
            actions = []
            if status == STATUS_OPERATOR_REVIEW:
                # Navigation only — never one-click retry for ambiguous Meta outcomes.
                actions.append(_open_action(href, label="Review"))
                return actions

            retry_ok = status in _WORKSPACE_RETRY_STATUSES
            disabled_reason = None
            if status == STATUS_IN_PROGRESS:
                retry_ok = False
                disabled_reason = "Publish is currently in progress"
            elif status == STATUS_SUCCESS:
                retry_ok = False
                disabled_reason = "Attempt already succeeded"
            elif not retry_ok:
                disabled_reason = "Retry not available for this publish state"

            if retry_ok or disabled_reason:
                actions.append(
                    _mutation(
                        ACTION_RETRY_PUBLISH,
                        label="Retry publish",
                        enabled=retry_ok,
                        requires_confirmation=True,
                        confirmation_message="This will schedule/attempt publication again.",
                        disabled_reason=None if retry_ok else disabled_reason,
                        external_side_effect=True,
                        target_resource=target,
                        primary=retry_ok,
                    ),
                )
            actions.append(_open_action(href, label="Review"))
            return actions

        if prefix == "content-review":
            status = item.current_state or ""
            eligible = status in INTERNAL_REVIEW_STATUSES
            content_id = str(item.content_id) if item.content_id else None
            return [
                _mutation(
                    ACTION_APPROVE_CONTENT,
                    label="Approve",
                    enabled=eligible,
                    requires_confirmation=True,
                    confirmation_message=(
                        "This marks internal approval and starts client review where configured. "
                        "It does not publish or bypass client approval."
                    ),
                    disabled_reason=None if eligible else "Content is not eligible for internal approval",
                    external_side_effect=True,  # may send Telegram client preview
                    target_resource=f"content:{content_id}" if content_id else None,
                    primary=eligible,
                ),
                _open_action(href, label="Open editor"),
            ]

        # All other categories: navigation only in Phase 1.
        return [_open_action(href, label=item.suggested_action or "Open")]

    @classmethod
    def attach_actions(cls, items: list[OperatorAttentionItem]) -> list[OperatorAttentionItem]:
        for item in items:
            item.actions = cls.derive_actions(item)
        return items

    @classmethod
    async def execute(
        cls,
        db: AsyncSession,
        *,
        attention_id: str,
        action_id: str,
        actor_id: UUID | None,
        tenant_id: UUID | None,
        note: str | None = None,
    ) -> OperatorWorkspaceActionResult:
        if action_id == ACTION_OPEN:
            raise HTTPException(
                status_code=400,
                detail="Navigation actions cannot be executed through the mutation endpoint",
            )
        if action_id not in MUTATION_ACTIONS:
            raise HTTPException(status_code=400, detail="Unknown or unsupported action")

        prefix, resource_key = parse_attention_id(attention_id)
        audit_tenant = tenant_id
        audit_client: UUID | None = None
        audit_category: str | None = None
        resource_type = prefix
        resource_id = resource_key

        try:
            if action_id in (ACTION_ACKNOWLEDGE_ALERT, ACTION_RESOLVE_ALERT):
                if prefix != "publish-alert":
                    raise HTTPException(status_code=400, detail="Action does not apply to this attention item")
                result, audit_tenant, audit_client = await cls._execute_alert(
                    db,
                    alert_id=UUID(resource_key),
                    action_id=action_id,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    note=note,
                )
                audit_category = "publishing_issue"
            elif action_id == ACTION_RETRY_PUBLISH:
                if prefix != "publish-attempt":
                    raise HTTPException(status_code=400, detail="Action does not apply to this attention item")
                result, audit_tenant, audit_client = await cls._execute_retry(
                    db,
                    attempt_id=UUID(resource_key),
                    tenant_id=tenant_id,
                    actor_id=actor_id,
                )
                audit_category = "publishing_issue"
            elif action_id == ACTION_APPROVE_CONTENT:
                if prefix != "content-review":
                    raise HTTPException(status_code=400, detail="Action does not apply to this attention item")
                result, audit_tenant, audit_client = await cls._execute_approve(
                    db,
                    content_id=UUID(resource_key),
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                )
                audit_category = "content_internal_review"
            else:
                raise HTTPException(status_code=400, detail="Unsupported action")

            await OperatorWorkspaceMetricsService.record_action(
                db,
                action_id=action_id,
                outcome="success",
                actor_id=actor_id,
                tenant_id=audit_tenant,
                attention_id=attention_id,
                resource_type=resource_type,
                resource_id=resource_id,
                client_id=audit_client,
                category=audit_category,
                message=result.message,
                commit=True,
            )
            return result
        except HTTPException as exc:
            outcome = "stale" if exc.status_code == 409 else "rejected"
            if exc.status_code >= 500:
                outcome = "failed"
            await OperatorWorkspaceMetricsService.record_action(
                db,
                action_id=action_id,
                outcome=outcome,  # type: ignore[arg-type]
                actor_id=actor_id,
                tenant_id=audit_tenant or tenant_id,
                attention_id=attention_id,
                resource_type=resource_type,
                resource_id=resource_id,
                client_id=audit_client,
                category=audit_category,
                reason_code=str(exc.status_code),
                message=str(exc.detail)[:500] if exc.detail else None,
                commit=True,
            )
            raise
        except Exception as exc:
            await OperatorWorkspaceMetricsService.record_action(
                db,
                action_id=action_id,
                outcome="failed",
                actor_id=actor_id,
                tenant_id=audit_tenant or tenant_id,
                attention_id=attention_id,
                resource_type=resource_type,
                resource_id=resource_id,
                client_id=audit_client,
                category=audit_category,
                reason_code="exception",
                message=str(exc)[:500],
                commit=True,
            )
            raise

    @classmethod
    async def _resolve_alert_tenant(
        cls,
        db: AsyncSession,
        alert: PublishOperatorAlert,
        *,
        tenant_id: UUID | None,
    ) -> UUID:
        """Prefer caller tenant; for admins, use the alert's tenant after scope checks."""
        ctx = get_auth_context()
        if ctx and ctx.is_tenant:
            if ctx.tenant_id is None:
                raise HTTPException(status_code=403, detail="Tenant scope required")
            if alert.tenant_id != ctx.tenant_id:
                raise HTTPException(status_code=404, detail="Alert not found")
            return ctx.tenant_id
        # Admin: use alert tenant (resource re-resolution), optional explicit override match.
        if tenant_id is not None and tenant_id != alert.tenant_id:
            raise HTTPException(status_code=404, detail="Alert not found")
        return alert.tenant_id

    @classmethod
    async def _load_alert_scoped(
        cls,
        db: AsyncSession,
        alert_id: UUID,
        *,
        tenant_id: UUID | None,
    ) -> tuple[PublishOperatorAlert, UUID, UUID | None]:
        row = (
            await db.execute(
                select(PublishOperatorAlert).where(PublishOperatorAlert.id == alert_id),
            )
        ).scalar_one_or_none()
        if row is None:
            raise HTTPException(status_code=404, detail="Alert not found")

        client_id: UUID | None = None
        # Enforce client scope via content when present.
        if row.content_id is not None:
            content = (
                await db.execute(
                    select(ContentItem).where(ContentItem.id == row.content_id),
                )
            ).scalar_one_or_none()
            if content is None:
                raise HTTPException(status_code=404, detail="Alert not found")
            guard_resource_client_id(content.client_id)
            client_id = content.client_id

        scope_tenant = await cls._resolve_alert_tenant(db, row, tenant_id=tenant_id)
        return row, scope_tenant, client_id

    @classmethod
    async def _execute_alert(
        cls,
        db: AsyncSession,
        *,
        alert_id: UUID,
        action_id: str,
        actor_id: UUID | None,
        tenant_id: UUID | None,
        note: str | None,
    ) -> tuple[OperatorWorkspaceActionResult, UUID, UUID | None]:
        alert, scope_tenant, client_id = await cls._load_alert_scoped(
            db, alert_id, tenant_id=tenant_id,
        )

        if action_id == ACTION_ACKNOWLEDGE_ALERT:
            if alert.state == "resolved":
                raise HTTPException(
                    status_code=409,
                    detail="Alert was already resolved — refresh the workspace",
                )
            if alert.state not in ("open", "acknowledged"):
                raise HTTPException(
                    status_code=409,
                    detail="Alert is no longer eligible for acknowledgement — refresh the workspace",
                )
            response = await PublishOperatorAlertService.acknowledge(
                db, scope_tenant, alert_id, actor_id=actor_id,
            )
            await db.commit()
            still = response.state in ("open", "acknowledged")
            return (
                OperatorWorkspaceActionResult(
                    success=True,
                    action_id=action_id,
                    message="Alert acknowledged",
                    canonical_state={"id": str(response.id), "state": response.state},
                    attention_still_relevant=still,
                    refresh_recommended=True,
                ),
                scope_tenant,
                client_id,
            )

        # resolve
        if alert.state not in ("open", "acknowledged", "resolved"):
            raise HTTPException(
                status_code=409,
                detail="Alert is no longer eligible for resolve — refresh the workspace",
            )
        response = await PublishOperatorAlertService.resolve_manual(
            db, scope_tenant, alert_id, actor_id=actor_id, note=note,
        )
        await db.commit()
        return (
            OperatorWorkspaceActionResult(
                success=True,
                action_id=action_id,
                message="Alert resolved",
                canonical_state={"id": str(response.id), "state": response.state},
                attention_still_relevant=False,
                refresh_recommended=True,
            ),
            scope_tenant,
            client_id,
        )

    @classmethod
    async def _execute_retry(
        cls,
        db: AsyncSession,
        *,
        attempt_id: UUID,
        tenant_id: UUID | None,
        actor_id: UUID | None = None,
    ) -> tuple[OperatorWorkspaceActionResult, UUID | None, UUID | None]:
        del actor_id  # recorded by execute() wrapper
        ctx = get_auth_context()
        scope_tenant = tenant_id
        if ctx and ctx.is_tenant:
            scope_tenant = ctx.tenant_id

        attempt = await PublishAttemptOpsService._load_attempt(
            db, attempt_id, tenant_id=scope_tenant,
        )

        # Client attribution is best-effort for audit only; never block retry.
        client_id: UUID | None = getattr(attempt, "client_id", None)
        if not isinstance(client_id, UUID):
            client_id = None

        # Re-check Workspace eligibility (stricter than canonical).
        allowed, reason = workspace_retry_allowed(attempt)
        if not allowed:
            raise HTTPException(
                status_code=409,
                detail=reason or "Retry is no longer available — refresh the workspace",
            )

        # Extra live-success guard before delegating (canonical also checks).
        if attempt.idempotency_key:
            prior = await PublishResilienceService.find_live_success(
                db, idempotency_key=attempt.idempotency_key,
            )
            if prior is not None:
                raise HTTPException(
                    status_code=409,
                    detail="Destination already published — retry blocked to prevent duplicates",
                )

        result = await PublishAttemptOpsService.manual_retry(
            db, attempt_id, tenant_id=scope_tenant,
        )
        if not result.get("ok"):
            blocked = result.get("retry_blocked_reason") or result.get("message")
            raise HTTPException(
                status_code=409,
                detail=str(blocked or "Retry unavailable — refresh the workspace"),
            )

        return (
            OperatorWorkspaceActionResult(
                success=True,
                action_id=ACTION_RETRY_PUBLISH,
                message=str(result.get("message") or "Publish retry completed"),
                canonical_state={
                    "attempt_id": str(attempt_id),
                    "content_id": str(result.get("content_id")) if result.get("content_id") else None,
                    "status": result.get("status"),
                },
                attention_still_relevant=not bool(result.get("ok")),
                refresh_recommended=True,
                redirect_path=f"/content/{result['content_id']}" if result.get("content_id") else None,
            ),
            scope_tenant,
            client_id,
        )

    @classmethod
    async def _execute_approve(
        cls,
        db: AsyncSession,
        *,
        content_id: UUID,
        actor_id: UUID | None = None,
        tenant_id: UUID | None = None,
    ) -> tuple[OperatorWorkspaceActionResult, UUID | None, UUID | None]:
        del actor_id  # recorded by execute() wrapper
        item = await ContentService.get(db, content_id)
        client_id = item.client_id
        ctx = get_auth_context()
        scope_tenant = tenant_id
        if ctx and ctx.is_tenant:
            scope_tenant = ctx.tenant_id

        # Idempotent: already internally approved → success, no duplicate transition.
        if item.status == "approved" and item.approved_at is not None:
            return (
                OperatorWorkspaceActionResult(
                    success=True,
                    action_id=ACTION_APPROVE_CONTENT,
                    message="Content already approved",
                    canonical_state={
                        "content_id": str(item.id),
                        "status": item.status,
                        "client_review_status": item.client_review_status,
                    },
                    attention_still_relevant=False,
                    refresh_recommended=True,
                ),
                scope_tenant,
                client_id,
            )

        # Must still be in internal-review statuses (not waiting for client, not published).
        if item.status not in INTERNAL_REVIEW_STATUSES:
            raise HTTPException(
                status_code=409,
                detail="Content is no longer eligible for internal approval — refresh the workspace",
            )
        if item.client_review_status in (CLIENT_REVIEW_PENDING, CLIENT_REVIEW_CHANGES):
            raise HTTPException(
                status_code=409,
                detail="Content is waiting for client review — internal approve is not available",
            )

        approved = await ContentService.approve(db, content_id)
        return (
            OperatorWorkspaceActionResult(
                success=True,
                action_id=ACTION_APPROVE_CONTENT,
                message="Content approved — client review started where configured",
                canonical_state={
                    "content_id": str(approved.id),
                    "status": approved.status,
                    "client_review_status": approved.client_review_status,
                },
                attention_still_relevant=False,
                refresh_recommended=True,
                redirect_path=f"/content/{approved.id}",
            ),
            scope_tenant,
            client_id,
        )


def derive_actions_for_item(item: OperatorAttentionItem) -> list[OperatorWorkspaceAction]:
    return OperatorWorkspaceActionService.derive_actions(item)
