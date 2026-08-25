"""Sanitize sensitive query parameters in HTTP access / request logs.

Uvicorn's AccessFormatter logs the request line with the full query string.
OAuth callbacks include one-time ``code`` / ``state`` values that must not
persist in operational logs.
"""
from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

# Parameter names whose values are replaced with [REDACTED].
SENSITIVE_QUERY_PARAMS = frozenset({
    "code",
    "state",
    "access_token",
    "refresh_token",
    "id_token",
    "token",
    "oauth_token",
    "oauth_verifier",
    "client_secret",
    "client_secret_expires_at",
    "password",
    "secret",
    "authorization",
    "auth",
    "api_key",
    "apikey",
    "session",
    "session_id",
})

# Paths where the entire query string is collapsed (defense in depth).
_SENSITIVE_PATH_MARKERS = (
    "/oauth/callback",
    "/oauth/authorize",
    "/auth/callback",
    "/login/callback",
)

_SENSITIVE_QUERY_RE = re.compile(
    r"(?i)([?&])("
    + "|".join(re.escape(p) for p in sorted(SENSITIVE_QUERY_PARAMS, key=len, reverse=True))
    + r")=([^&]*)"
)


def sanitize_request_path(path_with_query: str) -> str:
    """Return a log-safe request path; redact sensitive query values."""
    if not path_with_query:
        return path_with_query

    raw = str(path_with_query)
    # Strip scheme/host if a full URL somehow appears in the access log.
    if "://" in raw:
        parts = urlsplit(raw)
        path = parts.path or "/"
        query = parts.query
        fragment = parts.fragment
    else:
        if "?" in raw:
            path, query = raw.split("?", 1)
            fragment = ""
            if "#" in query:
                query, fragment = query.split("#", 1)
        else:
            path, query, fragment = raw, "", ""

    path_l = path.lower()
    if any(marker in path_l for marker in _SENSITIVE_PATH_MARKERS):
        if query:
            return f"{path}?[REDACTED]" + (f"#{fragment}" if fragment else "")
        return path + (f"#{fragment}" if fragment else "")

    if not query:
        return path + (f"#{fragment}" if fragment else "")

    pairs = parse_qsl(query, keep_blank_values=True)
    redacted: list[tuple[str, str]] = []
    changed = False
    for key, value in pairs:
        if key.lower() in SENSITIVE_QUERY_PARAMS:
            redacted.append((key, "[REDACTED]"))
            changed = True
        else:
            redacted.append((key, value))

    if not changed:
        # Fallback regex for odd encodings / duplicate structures.
        scrubbed = _SENSITIVE_QUERY_RE.sub(r"\1\2=[REDACTED]", f"?{query}")
        if scrubbed.startswith("?"):
            scrubbed = scrubbed[1:]
        new_query = scrubbed
    else:
        parts: list[str] = []
        for key, value in redacted:
            enc_key = quote(str(key), safe="")
            if value == "[REDACTED]":
                parts.append(f"{enc_key}=[REDACTED]")
            else:
                parts.append(f"{enc_key}={quote(str(value), safe='')}")
        new_query = "&".join(parts)

    if "://" in raw:
        parts = urlsplit(raw)
        return urlunsplit((parts.scheme, parts.netloc, path, new_query, fragment))
    return path + (f"?{new_query}" if new_query else "") + (f"#{fragment}" if fragment else "")


class SensitiveAccessLogFilter(logging.Filter):
    """Mutate uvicorn.access args in-place without breaking AccessFormatter.

    Uvicorn packs ``record.args`` as a 5-tuple:
    ``(client_addr, method, full_path, http_version, status_code)``.
    Filters must preserve length and types.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3:
            path = args[2]
            if isinstance(path, str) and ("?" in path or any(m in path.lower() for m in _SENSITIVE_PATH_MARKERS)):
                cleaned = list(args)
                cleaned[2] = sanitize_request_path(path)
                record.args = tuple(cleaned)
        elif isinstance(record.msg, str) and ("?" in record.msg or "code=" in record.msg.lower()):
            record.msg = sanitize_request_path(record.msg) if record.msg.startswith("/") else _scrub_message(record.msg)
        return True


def _scrub_message(message: str) -> str:
    """Best-effort scrub of free-form log messages containing query strings."""
    def _replace_path(match: re.Match[str]) -> str:
        return sanitize_request_path(match.group(0))

    return re.sub(r"/[^\s\"']+\?[^\s\"']+", _replace_path, message)


def install_access_log_redaction() -> None:
    """Attach the filter to uvicorn access/error loggers (idempotent)."""
    filt = SensitiveAccessLogFilter()
    for name in ("uvicorn.access", "uvicorn.error", "uvicorn"):
        log = logging.getLogger(name)
        if not any(isinstance(f, SensitiveAccessLogFilter) for f in log.filters):
            log.addFilter(filt)
    # Also cover root handlers that may receive propagated access records.
    root = logging.getLogger()
    if not any(isinstance(f, SensitiveAccessLogFilter) for f in root.filters):
        root.addFilter(filt)


def scrub_audit_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Deny-by-name scrub for PlatformAuditLog.details (nested)."""
    from app.services.automation_domain_events import scrub_payload

    clean = scrub_payload(details)
    # Extra OAuth / platform-secret keys not covered by generic token scrubbing.
    extra_banned = (
        "code",
        "state",
        "oauth_code",
        "oauth_state",
        "authorization_code",
        "admin_secret_key",
        "app_secret",
        "meta_app_secret",
        "client_secret",
        "encrypted_token",
        "ciphertext",
    )

    def _walk(obj: Any) -> Any:
        if isinstance(obj, dict):
            out: dict[str, Any] = {}
            for key, value in obj.items():
                lowered = str(key).lower()
                if lowered in extra_banned or any(
                    part in lowered for part in ("secret", "password", "token", "authorization")
                ):
                    continue
                out[key] = _walk(value)
            return out
        if isinstance(obj, list):
            return [_walk(item) for item in obj]
        return obj

    return _walk(clean)
