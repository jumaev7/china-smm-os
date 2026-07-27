"""Resolve publishing-account credentials for live listening — never persist tokens."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.publishing_account import PublishingAccount
from app.services.listening.providers.meta_errors import MetaListeningError
from app.utils.token_vault import decrypt_token

logger = logging.getLogger(__name__)

_REVOKED_STATUSES = frozenset({
    "disconnected", "expired", "invalid", "revoked", "blocked", "missing_permissions",
})


@dataclass(frozen=True)
class LiveCredentialBundle:
    publishing_account_id: UUID
    platform: str
    status: str
    page_id: str
    page_name: str | None
    granted_permissions: list[str]
    page_access_token: str

    def __repr__(self) -> str:
        # Never include page_access_token in repr / debugger / logs.
        return (
            "LiveCredentialBundle("
            f"publishing_account_id={self.publishing_account_id!r}, "
            f"platform={self.platform!r}, status={self.status!r}, "
            f"page_id={self.page_id!r}, page_name={self.page_name!r}, "
            f"granted_permissions={self.granted_permissions!r}, "
            "page_access_token='***')"
        )

    def public_config_overlay(self) -> dict[str, Any]:
        """Safe fields that may be merged into runtime config (no token)."""
        return {
            "publishing_account_id": str(self.publishing_account_id),
            "integration_id": str(self.publishing_account_id),
            "provider_resource_ref": self.page_id,
            "facebook_page_id": self.page_id,
            "facebook_page_name": self.page_name,
            "integration_status": self.status,
            "granted_permissions": list(self.granted_permissions),
            "platform": self.platform,
        }


def _parse_permissions(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return sorted({str(x) for x in data if x})
        if isinstance(data, dict):
            scopes = data.get("scopes") or data.get("permissions") or []
            if isinstance(scopes, list):
                return sorted({str(x) for x in scopes if x})
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    return sorted({p.strip() for p in raw.split(",") if p.strip()})


async def resolve_facebook_page_credentials(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    publishing_account_id: UUID,
    expected_page_id: str | None = None,
) -> LiveCredentialBundle:
    """Load and decrypt a tenant-owned Facebook Page token.

    Raises MetaListeningError with stable codes for missing scope / revoked.
    Tokens are returned only in-memory and must never be written to listening tables.
    """
    account = (
        await db.execute(
            select(PublishingAccount).where(
                PublishingAccount.id == publishing_account_id,
                PublishingAccount.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if account is None:
        raise MetaListeningError(
            "invalid_configuration",
            "publishing account not found for tenant",
            retryable=False,
        )
    if account.platform != "facebook":
        raise MetaListeningError(
            "invalid_configuration",
            "listening live Facebook sources require a facebook publishing account",
            retryable=False,
        )

    status = (account.status or "").strip().lower()
    if status in _REVOKED_STATUSES:
        code = "missing_scope" if status == "missing_permissions" else "token_expired_or_revoked"
        raise MetaListeningError(code, f"integration_status:{status}", retryable=False)

    page_id = (account.facebook_page_id or account.account_id or "").strip()
    if not page_id:
        raise MetaListeningError(
            "invalid_configuration",
            "Facebook Page id missing on publishing account",
            retryable=False,
        )
    if expected_page_id and expected_page_id.strip() != page_id:
        raise MetaListeningError(
            "invalid_configuration",
            "provider_resource_ref does not match publishing account page",
            retryable=False,
        )

    if not account.access_token_encrypted:
        # Missing ciphertext ≠ revoked/expired status on the account row.
        raise MetaListeningError(
            "missing_credentials",
            "publishing account has no access token",
            retryable=False,
        )

    try:
        token = decrypt_token(account.access_token_encrypted)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "listening_token_decrypt_failed",
            extra={
                "tenant_id": str(tenant_id),
                "publishing_account_id": str(publishing_account_id),
                "error": type(exc).__name__,
            },
        )
        raise MetaListeningError(
            "missing_credentials",
            "unable to decrypt publishing account token",
            retryable=False,
        ) from exc

    if not token:
        raise MetaListeningError(
            "missing_credentials",
            "empty publishing account token",
            retryable=False,
        )

    return LiveCredentialBundle(
        publishing_account_id=account.id,
        platform=account.platform,
        status=status or "connected",
        page_id=page_id,
        page_name=account.account_name,
        granted_permissions=_parse_permissions(account.permissions_json),
        page_access_token=token,
    )


__all__ = [
    "LiveCredentialBundle",
    "resolve_facebook_page_credentials",
]
