# I2a — Durable Publication Request Schema

**Status:** `SCHEMA LANDED` — I2b may accept intents behind
`PUBLISH_INTENTIONAL_PUBLICATION_REQUESTS_ENABLED` (default false).
Not authorized for production migration, provider write, or registry authority.

**Revision:** `20260928_publish_intentional_publication_requests`  
**Down revision:** `20260927_publish_write_coordination_registry`

## Table

`publish_intentional_publication_requests`

Minimum persistence for future idempotent publication-intent materialization
(I2b+). I2a adds schema + ORM + default-off flag only.

## Request-key uniqueness scope

```
UNIQUE (tenant_id, content_id, platform, account_id, operation, client_idempotency_key)
NULLS NOT DISTINCT  -- account_id NULL equals account_id NULL
```

Applies to a **client request at the selected destination and operation**.

It does **not** establish distinctness of external provider destinations.
Two aliases of the same external destination require separate destination-
resolution protection in future I2b/I2c.

### Same client key reuse policy

| Scope difference | DB behavior |
|---|---|
| Same full scope key | Rejected (unique violation) |
| Different `operation` | Allowed (distinct request) |
| Different destination (`platform` / `account_id` / `content_id` / `tenant_id`) | Allowed (distinct request) |

Fingerprint mismatch under the same key is a **future service-layer** conflict
(409); the schema stores one immutable fingerprint per accepted row and does
not encode that comparison rule in SQL.

## Fingerprint storage contract

- Encoding: SHA-256 hex digest
- Length: 64 lowercase hex characters (`[0-9a-f]{64}`)
- Immutable after accept
- Future accept-path contributors (I2.0): resolved destination, operation,
  `publish_version` (content snapshot id), `intent_mode`
- Does **not** store an immutable content snapshot body

Helper (dormant, unused at runtime): `build_request_fingerprint` in
`app.models.publish_intentional_publication_request`.

## Intent identity

- Each request row has one immutable `publication_intent_id`
- `UNIQUE (publication_intent_id)`
- Different request rows must not share an intent unless a separately designed
  mapping mechanism explicitly permits it
- I2a does **not** mint intents

## Tenant / FK integrity

Ordinary FKs (same pattern as R1 registry):

- `tenant_id → tenants.id` RESTRICT
- `content_id → content_items.id` RESTRICT
- `account_id → publishing_accounts.id` RESTRICT (nullable)

PostgreSQL does **not** enforce that `content_id` or `account_id` belong to
`tenant_id`. `content_items` has no `tenant_id` column; composite tenant
consistency would require broader parent-schema changes (out of I2a scope).
Cross-tenant consistency remains **service-layer** responsibility.

## Domains

- `operation ∈ {initial_publish, intentional_republish}`
- `status ∈ {accepted}` only (no speculative runtime transitions)

## Feature flag

`PUBLISH_INTENTIONAL_PUBLICATION_REQUESTS_ENABLED` default `False`.

Production Compose pin:
`${PUBLISH_INTENTIONAL_PUBLICATION_REQUESTS_ENABLED:-false}`

Unused for activation in I2a.

## Explicit non-goals (I2a)

No PublishService changes, API routes, intent minting, provider adapters,
retry/registry/shadow activation, workers, or production migration execution.
