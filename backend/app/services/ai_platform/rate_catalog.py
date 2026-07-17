"""Code-controlled token cost rate catalog (estimates only)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


RATE_CATALOG_VERSION = "1.0.0"


@dataclass(frozen=True)
class RateEntry:
    provider: str
    model: str
    effective_from: date
    input_cost_per_million: int  # minor currency units
    output_cost_per_million: int
    currency: str
    version: str


# Costs are estimates in USD cents per million tokens (minor units = cents).
_RATES: tuple[RateEntry, ...] = (
    RateEntry("mock", "mock-content-standard", date(2026, 1, 1), 0, 0, "USD", RATE_CATALOG_VERSION),
    RateEntry("mock", "mock-content-fast", date(2026, 1, 1), 0, 0, "USD", RATE_CATALOG_VERSION),
    RateEntry("mock", "mock-content-high", date(2026, 1, 1), 0, 0, "USD", RATE_CATALOG_VERSION),
    RateEntry("openai", "gpt-4o-mini", date(2026, 1, 1), 15, 60, "USD", RATE_CATALOG_VERSION),
    RateEntry("openai", "gpt-4o", date(2026, 1, 1), 250, 1000, "USD", RATE_CATALOG_VERSION),
)


def resolve_rate(provider: str, model: str) -> RateEntry | None:
    matches = [r for r in _RATES if r.provider == provider and r.model == model]
    if not matches:
        # Fallback: any provider entry for model prefix
        matches = [r for r in _RATES if r.provider == provider]
    return matches[-1] if matches else None


def estimate_cost_minor(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> tuple[int, str, str]:
    rate = resolve_rate(provider, model)
    if rate is None:
        return 0, "USD", RATE_CATALOG_VERSION
    cost = (
        (input_tokens * rate.input_cost_per_million) // 1_000_000
        + (output_tokens * rate.output_cost_per_million) // 1_000_000
    )
    return int(cost), rate.currency, rate.version
