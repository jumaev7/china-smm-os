"""OAuth / access-log redaction and audit-detail scrubbing."""
from __future__ import annotations

import logging

from uvicorn.logging import AccessFormatter

from app.core.access_log_redaction import (
    SensitiveAccessLogFilter,
    sanitize_request_path,
    scrub_audit_details,
)


def test_sanitize_oauth_callback_collapses_query():
    path = (
        "/api/v1/publishing/meta/oauth/callback"
        "?code=AQBsupersecretcode123&state=eyJhbGciOi.jwt.payload"
    )
    cleaned = sanitize_request_path(path)
    assert "AQBsupersecretcode123" not in cleaned
    assert "eyJhbGciOi" not in cleaned
    assert cleaned.startswith("/api/v1/publishing/meta/oauth/callback")
    assert "[REDACTED]" in cleaned


def test_sanitize_named_sensitive_params_elsewhere():
    path = "/api/v1/other?foo=1&access_token=EAABSECRET&bar=2"
    cleaned = sanitize_request_path(path)
    assert "EAABSECRET" not in cleaned
    assert "foo=1" in cleaned
    assert "bar=2" in cleaned
    assert "access_token=[REDACTED]" in cleaned


def test_non_sensitive_query_preserved():
    path = "/api/v1/clients?tenant_id=abc&page=2"
    assert sanitize_request_path(path) == path


def test_uvicorn_access_filter_preserves_tuple_shape():
    filt = SensitiveAccessLogFilter()
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1",
            "GET",
            "/api/v1/publishing/meta/oauth/callback?code=SECRETCODE&state=STATEVAL",
            "1.1",
            307,
        ),
        exc_info=None,
    )
    assert filt.filter(record) is True
    assert isinstance(record.args, tuple)
    assert len(record.args) == 5
    assert "SECRETCODE" not in record.args[2]
    assert "STATEVAL" not in record.args[2]
    assert "[REDACTED]" in record.args[2]
    # AccessFormatter must still unpack the 5-tuple successfully.
    formatted = AccessFormatter().format(record)
    assert "SECRETCODE" not in formatted
    assert "STATEVAL" not in formatted
    assert "307" in formatted


def test_scrub_audit_details_drops_secrets_and_oauth():
    dirty = {
        "platform": "facebook",
        "status": "healthy",
        "access_token": "EAAB_SHOULD_NOT_PERSIST",
        "refresh_token": "refresh_secret",
        "code": "oauth_code_value",
        "state": "oauth_state_value",
        "ADMIN_SECRET_KEY": "admin-secret",
        "app_secret": "meta-app-secret",
        "nested": {
            "page_access_token": "page-tok",
            "reason_code": "healthy",
            "provider_payload": {"access_token": "nested-tok", "ok": True},
        },
    }
    clean = scrub_audit_details(dirty)
    blob = str(clean)
    assert "EAAB_SHOULD_NOT_PERSIST" not in blob
    assert "refresh_secret" not in blob
    assert "oauth_code_value" not in blob
    assert "oauth_state_value" not in blob
    assert "admin-secret" not in blob
    assert "meta-app-secret" not in blob
    assert "page-tok" not in blob
    assert "nested-tok" not in blob
    assert clean["platform"] == "facebook"
    assert clean["status"] == "healthy"
    assert clean["nested"]["reason_code"] == "healthy"
