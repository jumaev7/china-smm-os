"""Stable, typed errors for the Campaign Planner.

Every error carries a machine-stable ``code`` plus an HTTP status so the API can
surface a consistent contract. Cross-tenant access is always surfaced as 404.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class CampaignPlannerError(Exception):
    code: str = "campaign_planner_error"
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


class CampaignNotFoundError(CampaignPlannerError):
    code = "campaign_not_found"
    http_status = 404


class CampaignChildNotFoundError(CampaignPlannerError):
    code = "campaign_child_not_found"
    http_status = 404


class PlanVersionNotFoundError(CampaignPlannerError):
    code = "plan_version_not_found"
    http_status = 404


class SlotNotFoundError(CampaignPlannerError):
    code = "slot_not_found"
    http_status = 404


class PillarNotFoundError(CampaignPlannerError):
    code = "pillar_not_found"
    http_status = 404


class ContentNotFoundError(CampaignPlannerError):
    code = "content_not_found"
    http_status = 404


class ReviewNotFoundError(CampaignPlannerError):
    code = "review_not_found"
    http_status = 404


class AIRequestNotFoundError(CampaignPlannerError):
    code = "ai_request_not_found"
    http_status = 404


class CampaignStateError(CampaignPlannerError):
    code = "campaign_invalid_state"
    http_status = 409


class PlanImmutableError(CampaignPlannerError):
    code = "plan_version_immutable"
    http_status = 409


class ConcurrencyConflictError(CampaignPlannerError):
    code = "concurrency_conflict"
    http_status = 409


class PlanConfigurationError(CampaignPlannerError):
    code = "plan_configuration_invalid"
    http_status = 422


class ValidationError(CampaignPlannerError):
    code = "validation_error"
    http_status = 422


class LimitExceededError(CampaignPlannerError):
    code = "limit_exceeded"
    http_status = 422


class AssignmentBlockedError(CampaignPlannerError):
    code = "assignment_blocked"
    http_status = 422


class DuplicateError(CampaignPlannerError):
    code = "duplicate_resource"
    http_status = 409


__all__ = [
    "CampaignPlannerError",
    "CampaignNotFoundError",
    "CampaignChildNotFoundError",
    "PlanVersionNotFoundError",
    "SlotNotFoundError",
    "PillarNotFoundError",
    "ContentNotFoundError",
    "ReviewNotFoundError",
    "AIRequestNotFoundError",
    "CampaignStateError",
    "PlanImmutableError",
    "ConcurrencyConflictError",
    "PlanConfigurationError",
    "ValidationError",
    "LimitExceededError",
    "AssignmentBlockedError",
    "DuplicateError",
]
