"""Official Meta capability matrix for Social Listening live adapters.

Capabilities are verified independently. Owned Page comments and tagged
mentions are never collapsed into one capability flag.

Access layers (must not be conflated):
1. permission granted to a token — OAuth scopes on the Page access token
2. Advanced Access / App Review — Meta app access level for Live mode
3. Page/task authorization — token user can perform required Page tasks
4. development-mode availability — app roles / test users only
5. production availability — Live mode + Advanced Access after App Review

A configured permission string does not mean the source is operational.
"""
from __future__ import annotations

from typing import Any

# Graph API version used by settings.META_GRAPH_API_VERSION (default v21.0).
# Official reference docs currently publish against v25.0; path shape is stable.
GRAPH_DOC_VERSION = "v25.0"

CAPABILITY_MATRIX: dict[str, dict[str, Any]] = {
    "owned_content_comments": {
        "source_type": "facebook_page_comments",
        "shipped": True,
        "endpoint_path": "GET /{page-post-id}/comments",
        "supporting_endpoints": ("GET /{page-id}/posts",),
        "graph_api_version": GRAPH_DOC_VERSION,
        "token_type": "Page access token",
        "required_permissions": (
            "pages_show_list",
            "pages_read_engagement",
            "pages_read_user_content",
        ),
        "required_page_tasks": ("MODERATE",),
        "app_review_feature": (
            "pages_read_engagement and pages_read_user_content require App Review "
            "and Advanced Access for production use beyond app roles / Development mode"
        ),
        "eligible_relationship": (
            "Authorized tenant-owned Facebook Page bound via publishing_accounts; "
            "not competitor pages; not PPCA public scraping"
        ),
        "pagination": "cursor (paging.cursors.after / paging.next)",
        "fields_requested": (
            "id,message,created_time,from{id,name},permalink_url,comment_count"
        ),
        "webhook_support": False,
        "polling_support": True,
        "historical_limitations": (
            "Limited to recent Page posts returned by /{page-id}/posts; "
            "feed docs note ~600 ranked published posts/year and max limit 100; "
            "expired posts may become unreadable"
        ),
        "replies_supported": False,
        "deletion_signal": False,
        "production_requires_app_review": True,
        "production_requires_advanced_access": True,
        "official_docs": (
            "https://developers.facebook.com/docs/graph-api/reference/page-post/comments/",
            "https://developers.facebook.com/docs/graph-api/reference/page/feed/",
            "https://developers.facebook.com/docs/permissions/",
            "https://developers.facebook.com/docs/pages-api/comments-mentions/",
        ),
    },
    "direct_account_mentions": {
        "source_type": "facebook_page_mentions",
        "shipped": True,
        "capability_alias": "tagged_mentions",
        "endpoint_path": "GET /{page-id}/tagged",
        "supporting_endpoints": (),
        "graph_api_version": GRAPH_DOC_VERSION,
        "token_type": "Page access token",
        "required_permissions": (
            "pages_show_list",
            "pages_read_user_content",
        ),
        "required_page_tasks": ("MODERATE",),
        "app_review_feature": (
            "pages_read_user_content requires App Review and Advanced Access "
            "for production use beyond app roles / Development mode. "
            "Permission name alone does not prove /tagged is operational."
        ),
        "eligible_relationship": (
            "Public posts that tag the authorized Page; other Pages included "
            "only when authentic (official feed limitation)"
        ),
        "pagination": "cursor (paging.cursors.after / paging.next)",
        "fields_requested": (
            "id,message,created_time,permalink_url,from{id,name},updated_time"
        ),
        "webhook_support": False,
        "polling_support": True,
        "historical_limitations": (
            "Provider-default tagged window; not global keyword search; "
            "not Instagram @mentions; not Messenger"
        ),
        "replies_supported": False,
        "deletion_signal": False,
        "production_requires_app_review": True,
        "production_requires_advanced_access": True,
        "official_docs": (
            "https://developers.facebook.com/docs/graph-api/reference/page/feed/",
            "https://developers.facebook.com/docs/permissions/",
            "https://developers.facebook.com/documentation/pages-api",
            "https://developers.facebook.com/docs/graph-api/reference/page/",
        ),
        "independent_proof": (
            "Documented as a distinct edge /{page-id}/tagged on Page Feed and "
            "Pages API Mentions; pages_read_user_content allowed usage explicitly "
            "lists 'Get posts that your Page is tagged in'."
        ),
    },
}

ACCESS_LAYER_NOTES = (
    "permission_granted_to_token",
    "advanced_access_or_app_review",
    "page_task_authorization",
    "development_mode_availability",
    "production_availability",
)

SANITIZED_HEALTH_CODES = frozenset({
    "missing_scope",
    "insufficient_app_access",
    "page_not_authorized",
    "token_expired_or_revoked",
    "rate_limited",
    "provider_unavailable",
    "unsupported_capability",
})


def matrix_entry(capability_key: str) -> dict[str, Any] | None:
    return CAPABILITY_MATRIX.get(capability_key)


def shipped_capabilities() -> list[dict[str, Any]]:
    return [v for v in CAPABILITY_MATRIX.values() if v.get("shipped")]


__all__ = [
    "CAPABILITY_MATRIX",
    "ACCESS_LAYER_NOTES",
    "SANITIZED_HEALTH_CODES",
    "GRAPH_DOC_VERSION",
    "matrix_entry",
    "shipped_capabilities",
]
