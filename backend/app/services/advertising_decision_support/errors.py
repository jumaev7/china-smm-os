"""Errors for the Advertising Decision Support domain.

Reuses Phase 1 advertising error base so HTTP mapping stays consistent.
Cross-tenant access collapses to 404.
"""
from __future__ import annotations

from typing import Any

from app.services.advertising_intelligence.errors import (
    AdCrossTenantReferenceError,
    AdCurrencyMismatchError,
    AdReadOnlyOperationError,
    AdvertisingError,
)


class AdDecisionSupportError(AdvertisingError):
    code = "AD_DECISION_SUPPORT_ERROR"
    http_status = 400


class AdComparisonIncompatibleError(AdvertisingError):
    code = "AD_COMPARISON_INCOMPATIBLE"
    http_status = 422


class AdSimulationValidationError(AdvertisingError):
    code = "AD_SIMULATION_VALIDATION"
    http_status = 422


class AdSimulationNotFoundError(AdvertisingError):
    code = "AD_SIMULATION_NOT_FOUND"
    http_status = 404


class AdExperimentNotFoundError(AdvertisingError):
    code = "AD_EXPERIMENT_NOT_FOUND"
    http_status = 404


class AdExperimentStateError(AdvertisingError):
    code = "AD_EXPERIMENT_STATE"
    http_status = 409


class AdExperimentValidationError(AdvertisingError):
    code = "AD_EXPERIMENT_VALIDATION"
    http_status = 422


class AdChangePlanNotFoundError(AdvertisingError):
    code = "AD_CHANGE_PLAN_NOT_FOUND"
    http_status = 404


class AdChangePlanStateError(AdvertisingError):
    code = "AD_CHANGE_PLAN_STATE"
    http_status = 409


class AdEntityNotFoundError(AdvertisingError):
    code = "AD_ENTITY_NOT_FOUND"
    http_status = 404


ERROR_CODE_TO_CLASS: dict[str, type[AdvertisingError]] = {
    cls.code: cls
    for cls in (
        AdDecisionSupportError,
        AdComparisonIncompatibleError,
        AdSimulationValidationError,
        AdSimulationNotFoundError,
        AdExperimentNotFoundError,
        AdExperimentStateError,
        AdExperimentValidationError,
        AdChangePlanNotFoundError,
        AdChangePlanStateError,
        AdEntityNotFoundError,
        AdCurrencyMismatchError,
        AdCrossTenantReferenceError,
        AdReadOnlyOperationError,
    )
}


__all__ = [
    "AdDecisionSupportError",
    "AdComparisonIncompatibleError",
    "AdSimulationValidationError",
    "AdSimulationNotFoundError",
    "AdExperimentNotFoundError",
    "AdExperimentStateError",
    "AdExperimentValidationError",
    "AdChangePlanNotFoundError",
    "AdChangePlanStateError",
    "AdEntityNotFoundError",
    "ERROR_CODE_TO_CLASS",
]
