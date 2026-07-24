"""Capability catalog for the advertising platform layer.

This module encodes the *read-only* contract of the advertising domain at the
capability level. ``ALLOWED_READ_CAPABILITIES`` is the exhaustive set of things
an adapter may ever do; ``FORBIDDEN_WRITE_CAPABILITIES`` enumerates the mutating
operations that are explicitly out of scope and must never be implemented.

The two sets are asserted to be disjoint at import time, and
``assert_read_only`` is provided so callers can defensively reject any attempt
to route a forbidden capability through the platform layer.
"""
from __future__ import annotations

# Everything an advertising adapter is permitted to do. All are read/observe
# operations against a provider.
ALLOWED_READ_CAPABILITIES = frozenset({
    "read_account",
    "read_account_permissions",
    "list_campaigns",
    "list_ad_groups",
    "list_ads",
    "list_creatives",
    "read_insights",
    "read_conversions",
    "read_breakdowns",
    "read_budget",
    "health_check",
})

# Operations that are explicitly forbidden. These are never implemented by any
# adapter and exist here only to make the prohibition auditable.
FORBIDDEN_WRITE_CAPABILITIES = frozenset({
    "create_campaign",
    "update_campaign",
    "delete_campaign",
    "create_ad_group",
    "update_ad_group",
    "delete_ad_group",
    "create_ad",
    "update_ad",
    "delete_ad",
    "create_creative",
    "update_creative",
    "delete_creative",
    "pause",
    "activate",
    "resume",
    "archive",
    "set_budget",
    "update_budget",
    "set_bid",
    "update_bid",
    "set_status",
    "update_targeting",
    "publish",
    "boost_post",
})

# Invariant: read and write capability sets are disjoint.
assert not (ALLOWED_READ_CAPABILITIES & FORBIDDEN_WRITE_CAPABILITIES), (
    "read and write capability sets must be disjoint"
)


def is_read_capability(capability: str) -> bool:
    return capability in ALLOWED_READ_CAPABILITIES


def is_forbidden_capability(capability: str) -> bool:
    return capability in FORBIDDEN_WRITE_CAPABILITIES


def assert_read_only(capability: str) -> None:
    """Raise if ``capability`` is a mutating/unknown operation.

    Any capability not explicitly in ``ALLOWED_READ_CAPABILITIES`` is rejected —
    forbidden ones and unknown ones alike — so new write verbs can never slip
    through unnoticed.
    """
    from app.services.advertising_platform.errors import (
        WriteOperationForbiddenError,
    )

    if capability not in ALLOWED_READ_CAPABILITIES:
        raise WriteOperationForbiddenError(
            f"capability '{capability}' is not a permitted read-only operation",
            details={
                "capability": capability,
                "is_forbidden": capability in FORBIDDEN_WRITE_CAPABILITIES,
            },
        )


__all__ = [
    "ALLOWED_READ_CAPABILITIES",
    "FORBIDDEN_WRITE_CAPABILITIES",
    "is_read_capability",
    "is_forbidden_capability",
    "assert_read_only",
]
