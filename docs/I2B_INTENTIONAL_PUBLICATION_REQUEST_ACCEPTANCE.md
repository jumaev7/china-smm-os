# I2b — Idempotent Intent-Only Publication Request Acceptance

**Status:** `DEVELOPMENT / DEFAULT-OFF` — authorized for source landing only.
Not authorized for production migration, image build, runtime enablement,
registry authority, or provider-write integration.

**Depends on:** I2a schema (`publish_intentional_publication_requests`),
I1 destination identity, existing tenant publishing auth.

## What I2b does

Accepts a **business intention** to publish once to exactly one destination:

`(tenant, content, platform, account|null, operation)`

On first authorized accept:

1. Validates tenant ownership of content (content → client → tenant) and account.
2. Validates `expected_publish_version` against `compute_publish_version`.
3. Applies I1 destination safety (aliases, historical NULL, unresolved).
4. Inserts one durable request row and mints one `publication_intent_id`.
5. Returns `request_id` + `publication_intent_id` with `status=accepted`.

A successfully accepted request is **not** a successfully published post.

## What I2b must never do

- Call provider adapters / `PublishService` publication execution
- `acquire_write_authority` / registry mutation / `supersede_intent`
- Create publish attempts or retry commands
- Enqueue workers / scheduler / shadow activation
- Backfill historical intents onto old successes

## Feature flag

`PUBLISH_INTENTIONAL_PUBLICATION_REQUESTS_ENABLED` (default `false`).

When false:

- `POST /api/v1/publishing/intentional-publication-requests` → **404**
- zero request rows / intents minted
- existing `POST /content/{id}/publish` semantics unchanged
- no new required headers for existing callers

## API

```
POST /api/v1/publishing/intentional-publication-requests
```

Auth: tenant user (scoped to `user.tenant_id`) or platform admin with
`?tenant_id=`.

### Body

| Field | Required | Notes |
|---|---|---|
| `content_id` | yes | Must belong to authenticated tenant via client |
| `platform` | yes | Exactly one normalized platform |
| `account_id` | no | Explicit NULL is a destination token; not auto-defaulted |
| `operation` | yes | `initial_publish` \| `intentional_republish` |
| `client_idempotency_key` | yes | Non-empty; scoped uniqueness (not global) |
| `expected_publish_version` | yes | Must match current content snapshot |

### Authorization

| Operation | Roles |
|---|---|
| `initial_publish` | `owner` \| `manager` \| `operator` (or admin) |
| `intentional_republish` | `owner` \| `manager` (or admin) |

Ordinary `POST /content/{id}/publish` authorization is unchanged.

### Responses

| Case | HTTP | Body highlights |
|---|---|---|
| New accept | **201** | `accepted=true`, `idempotent_replay=false`, `write_authorized=false` |
| Duplicate same fingerprint | **201** | same ids, `idempotent_replay=true` |
| Same key / different fingerprint | **409** | `request_fingerprint_conflict` — no new intent |
| Missing / empty key | **400** | `missing_client_idempotency_key` |
| Version mismatch | **409** | `publish_version_mismatch` |
| Unauthorized republish | **403** | `unauthorized_operation` |
| Forged tenant/content/account | **403** | `tenant_ownership_rejected` |
| Unresolved destination / ambiguous prior | **422** | stable failure codes; no sensitive disclosure |
| Feature disabled | **404** | unavailable |

`write_authorized` is always `false` in I2b.

If prior live success exists at the same destination, acceptance may still
succeed with `prior_live_success=true` and an explicit note that acceptance
does **not** authorize republishing. Unresolved / NULL-vs-concrete /
identity-conflict cases are **rejected** (fail closed).

## Request-key uniqueness

```
UNIQUE (tenant_id, content_id, platform, account_id, operation, client_idempotency_key)
NULLS NOT DISTINCT
```

Scope permits reuse of the same client key under a different destination or
operation. It is **not** a global unique key.

One intentional request per destination. Multi-platform publication requires
one accept call (and one intent) per destination.

## Fingerprint

SHA-256 hex via `build_request_fingerprint` (I2a helper):

- resolved destination (`tenant_id`, `content_id`, platform, `account_id`)
- `operation`
- `publish_version`
- `intent_mode` = `mint_new`

Fingerprint is immutable at accept. It does **not** store an immutable
content payload blob. Before I2c, immutable payload retrieval / snapshot
binding must be separately verified.

## Replay semantics

| Delivery | Result |
|---|---|
| Same key + same fingerprint | Return existing `request_id` / `publication_intent_id` |
| Same key + different fingerprint (incl. after content edit) | **409** — never mint second intent; never silently rebind to latest content |
| Same key after response loss / process restart | Reload committed row — same ids |
| Concurrent duplicate | Exactly one row via `INSERT … ON CONFLICT DO NOTHING` + reload |

Content is locked (`FOR UPDATE`) while validating version and inserting so a
concurrent edit cannot silently substitute the accepted snapshot between
validation and commit.

## Concurrency

Prefer atomic PostgreSQL `INSERT … ON CONFLICT DO NOTHING` on the request
identity index. On conflict: reload committed row, compare fingerprint,
return replay or 409. Never mint a replacement UUID. Nested savepoint used so
IntegrityError does not poison the outer transaction.

Destination `pg_advisory_xact_lock` serializes peers for the destination
during acceptance. The transaction is **not** held across provider I/O
(there is no provider I/O).

## Destination safety (I1)

Uses `compare_publication_destinations` / `find_destination_live_success`:

- Alias → `SAME_DESTINATION` (prior success noted; write still unauthorized)
- Historical NULL vs concrete account → `UNRESOLVED` → reject
- Unresolved / ambiguous prior write on same or unresolved destination → reject
- UUID inequality alone never proves distinct destinations

## Isolation proofs (I2b)

Acceptance path source must not reference:

- provider adapters
- `PublishService.publish_content` / execution
- `acquire_write_authority` / `mark_write_started` / registry success paths
- `supersede_intent`
- retry executor / scheduler activation

Registry row counts, attempt counts, and retry-command counts must remain
unchanged by acceptance.

## Production gates

| Gate | Verdict |
|---|---|
| I2b development / tests / push | GO when tests pass |
| Production source landing | NO-GO (separate auth) |
| Production migration | NO-GO |
| Image build / runtime deploy | NO-GO |
| Flag enable in production | NO-GO |
| Registry authority | NO-GO |
| Provider-write integration | NO-GO |
| Retry / shadow | NO-GO |
