"""Orchestration stub for the per-content preparation pipeline.

`app.api.v1.workflow` (routes under /content/{id}/workflow/*) references start_workflow,
get_progress, and retry_workflow, but no orchestrator for the content-prep pipeline
(subtitles -> translations -> captions -> hashtags -> post_time -> voice -> export) has
been implemented yet. Individual steps already exist as standalone endpoints/services
(see ContentService.burn_subtitled_video, ContentService.generate_voiceover,
ContentService.generate_final_export, app.api.v1.generate). This module provides a
non-crashing, honest placeholder so the router can be imported and called safely until
a real orchestrator is built.
"""
from __future__ import annotations

from uuid import UUID

from app.schemas.content_workflow import WorkflowPrepareRequest, WorkflowProgressResponse

_NOT_IMPLEMENTED_MESSAGE = "Automated content workflow orchestration is not implemented yet."


def get_progress(content_id: UUID) -> WorkflowProgressResponse:
    return WorkflowProgressResponse(
        content_id=content_id,
        status="idle",
        steps=[],
        message=_NOT_IMPLEMENTED_MESSAGE,
        can_retry=False,
    )


async def start_workflow(content_id: UUID, data: WorkflowPrepareRequest) -> WorkflowProgressResponse:
    return WorkflowProgressResponse(
        content_id=content_id,
        status="failed",
        steps=[],
        message=_NOT_IMPLEMENTED_MESSAGE,
        can_retry=False,
    )


async def retry_workflow(content_id: UUID, step: str | None) -> WorkflowProgressResponse:
    return WorkflowProgressResponse(
        content_id=content_id,
        status="failed",
        current_step=step,  # type: ignore[arg-type]
        steps=[],
        message=_NOT_IMPLEMENTED_MESSAGE,
        can_retry=False,
    )
