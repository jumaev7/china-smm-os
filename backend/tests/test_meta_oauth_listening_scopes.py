"""HIGH-4: Meta OAuth scopes include Listening read permissions."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from app.core.config import settings
from app.services.meta_graph_client import (
    LISTENING_FACEBOOK_READ_PERMISSIONS,
    REQUIRED_CONNECTION_PERMISSIONS,
    REQUIRED_FACEBOOK_PUBLISH_PERMISSIONS,
    REQUIRED_INSTAGRAM_PUBLISH_PERMISSIONS,
    build_oauth_authorize_url,
)
from app.services.listening.providers.meta_graph_read import (
    REQUIRED_FACEBOOK_COMMENTS_PERMISSIONS,
    REQUIRED_FACEBOOK_MENTIONS_PERMISSIONS,
)


def _scope_set(raw: str) -> set[str]:
    return {s.strip() for s in (raw or "").split(",") if s.strip()}


def test_default_meta_oauth_scopes_include_listening_reads():
    scopes = _scope_set(settings.META_OAUTH_SCOPES)
    assert "pages_read_engagement" in scopes
    assert "pages_read_user_content" in scopes
    assert LISTENING_FACEBOOK_READ_PERMISSIONS.issubset(scopes)


def test_default_scopes_include_publish_and_connection_minimum():
    scopes = _scope_set(settings.META_OAUTH_SCOPES)
    assert REQUIRED_CONNECTION_PERMISSIONS.issubset(scopes)
    assert REQUIRED_FACEBOOK_PUBLISH_PERMISSIONS.issubset(scopes)
    assert REQUIRED_INSTAGRAM_PUBLISH_PERMISSIONS.issubset(scopes)


def test_authorize_url_requests_listening_scopes():
    url = build_oauth_authorize_url(state="test-state")
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    scopes = _scope_set(qs.get("scope", [""])[0])
    assert LISTENING_FACEBOOK_READ_PERMISSIONS.issubset(scopes)
    assert "pages_read_engagement" in scopes
    assert "pages_read_user_content" in scopes


def test_listening_capability_permission_sets_covered_by_oauth_default():
    scopes = _scope_set(settings.META_OAUTH_SCOPES)
    assert REQUIRED_FACEBOOK_COMMENTS_PERMISSIONS.issubset(scopes)
    assert REQUIRED_FACEBOOK_MENTIONS_PERMISSIONS.issubset(scopes)


def test_scopes_are_minimum_not_arbitrarily_broad():
    scopes = _scope_set(settings.META_OAUTH_SCOPES)
    # Must not request unrelated broad permissions.
    forbidden = {
        "email",
        "user_friends",
        "publish_video",
        "pages_manage_ads",
        "ads_management",
        "read_insights",
    }
    assert scopes.isdisjoint(forbidden)


if __name__ == "__main__":
    test_default_meta_oauth_scopes_include_listening_reads()
    test_default_scopes_include_publish_and_connection_minimum()
    test_authorize_url_requests_listening_scopes()
    test_listening_capability_permission_sets_covered_by_oauth_default()
    test_scopes_are_minimum_not_arbitrarily_broad()
    print("meta oauth listening scope tests passed")
