# Social Listening Phase 3 — Governed Live Read-Only Sources

Read-only Facebook Page observation via Meta Graph. Tokens stay on
`publishing_accounts`. Listening sources bind by `integration_id` only.

## Shipped capabilities (independent)

Owned Page comments and tagged mentions are **separate** capabilities and are
never collapsed into one flag.

### 1. `owned_content_comments` → `facebook_page_comments`

| Item | Value |
| --- | --- |
| Endpoint | `GET /{page-post-id}/comments` (posts via `GET /{page-id}/posts`) |
| Graph version | App setting `META_GRAPH_API_VERSION` (default `v21.0`); docs publish `v25.0` |
| Token | Page access token from authorized `publishing_accounts` |
| Permissions | `pages_show_list`, `pages_read_engagement`, `pages_read_user_content` |
| Page tasks | `MODERATE` |
| App review | **Required** — Advanced Access for production beyond Development-mode app roles |
| Pagination | Cursor (`paging.cursors.after`) |
| Webhooks | Not used (polling only) |
| Historical | Recent Page posts window; feed docs note ~600 ranked posts/year |
| Replies | Not supported (`filter=toplevel`) |
| Deletion | No trustworthy polling deletion signal — mentions are never deleted because an item is missing from a later page |

Official docs:

- https://developers.facebook.com/docs/graph-api/reference/page-post/comments/
- https://developers.facebook.com/docs/graph-api/reference/page/feed/
- https://developers.facebook.com/docs/permissions/
- https://developers.facebook.com/docs/pages-api/comments-mentions/

**Production:** Meta App Review + Advanced Access required for
`pages_read_engagement` and `pages_read_user_content`.

### 2. `direct_account_mentions` / tagged mentions → `facebook_page_mentions`

Independently documented as `GET /{page-id}/tagged` (Page Feed / Pages API Mentions).
`pages_read_user_content` allowed usage explicitly includes “Get posts that your
Page is tagged in.” Permission **name alone is not operational proof** — live
probe hits `/tagged?limit=1`.

| Item | Value |
| --- | --- |
| Endpoint | `GET /{page-id}/tagged` |
| Token | Page access token |
| Permissions | `pages_show_list`, `pages_read_user_content` |
| Page tasks | `MODERATE` (feed reading requirements) |
| App review | **Required** — Advanced Access for production beyond app roles |
| Pagination | Cursor |
| Webhooks | Not used |
| Limitations | Other Pages only when authentic; not Instagram @mentions; not keyword search |

Official docs:

- https://developers.facebook.com/docs/graph-api/reference/page/feed/
- https://developers.facebook.com/docs/permissions/
- https://developers.facebook.com/documentation/pages-api
- https://developers.facebook.com/docs/graph-api/reference/page/

**Production:** Meta App Review + Advanced Access required for
`pages_read_user_content`.

## OAuth scope alignment

Default backend `META_OAUTH_SCOPES` (and `.env.production.example`) request the
minimum permissions for implemented publish + Listening features, including
`pages_read_engagement` and `pages_read_user_content`.

**Reconnection required for existing integrations:** tokens issued before these
scopes were added will not gain Listening permissions until the tenant
re-runs Meta OAuth connect. Capability health correctly reports `missing_scope`
until reconnection. Do not broaden scopes beyond implemented features.

## Access layers (do not conflate)

1. **Permission granted to a token** — OAuth scopes present on the Page token
2. **Advanced Access / App Review** — Meta app access level for Live mode
3. **Page/task authorization** — user can perform required Page tasks; Page bound to tenant
4. **Development-mode availability** — app roles / testers only
5. **Production availability** — Live mode + Advanced Access after review

A configured permission must not automatically mean the source is operational.
Health probes perform a harmless capability-specific Graph read.

## Sanitized health states

Exposed codes (never Meta payloads or tokens):

- `missing_scope`
- `insufficient_app_access`
- `page_not_authorized`
- `token_expired_or_revoked`
- `rate_limited`
- `provider_unavailable`
- `unsupported_capability`

## Credentials & locking

- Page tokens are resolved from the existing Meta publishing integration only
- Tokens are never copied into `ListeningSource.config_json`, ingestion runs,
  checkpoints, or mention provenance
- `missing_credentials` (no/undecryptable token) is distinct from
  `token_expired_or_revoked` (revoked/expired/invalid account status)
- Cross-tenant publishing account IDs resolve as configuration errors (tenant
  filter on `publishing_accounts`); Page id must match `provider_resource_ref`

### Atomic source lock lifecycle

Source ingestion uses a **database row lease** (`lock_owner` /
`lock_expires_at`) via atomic `UPDATE … RETURNING`. The lease is **committed
before** provider work so other sessions observe it after the acquire
transaction ends — `RETURNING` alone is not sufficient.

| Step | Behavior |
| --- | --- |
| Acquisition | Conditional `UPDATE` succeeds only when lock is free, expired/stale, or already owned by the same owner |
| Owner / run identity | `lock_owner` (e.g. `manual:<user_id>`, `<worker>:<source_id>`, `sync:<hex>`) |
| Lease expiry | `lock_expires_at = now + LOCK_LEASE_SECONDS` (default 180s) |
| Worker crash after commit | Lease remains until expiry; another worker may reclaim when expired |
| Stale-lock recovery | `WHERE` treats `lock_expires_at < now` (or null) as free |
| Release | Clears lock only when `lock_owner` matches the releasing run |
| Concurrent manual + scheduled | Exactly one wins the committed lease; loser gets `already_running` |
| Transaction boundaries | Acquire commits immediately; work runs afterward; release commits in `finally` |

## Schema

- Production evolution: Alembic (`20260916_listening_live_sources` retains ALTER)
- Local helper: `ensure_listening_schema()` is **create-only** (no ALTER drift)
- Fresh ensure CREATE includes live columns + `VARCHAR(1000)` cursors for parity

## Capability probes

Probes run only during explicit `health_check` / configuration validation paths —
never on ordinary mention/analytics/review/Executive Copilot reads, and never
once per mention. They use bounded timeouts (≤15s), classify rate limits, sanitize
Graph errors, persist only capability status/freshness (never response payloads),
and are read-only (GET only).

**Limitation:** a successful `limit=1` probe confirms **endpoint access** for the
authorized Page — not general market coverage.

## Ordinary read paths

Mention list/detail, analytics/intelligence, review, and Executive Copilot must
make **zero** Graph API calls. Provider I/O is confined to scheduled/manual sync.

## Contract fixtures

See `backend/app/services/listening/providers/fixtures/meta/` and
`backend/scripts/test_listening_live_sources.py`.
