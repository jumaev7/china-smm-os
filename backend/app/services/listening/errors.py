"""Stable typed errors for Social Listening Phase 1.

Cross-tenant access always resolves to 404 so callers cannot distinguish
"not found" from "not yours".
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


class ListeningError(Exception):
    code: str = "listening_error"
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


class ProjectNotFoundError(ListeningError):
    code = "listening_project_not_found"
    http_status = 404


class SubjectNotFoundError(ListeningError):
    code = "listening_subject_not_found"
    http_status = 404


class QueryNotFoundError(ListeningError):
    code = "listening_query_not_found"
    http_status = 404


class SourceNotFoundError(ListeningError):
    code = "listening_source_not_found"
    http_status = 404


class MentionNotFoundError(ListeningError):
    code = "observed_mention_not_found"
    http_status = 404


class IngestionRunNotFoundError(ListeningError):
    code = "listening_ingestion_run_not_found"
    http_status = 404


class InvalidReviewStateError(ListeningError):
    code = "invalid_review_state"
    http_status = 400


class InvalidProjectStatusError(ListeningError):
    code = "invalid_project_status"
    http_status = 400


class ProjectPausedError(ListeningError):
    code = "listening_project_paused"
    http_status = 409


class ProjectArchivedError(ListeningError):
    code = "listening_project_archived"
    http_status = 409


class SourceUnsupportedError(ListeningError):
    code = "listening_source_unsupported"
    http_status = 422


class ImportValidationError(ListeningError):
    code = "listening_import_validation_error"
    http_status = 400


class ListeningForbiddenError(ListeningError):
    code = "listening_forbidden"
    http_status = 403


class ListeningRateLimitedError(ListeningError):
    code = "listening_rate_limited"
    http_status = 429


__all__ = [
    "ListeningError",
    "ProjectNotFoundError",
    "SubjectNotFoundError",
    "QueryNotFoundError",
    "SourceNotFoundError",
    "MentionNotFoundError",
    "IngestionRunNotFoundError",
    "InvalidReviewStateError",
    "InvalidProjectStatusError",
    "ProjectPausedError",
    "ProjectArchivedError",
    "SourceUnsupportedError",
    "ImportValidationError",
    "ListeningForbiddenError",
    "ListeningRateLimitedError",
]
