"""Provider adapter registry for the measurement pipeline."""
from __future__ import annotations

from app.services.measurement.providers.base import MetricProviderAdapter, UnsupportedAdapter
from app.services.measurement.providers.facebook import FacebookAdapter
from app.services.measurement.providers.mock import MockAdapter
from app.services.measurement.providers.telegram import TelegramAdapter

# Platforms with a dedicated adapter implementation.
_ADAPTERS: dict[str, type[MetricProviderAdapter]] = {
    "mock": MockAdapter,
    "telegram": TelegramAdapter,
    "facebook": FacebookAdapter,
}

# Platforms known to the platform catalog but without a dedicated adapter
# yet — served by UnsupportedAdapter (mock_only for mock accounts, otherwise
# unsupported).
_FALLBACK_PLATFORMS = frozenset({"instagram", "tiktok", "linkedin"})

_instances: dict[str, MetricProviderAdapter] = {}


def get_adapter(platform: str) -> MetricProviderAdapter:
    """Return a cached adapter instance for the given platform.

    Unknown platforms (including the currently-unimplemented
    instagram/tiktok/linkedin) resolve to :class:`UnsupportedAdapter`, which
    is mock_only for mock accounts and unsupported otherwise. This function
    never raises — the caller decides how to surface "unsupported".
    """
    if platform in _instances:
        return _instances[platform]

    adapter_cls = _ADAPTERS.get(platform)
    if adapter_cls is not None:
        adapter = adapter_cls()
    else:
        adapter = UnsupportedAdapter(platform)
    _instances[platform] = adapter
    return adapter


def registered_platforms() -> frozenset[str]:
    return frozenset(_ADAPTERS.keys()) | _FALLBACK_PLATFORMS


__all__ = ["get_adapter", "registered_platforms", "MetricProviderAdapter", "UnsupportedAdapter"]
