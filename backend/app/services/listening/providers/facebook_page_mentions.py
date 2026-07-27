"""Facebook Page tagged/mention observations — live read-only listening adapter.

Official docs:
- https://developers.facebook.com/docs/graph-api/reference/page/feed/ (/{page-id}/tagged)
- https://developers.facebook.com/docs/pages-api/ (Mentions → pages_read_user_content)
- https://developers.facebook.com/docs/permissions/ (pages_read_user_content)

Observes public posts in which an authorized Facebook Page is tagged.
Does not support keyword search, competitor scraping, or DMs.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.services.listening.providers.base import ListeningSourceAdapter
from app.services.listening.providers.meta_errors import MetaListeningError
from app.services.listening.providers.meta_graph_read import (
    PROVIDER_CAPABILITY_VERSION,
    REQUIRED_FACEBOOK_MENTIONS_PERMISSIONS,
    fetch_page_tagged,
    probe_capability,
)
from app.services.listening.providers.meta_capability_matrix import matrix_entry
from app.services.listening.providers.meta_errors import public_failure_summary
from app.services.listening.schemas import ObservationPage, RawObservation, SourceCapabilities

logger = logging.getLogger(__name__)

SOURCE_TYPE = "facebook_page_mentions"


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        cleaned = value.replace("+0000", "+00:00")
        if cleaned.endswith("Z"):
            cleaned = cleaned[:-1] + "+00:00"
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


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


def _tagged_to_observation(item: dict[str, Any], *, page_id: str) -> RawObservation:
    external_id = str(item.get("id") or "").strip()
    if not external_id:
        return RawObservation(malformed=True, reject_reason="missing_tagged_id")

    from_obj = item.get("from") if isinstance(item.get("from"), dict) else {}
    author_id = str(from_obj.get("id") or "").strip() or None
    author_name = str(from_obj.get("name") or "").strip() or None
    message = item.get("message")
    if message is not None and not isinstance(message, str):
        message = str(message)
    permalink = item.get("permalink_url")
    if permalink is not None:
        permalink = str(permalink).strip() or None

    return RawObservation(
        provider_external_id=external_id,
        canonical_url=permalink,
        author_display=author_name,
        author_external_id=author_id,
        content_text=message,
        content_type="post",
        published_at=_parse_dt(item.get("created_time")),
        source_updated_at=_parse_dt(item.get("updated_time")),
        engagement=None,
        provider_account_ref=f"facebook_page:{page_id}",
        raw_safe_summary={
            "provider": "meta",
            "source_type": SOURCE_TYPE,
            "page_id": page_id,
            "capability_version": PROVIDER_CAPABILITY_VERSION,
            "observation_kind": "page_tagged",
        },
    )


class FacebookPageMentionsAdapter(ListeningSourceAdapter):
    source_type = SOURCE_TYPE

    def capabilities(self) -> SourceCapabilities:
        matrix = matrix_entry("direct_account_mentions") or {}
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
            owned_content_comments=False,
            direct_account_mentions=True,
            hashtag_discovery=False,
            keyword_search=False,
            replies=False,
            content_updates=True,
            deletion_events=False,
            polling=True,
            webhooks=False,
            historical_window="provider_default_tagged",
            freshness_expectation="poll_interval",
            required_permissions=tuple(sorted(REQUIRED_FACEBOOK_MENTIONS_PERMISSIONS)),
            provider_limitation_text=(
                "Observes public posts that tag the authorized Facebook Page via "
                "GET /{page-id}/tagged — independent of owned-content comments. "
                "Not global keyword listening. Not Instagram @mentions. Not DMs. "
                "pages_read_user_content on the token is necessary but not sufficient; "
                "live probe of /tagged is required. Production requires Meta App Review "
                "+ Advanced Access beyond Development-mode app roles."
            ),
            observation_origin="live_provider",
            notes=(
                f"Meta Graph GET /{{page-id}}/tagged ({PROVIDER_CAPABILITY_VERSION}). "
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
            missing = sorted(REQUIRED_FACEBOOK_MENTIONS_PERMISSIONS - set(granted))
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
            probe = await probe_capability(
                kind="direct_account_mentions",
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
        _ = items
        token = _runtime_token(config)
        page_id = _page_id(config)
        hard_limit = max(1, min(int(limit), 200))
        request_id = f"fb_mentions_{uuid4().hex[:12]}"

        try:
            rows, next_cursor = await fetch_page_tagged(
                page_id=page_id,
                access_token=token,
                limit=hard_limit,
                after=cursor,
            )
        except MetaListeningError as exc:
            return ObservationPage(
                items=[],
                next_cursor=cursor,  # do not advance on fatal provider failure
                provider_request_id=request_id,
                fetched_count=0,
                rejected_count=0,
                error_summary=exc.code,
            )

        observations: list[RawObservation] = []
        rejected = 0
        for row in rows:
            obs = _tagged_to_observation(row, page_id=page_id)
            if obs.malformed:
                rejected += 1
                continue
            observations.append(obs)

        return ObservationPage(
            items=observations,
            next_cursor=next_cursor,
            provider_request_id=request_id,
            fetched_count=len(observations),
            rejected_count=rejected,
            error_summary=None,
        )


__all__ = ["FacebookPageMentionsAdapter", "SOURCE_TYPE"]
