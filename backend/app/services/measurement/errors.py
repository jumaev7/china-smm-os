"""Stable, typed errors for the Marketing Intelligence measurement services.

Mirrors the pattern in ``app.services.campaign_planner.errors``: every error
carries a machine-stable ``code`` plus an HTTP status so the API surface is
consistent. Cross-tenant access always resolves to 404 (never 403), so callers
cannot distinguish "not found" from "not yours".
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class MeasurementError(Exception):
    code: str = "measurement_error"
    http_status: int = 400

    def __init__(self, message: str | None = None, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message or self.code)
        self.message = message or self.code
        self.details = details or {}

    def to_http(self) -> HTTPException:
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return HTTPException(status_code=self.http_status, detail=payload)


# ---------------------------------------------------------------------------
# Not-found family (404)
# ---------------------------------------------------------------------------


class PublicationNotFoundError(MeasurementError):
    code = "publication_not_found"
    http_status = 404


class SnapshotNotFoundError(MeasurementError):
    code = "snapshot_not_found"
    http_status = 404


class IngestionRunNotFoundError(MeasurementError):
    code = "ingestion_run_not_found"
    http_status = 404


class MeasurementJobNotFoundError(MeasurementError):
    code = "measurement_job_not_found"
    http_status = 404


class TrackedLinkNotFoundError(MeasurementError):
    code = "tracked_link_not_found"
    http_status = 404


class AnomalyNotFoundError(MeasurementError):
    code = "anomaly_not_found"
    http_status = 404


class AttributionRecordNotFoundError(MeasurementError):
    code = "attribution_record_not_found"
    http_status = 404


class KpiNotFoundError(MeasurementError):
    code = "kpi_not_found"
    http_status = 404


class CampaignNotFoundError(MeasurementError):
    code = "campaign_not_found"
    http_status = 404


# ---------------------------------------------------------------------------
# Validation / limits (422)
# ---------------------------------------------------------------------------


class ValidationError(MeasurementError):
    code = "validation_error"
    http_status = 422


class LimitExceededError(MeasurementError):
    code = "limit_exceeded"
    http_status = 422


class UnsupportedCapabilityError(MeasurementError):
    """Raised when a platform/adapter cannot fulfil a requested capability.

    E.g. requesting live post-level metrics from Telegram, or a metric key
    that has no provider mapping for the given platform.
    """

    code = "unsupported_capability"
    http_status = 422


class InvalidMetricKeyError(MeasurementError):
    code = "invalid_metric_key"
    http_status = 422


# ---------------------------------------------------------------------------
# Rate limiting (429)
# ---------------------------------------------------------------------------


class RefreshRateLimitedError(MeasurementError):
    code = "refresh_rate_limited"
    http_status = 429


# ---------------------------------------------------------------------------
# Conflict / state (409)
# ---------------------------------------------------------------------------


class AccountDisconnectedError(MeasurementError):
    code = "account_disconnected"
    http_status = 409


class DuplicateError(MeasurementError):
    code = "duplicate_resource"
    http_status = 409


class ConcurrencyConflictError(MeasurementError):
    code = "concurrency_conflict"
    http_status = 409


__all__ = [
    "MeasurementError",
    "PublicationNotFoundError",
    "SnapshotNotFoundError",
    "IngestionRunNotFoundError",
    "MeasurementJobNotFoundError",
    "TrackedLinkNotFoundError",
    "AnomalyNotFoundError",
    "AttributionRecordNotFoundError",
    "KpiNotFoundError",
    "CampaignNotFoundError",
    "ValidationError",
    "LimitExceededError",
    "UnsupportedCapabilityError",
    "InvalidMetricKeyError",
    "RefreshRateLimitedError",
    "AccountDisconnectedError",
    "DuplicateError",
    "ConcurrencyConflictError",
]
