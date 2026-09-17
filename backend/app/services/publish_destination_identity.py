"""I1 — publication destination identity comparison.

Compares the *external* publish destination, not merely PublishingAccount UUIDs.

Outcomes:
  SAME_DESTINATION            — proven same external destination (incl. aliases)
  PROVEN_DISTINCT_DESTINATION — proven different external destinations
  UNRESOLVED_DESTINATION      — missing / ambiguous / inconsistent identity

Only PROVEN_DISTINCT_DESTINATION may authorize a cross-account provider write
after existing gates pass. UUID inequality alone never proves distinction.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.models.publishing_account import PublishingAccount
from app.utils.telegram_publish_destination import (
    normalize_telegram_publish_chat_id,
    validate_telegram_publish_chat_id,
)

SAME_DESTINATION = "SAME_DESTINATION"
PROVEN_DISTINCT_DESTINATION = "PROVEN_DISTINCT_DESTINATION"
UNRESOLVED_DESTINATION = "UNRESOLVED_DESTINATION"

DESTINATION_IDENTITY_UNRESOLVED_REASON = "destination_identity_unresolved"
DESTINATION_IDENTITY_UNRESOLVED_FAILURE_CODE = "destination_identity_unresolved"


@dataclass(frozen=True)
class ExternalDestinationRef:
    """Canonical provider destination when the data model can prove it."""

    platform: str
    kind: str
    value: str


def normalize_platform(platform: str | None) -> str:
    return (platform or "").strip().lower()


def extract_external_destination(
    account: PublishingAccount | None,
    *,
    platform: str | None = None,
) -> ExternalDestinationRef | None:
    """Return the established provider destination for *account*, or None.

    Established identifiers (do not invent fallbacks):
      - telegram  → normalized chat id / @channel (``account_id``)
      - facebook  → ``facebook_page_id`` only
      - instagram → ``instagram_business_account_id`` only

    Display names and bare UUID inequality are never used as proof.
    Platforms without an established canonical field yield None (unresolved).
    """
    if account is None:
        return None
    plat = normalize_platform(platform or getattr(account, "platform", None))
    if not plat:
        return None

    if plat == "telegram":
        raw = (getattr(account, "account_id", None) or "").strip()
        if not raw:
            return None
        try:
            validated = validate_telegram_publish_chat_id(raw)
            if validated:
                return ExternalDestinationRef(plat, "telegram_chat_id", validated)
            # Mock / test chat ids may not pass strict publish validation
            # (e.g. ``tg-a``). Normalize conservatively and treat non-empty
            # account_id as the telegram destination token when validation
            # rejects — still platform-local and never a display name.
            normalized = normalize_telegram_publish_chat_id(raw)
        except ValueError:
            try:
                normalized = normalize_telegram_publish_chat_id(raw)
            except ValueError:
                return None
        if not normalized:
            return None
        return ExternalDestinationRef(plat, "telegram_chat_id", normalized)

    if plat == "facebook":
        page = (getattr(account, "facebook_page_id", None) or "").strip()
        if not page:
            return None
        return ExternalDestinationRef(plat, "facebook_page_id", page)

    if plat == "instagram":
        ig = (getattr(account, "instagram_business_account_id", None) or "").strip()
        if not ig:
            return None
        return ExternalDestinationRef(plat, "instagram_business_account_id", ig)

    # tiktok / linkedin / unknown — no established canonical destination field.
    return None


def compare_publication_destinations(
    *,
    platform: str | None,
    intended_account_id: UUID | None,
    intended_account: PublishingAccount | None = None,
    prior_account_id: UUID | None,
    prior_account: PublishingAccount | None = None,
) -> str:
    """Compare intended vs prior destination; never use UUID inequality alone."""
    plat = normalize_platform(platform)

    # Exact same PublishingAccount PK (including both NULL) ⇒ same destination token.
    if intended_account_id is not None and prior_account_id is not None:
        if intended_account_id == prior_account_id:
            return SAME_DESTINATION
    elif intended_account_id is None and prior_account_id is None:
        return SAME_DESTINATION
    else:
        # NULL vs concrete — cannot prove same or distinct safely.
        return UNRESOLVED_DESTINATION

    # Distinct PKs — require proven external identity on both sides.
    intended_ref = extract_external_destination(intended_account, platform=plat)
    prior_ref = extract_external_destination(prior_account, platform=plat)
    if intended_ref is None or prior_ref is None:
        return UNRESOLVED_DESTINATION
    if intended_ref.kind != prior_ref.kind:
        return UNRESOLVED_DESTINATION
    if intended_ref.value == prior_ref.value:
        return SAME_DESTINATION
    return PROVEN_DISTINCT_DESTINATION


def shape_unresolved_destination_result(
    *,
    platform: str,
    account_id: UUID | None,
    account_name: str | None = None,
) -> dict[str, Any]:
    """Fail-closed skip payload — never authorizes a provider write."""
    return {
        "platform": platform,
        "success": False,
        "platform_post_id": None,
        "post_url": None,
        "mock": False,
        "deduplicated": False,
        "destination_identity": UNRESOLVED_DESTINATION,
        "error": (
            "Destination identity unresolved; publication blocked pending "
            "reconciliation"
        ),
        "failure_code": DESTINATION_IDENTITY_UNRESOLVED_FAILURE_CODE,
        "failure_category": "destination",
        "retryable": False,
        "account_id": str(account_id) if account_id else None,
        "account_name": account_name,
    }
