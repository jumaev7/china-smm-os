"""Integration health package — read-only automated diagnostics."""

from app.services.integration_health.service import IntegrationHealthService
from app.services.integration_health.taxonomy import REASON_CODES, reason_meta

__all__ = [
    "IntegrationHealthService",
    "REASON_CODES",
    "reason_meta",
]
