"""Facebook Page owned-post comments — live read-only listening adapter.

Official docs:
- https://developers.facebook.com/docs/graph-api/reference/page-post/comments/
- https://developers.facebook.com/docs/permissions/ (pages_read_user_content)
- https://developers.facebook.com/docs/pages-api/comments-mentions/

Observes comments on posts owned by an authorized Facebook Page. Does not
support keyword search, competitor pages, DMs, or comment creation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.listening.providers.base import ListeningSourceAdapter
from app.services.listening.providers.meta_errors import MetaListeningError
from app.services.listening.providers.meta_graph_read import (
    PROVIDER_CAPABILITY_VERSION,
    REQUIRED_FACEBOOK_COMMENTS_PERMISSIONS,
    fetch_page_posts,
    fetch_post_comments,
    probe_capability,
)
from app.services.listening.providers.meta_capability_matrix import matrix_entry
from app.services.listening.providers.meta_errors import public_failure_summary
from app.services.listening.schemas import ObservationPage, RawObservation, SourceCapabilities

logger = logging.getLogger(__name__)

SOURCE_TYPE = "facebook_page_comments"
MAX_POSTS_PER_PAGE = 8
MAX_COMMENTS_PER_POST = 25


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        # Graph returns ISO8601 with +0000 or Z
        cleaned = value.replace("+0000", "+00:00")
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _decode_cursor(cursor: str | None) -> dict[str, Any]:
    if not cursor:
        return {}
    try:
        data = json.loads(cursor)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {"posts_after": cursor}


def _encode_cursor(data: dict[str, Any]) -> str | None:
    if not data:
        return None
    return json.dumps(data, separators=(",", ":"), sort_keys=True)


def _runtime_token(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    token = cfg.get("_runtime_page_access_token")
    if not token or not isinstance(token, str):
        raise MetaListeningError(
            "missing_credentials",
            "Page access token unavailable for live fetch",
            retryable=False,
        )
    return token


def _page_id(config: dict[str, Any] | None) -> str:
    cfg = config or {}
    page_id = (
        cfg.get("provider_resource_ref")
        or cfg.get("facebook_page_id")
        or cfg.get("page_id")
        or ""
    )
    page_id = str(page_id).strip()
    if not page_id:
        raise MetaListeningError(
            "invalid_configuration",
            "facebook_page_id / provider_resource_ref is required",
            retryable=False,
        )
    return page_id


def _comment_to_observation(
    comment: dict[str, Any],
    *,
    page_id: str,
    post_id: str,
) -> RawObservation:
    comment_id = str(comment.get("id") or "").strip()
    if not comment_id:
        return RawObservation(malformed=True, reject_reason="missing_comment_id")

    from_obj = comment.get("from") if isinstance(comment.get("from"), dict) else {}
    author_id = str(from_obj.get("id") or "").strip() or None
    author_name = str(from_obj.get("name") or "").strip() or None
    # Minimize author data: display name + page-scoped id only.
    message = comment.get("message")
    if message is not None and not isinstance(message, str):
        message = str(message)

    permalink = comment.get("permalink_url")
    if permalink is not None:
        permalink = str(permalink).strip() or None

    return RawObservation(
        provider_external_id=comment_id,
        canonical_url=permalink,
        author_display=author_name,
        author_external_id=author_id,
        content_text=message,
        content_type="comment",
        published_at=_parse_dt(comment.get("created_time")),
        source_updated_at=None,
        engagement=None,
        provider_account_ref=f"facebook_page:{page_id}",
        raw_safe_summary={
            "provider": "meta",
            "source_type": SOURCE_TYPE,
            "page_id": page_id,
            "parent_post_id": post_id,
            "capability_version": PROVIDER_CAPABILITY_VERSION,
        },
    )


class FacebookPageCommentsAdapter(ListeningSourceAdapter):
    source_type = SOURCE_TYPE

    def capabilities(self) -> SourceCapabilities:
        matrix = matrix_entry("owned_content_comments") or {}
        return SourceCapabilities(
            source_type=SOURCE_TYPE,
            capability_status="live",
            supports_keyword_search=False,
            supports_account_feed=True,
            supports_historical_window=True,
            pagination_type="cursor",
            engagement_fields_available=False,
            author_fields_available=True,
            deletion_signals_available=False,
            owned_content_comments=True,
            direct_account_mentions=False,
            hashtag_discovery=False,
            keyword_search=False,
            replies=False,
            content_updates=True,
            deletion_events=False,
            polling=True,
            webhooks=False,
            historical_window="provider_default_recent_posts",
            freshness_expectation="poll_interval",
            required_permissions=tuple(sorted(REQUIRED_FACEBOOK_COMMENTS_PERMISSIONS)),
            provider_limitation_text=(
                "Observes comments on posts owned by the authorized Facebook Page only. "
                "Not global keyword listening. Not competitor pages. Not Instagram. "
                "Not Messenger/DMs. Not tagged mentions (separate capability). "
                "Requires pages_read_user_content + pages_read_engagement on a Page "
                "access token with MODERATE task. Permission grant ≠ operational: "
                "Advanced Access/App Review and Page authorization are also required. "
                "Production use requires Meta App Review + Advanced Access."
            ),
            observation_origin="live_provider",
            notes=(
                f"Meta Graph GET /{{page-post-id}}/comments ({PROVIDER_CAPABILITY_VERSION}). "
                f"Docs: {', '.join(matrix.get('official_docs') or ())}."
            ),
        )

    async def validate_configuration(self, config: dict[str, Any] | None) -> list[str]:
        errors: list[str] = []
        cfg = config or {}
        if not cfg.get("publishing_account_id") and not cfg.get("integration_id"):
            errors.append("publishing_account_id is required")
        page_id = (
            cfg.get("provider_resource_ref")
            or cfg.get("facebook_page_id")
            or cfg.get("page_id")
        )
        if not page_id:
            errors.append("provider_resource_ref (Facebook Page id) is required")
        granted = cfg.get("granted_permissions")
        if isinstance(granted, list):
            missing = sorted(REQUIRED_FACEBOOK_COMMENTS_PERMISSIONS - set(granted))
            if missing:
                errors.append(f"missing_scope:{','.join(missing)}")
        status = str(cfg.get("integration_status") or "").strip().lower()
        if status in {"revoked", "expired", "invalid", "disconnected", "missing_permissions"}:
            errors.append(f"integration_status:{status}")
        return errors

    async def health_check(self, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
        caps = self.capabilities()
        base = {
            "source_type": self.source_type,
            "capability_status": caps.capability_status,
            "notes": caps.notes,
            "required_permissions": list(caps.required_permissions),
            "access_layers": [
                "permission_granted_to_token",
                "advanced_access_or_app_review",
                "page_task_authorization",
                "development_mode_availability",
                "production_availability",
            ],
        }
        try:
            token = _runtime_token(config)
            page_id = _page_id(config)
            # Capability-specific probe — permission names alone are insufficient.
            probe = await probe_capability(
                kind="owned_content_comments",
                page_id=page_id,
                access_token=token,
            )
            return {**base, "status": "ok", "probe": probe}
        except MetaListeningError as exc:
            return {
                **base,
                "status": exc.code,
                "error_code": exc.code,
                "error_summary": public_failure_summary(exc.code),
                "retryable": exc.retryable,
            }
        except Exception:  # noqa: BLE001
            return {
                **base,
                "status": "internal_processing_failure",
                "error_code": "internal_processing_failure",
                "error_summary": public_failure_summary("internal_processing_failure"),
            }

    async def fetch_observations(
        self,
        *,
        config: dict[str, Any] | None = None,
        cursor: str | None = None,
        limit: int = 50,
        items: list[dict[str, Any]] | None = None,
    ) -> ObservationPage:
        _ = items  # live adapter ignores operator-supplied items
        token = _runtime_token(config)
        page_id = _page_id(config)
        state = _decode_cursor(cursor)
        posts_after = state.get("posts_after")
        resume_post_id = state.get("post_id")
        comment_after = state.get("comment_after")

        hard_limit = max(1, min(int(limit), 200))
        observations: list[RawObservation] = []
        rejected = 0
        request_id = f"fb_comments_{uuid4().hex[:12]}"
        next_state: dict[str, Any] = {}
        fatal: MetaListeningError | None = None

        try:
            posts, next_posts_after = await fetch_page_posts(
                page_id=page_id,
                access_token=token,
                limit=MAX_POSTS_PER_PAGE,
                after=str(posts_after) if posts_after else None,
            )
        except MetaListeningError as exc:
            return ObservationPage(
                items=[],
                next_cursor=cursor,
                provider_request_id=request_id,
                fetched_count=0,
                rejected_count=0,
                error_summary=exc.code,
            )

        # Optional resume mid-post when comment pagination was incomplete.
        if resume_post_id:
            posts = [p for p in posts if str(p.get("id")) == str(resume_post_id)] + [
                p for p in posts if str(p.get("id")) != str(resume_post_id)
            ]

        for post in posts:
            if len(observations) >= hard_limit:
                break
            post_id = str(post.get("id") or "").strip()
            if not post_id:
                rejected += 1
                continue
            remaining = hard_limit - len(observations)
            try:
                comments, next_comment_after = await fetch_post_comments(
                    post_id=post_id,
                    access_token=token,
                    limit=min(MAX_COMMENTS_PER_POST, remaining),
                    after=str(comment_after) if (resume_post_id == post_id and comment_after) else None,
                )
            except MetaListeningError as exc:
                fatal = exc
                # Keep observations already collected; do not advance past this post.
                next_state = {
                    "posts_after": posts_after,
                    "post_id": post_id,
                    "comment_after": comment_after,
                }
                break

            comment_after = None
            resume_post_id = None
            for comment in comments:
                obs = _comment_to_observation(comment, page_id=page_id, post_id=post_id)
                if obs.malformed:
                    rejected += 1
                    continue
                observations.append(obs)
                if len(observations) >= hard_limit:
                    break

            if next_comment_after and len(observations) >= hard_limit:
                next_state = {
                    "posts_after": posts_after,
                    "post_id": post_id,
                    "comment_after": next_comment_after,
                }
                break
        else:
            # Finished all posts in this page.
            if next_posts_after:
                next_state = {"posts_after": next_posts_after}

        error_summary = fatal.code if fatal else None
        # Healthy zero results: completed page with no comments is valid.
        return ObservationPage(
            items=observations,
            next_cursor=_encode_cursor(next_state),
            provider_request_id=request_id,
            fetched_count=len(observations),
            rejected_count=rejected,
            error_summary=error_summary,
        )


__all__ = ["FacebookPageCommentsAdapter", "SOURCE_TYPE"]
