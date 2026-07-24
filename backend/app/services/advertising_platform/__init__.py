"""Read-only advertising provider platform layer.

Public surface for provider adapters. This layer is strictly read-only: it
exposes no create/update/delete/pause/activate/set_budget operations, and never
stores provider tokens (those live on ``publishing_accounts``).
"""
from app.services.advertising_platform.capability_catalog import (
    ALLOWED_READ_CAPABILITIES,
    FORBIDDEN_WRITE_CAPABILITIES,
    assert_read_only,
    is_forbidden_capability,
    is_read_capability,
)
from app.services.advertising_platform.errors import (
    AdvertisingProviderError,
    ProviderPermissionBlockedError,
    ProviderRateLimitedError,
    ProviderUnavailableError,
    ProviderUnsupportedError,
    WriteOperationForbiddenError,
)
from app.services.advertising_platform.interfaces import (
    AdvertisingProviderAdapter,
    DISCONNECTED_CONNECTION_STATUSES,
)
from app.services.advertising_platform.registry import (
    get_adapter,
    registered_providers,
)

__all__ = [
    "ALLOWED_READ_CAPABILITIES",
    "FORBIDDEN_WRITE_CAPABILITIES",
    "assert_read_only",
    "is_forbidden_capability",
    "is_read_capability",
    "AdvertisingProviderError",
    "ProviderUnavailableError",
    "ProviderUnsupportedError",
    "ProviderPermissionBlockedError",
    "ProviderRateLimitedError",
    "WriteOperationForbiddenError",
    "AdvertisingProviderAdapter",
    "DISCONNECTED_CONNECTION_STATUSES",
    "get_adapter",
    "registered_providers",
]
