# Operator Workspace

## Purpose

Operator Workspace is the daily operational view for SMM operators managing multiple client companies. It answers one question:

**What requires my attention today?**

It is an **aggregation / projection layer** — not a new task system, approval workflow, or publishing engine.

Phase 1 (attention) surfaces what needs work.
**Actions Phase 1** adds one-click closure for a small set of **safe, existing canonical mutations**.

## Source-of-truth boundaries

| Domain | Canonical system | Workspace role |
|--------|------------------|----------------|
| Content editing & status | Content (`/content`, ContentItem) | Surfaces items needing internal review or client review; may invoke `ContentService.approve` |
| Publishing operations | Publishing Queue & Attempts (`/publishing/queue`, PublishAttempt) | Surfaces failed, stuck, operator-review, and overdue scheduled items; may invoke `PublishAttemptOpsService.manual_retry` when Workspace-eligible |
| Integrations | Integrations Center (`/integrations`, PublishingAccount) | Surfaces disconnected/expired/missing-permission accounts (navigation only) |
| Automation | Automation Center (`/automation`, TenantAutomationJob) | Surfaces recent failed/dead-letter jobs (navigation only — no dead-letter replay) |
| Telegram ingestion | Telegram webhook queue (platform admin) | Surfaces recent terminal failed webhook events to admins only (navigation only) |
| Publishing alerts | Publishing Alerts (`/publishing/alerts`) | Surfaces open/acknowledged operator alerts; may invoke acknowledge / resolve |

Operator Workspace **does not** invent domain logic. Mutations always revalidate canonical state and delegate to the owning service.

Mobile clients reuse these same projections and actions via `/api/v1/mobile-control/*` and `X-Client-Source: mobile` — see [MOBILE_OPERATOR_CONTROL.md](./MOBILE_OPERATOR_CONTROL.md).

## Attention categories

1. **content_internal_review** — draft/ready/needs_review content awaiting operator review
2. **waiting_for_client** — client approval pending or changes requested (lower urgency; responsible party = client); aggregated **one row per client** via SQL `GROUP BY`
3. **publishing_issue** — failed publish, operator review, stale in-progress, due retries, stuck publishing, open publish alerts
4. **scheduling_issue** — scheduled time passed but content not published (canonical overdue semantics)
5. **integration_issue** — publishing accounts in attention statuses (disconnected, expired, etc.)
6. **telegram_ingestion_issue** — recent terminal failed Telegram webhook events (**admin only**; events are platform-global)
7. **automation_failure** — failed/dead-letter automation jobs within the **7-day actionable window**

## Actions Phase 1 (safe mutation set)

Derived on each items response (`actions[]`). Not persisted.

| Action ID | Attention | Delegates to | Confirmation | Notes |
|-----------|-----------|--------------|--------------|-------|
| `acknowledge_alert` | `publish-alert:*` (open) | `PublishOperatorAlertService.acknowledge` | No | Idempotent if already acknowledged |
| `resolve_alert` | `publish-alert:*` (open/ack) | `PublishOperatorAlertService.resolve_manual` | Yes | Removes from actionable set |
| `retry_publish` | `publish-attempt:*` when canonical `evaluate_manual_retry_eligibility` allows (Workspace/web) | `PublishAttemptOpsService.manual_retry` after live revalidation | Yes | **Phase 3C.1A: allowlist is EMPTY** — no enabled Retry for Telegram/Meta/null/unknown/ambiguous codes, exhausted budget, mock platforms, or mobile source. Navigation / disabled affordances only. |
| `approve_content` | `content-review:*` | `ContentService.approve` | Yes | Does not bypass client approval; may start client review / Telegram preview via existing path |
| `open` | all | — | — | Navigation only; mutation endpoint rejects it |

### Explicitly excluded (navigation / deep-link only)

- Meta `operator_review` republish (ambiguous outcomes — fail-closed)
- Telegram `rate_limited` / `provider_transient` one-click retry (3C.1A: Bot API 429 is not structured into `failure_code`; `provider_transient` is Meta-text only — both fail closed)
- OAuth reconnect / credential mutation
- Automation dead-letter replay
- Client approval on behalf of client
- Live social send, Telegram send, email send
- Destructive deletes / billing

### Endpoint

`POST /api/v1/operator-workspace/items/{attention_id}/actions/{action_id}`

Flow:

1. Resolve attention id prefix + resource
2. Re-read canonical resource (tenant / client scoped)
3. Re-check eligibility (409 if stale)
4. Enforce workspace RBAC (`owner|manager|operator`)
5. Delegate to canonical service
6. Return action result + refresh recommendation

Do not trust stale frontend action metadata.

## Query correctness (no silent truncation)

Source queries filter to **actionable statuses only** and do **not** apply a hard `LIMIT 500` that could hide work.

- Content / publish / schedule / alerts / integrations: full actionable result sets (status-filtered)
- Waiting-for-client: SQL aggregation by `client_id` (one attention item per client regardless of pending volume)
- Automation / Telegram: bounded by **7-day recency** (derived actionability; historical rows are not mutated)
- Pathological volumes (≥5000 rows from one source) emit a warning log; they are not silently dropped

Summary counts and pagination totals are computed from the full collected attention set (client-scoped), so truncation cannot make totals wrong.

## Priority model

Deterministic, explainable rules (no ML):

- **Critical** — operator review, stale/stuck publishing, overdue scheduled publish
- **High** — failed/exhausted publish, integration blocked, dead-letter automation
- **Medium** — internal review, telegram failures, due retrying publish
- **Low** — waiting for client

## Responsibility model

| Situation | Responsible party |
|-----------|-------------------|
| Failed / exhausted / operator_review publish | operator |
| Provider auth/permission / rate-limit failure codes | provider |
| Retrying publish (due) | system |
| Stale in-progress publish | system (shown as stuck; needs monitoring) |
| Client approval / changes requested | client |
| Disconnected integration | operator |
| Expired / missing_permissions / invalid integration | provider |

Healthy in-flight `in_progress` attempts (lease still valid) are **excluded** so they do not pollute “Needs action now”.

## Dead-letter noise rule

Automation failed/dead_letter jobs appear only when `updated_at` is within **7 days**.

This is a derived recency/actionability rule for the daily workspace. Historical dead letters remain in the automation system unchanged and simply age out of “today”. Workspace never replays them.

## API

- `GET /api/v1/operator-workspace/summary` — optional `client_id`
- `GET /api/v1/operator-workspace/items` — `client_id`, `category`, `priority`, `responsible_party`, pagination (includes derived `actions[]`)
- `GET /api/v1/operator-workspace/metrics` — `window` (`24h`|`7d`|`30d`), optional `client_id` / `category` (read-only observability)
- `POST /api/v1/operator-workspace/items/{attention_id}/actions/{action_id}` — Phase 1 safe mutations

Category/priority/responsibility filters change the **items list** only. Summary cards stay based on the full client-scoped attention set.

## Authorization

Tenant roles: **owner**, **manager**, **operator**.

Denied: **sales**, **viewer**.

Platform admins may access via existing admin session. Frontend nav/route guards use the same role list.

Actions do **not** expand RBAC beyond the workspace gate + existing domain tenant/client scope.

## Tenant isolation

Uses existing `ApiAuthContext` + `scope_select()` for client-scoped content/publishing queries and `apply_tenant_direct_scope()` for tenant-level integration/automation resources. Action execution re-resolves the canonical resource server-side; attention ids alone cannot mutate cross-tenant data.

## Audit & metrics

Actor attribution for alert ack/resolve uses existing `acknowledged_by` / `resolved_by` fields.

**Observability Phase (this layer):**

- `GET /api/v1/operator-workspace/metrics` — read-only attention / action / resolution pulse
- Workspace mutation actions write durable provenance to existing `platform_audit_logs`
  (`event_type=operator_workspace.action`). Navigation `open` is never recorded.
- Attention volume/age is a **point-in-time** projection over canonical collectors (no new attention table).
- Alert TTR uses `PublishOperatorAlert.first_occurred_at` → `resolved_at` / `acknowledged_at`.
- Automation candidate levels (A/B/C/D) and scores are **advisory only** — auto-execution remains disabled.

No new analytics subsystem or migration was introduced for this phase.

## Durable publish retry commands (Phase 3C.1B / 3C.1C-A / 3C.1C-B / 3C.1C-C / 3C.1C-D1 / 3C.1C-D2-A)

Infrastructure foundation (`publish_retry_commands` + create/get service + claim worker + preparation + DB write barrier + unwired fake executor).

- Feature flags (all default **false**):
  - `PUBLISH_RETRY_COMMANDS_ENABLED` — global create/get + claim subsystem gate
  - `PUBLISH_RETRY_COMMAND_WORKER_ENABLED` — worker process/poll loop
  - `PUBLISH_RETRY_COMMAND_CLAIM_ENABLED` — permission to mutate pending→claimed / stale reclaim
  - `PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED` — preparation + barrier + fake-executor gate (keep false; not wired to worker)
- Precedence for claim/reclaim: commands **and** worker **and** claim must all be true
- Precedence for pre-I/O preparation (3C.1C-C), DB write barrier (3C.1C-D1), and unwired fake executor (3C.1C-D2-A): claim gates **and** execution must be true; **not** invoked by claim worker
- Creating a command records operator retry intent only — **does not publish**
- Claim worker (`publish-retry-command-worker`) owns pending→claimed / stale claimed reclaim only
- Canonical `evaluate_manual_retry_eligibility` still gates creation (allowlist remains empty)
- Workspace / mobile / admin synchronous retry paths are **unchanged**
- Read-only status: `GET /api/v1/publishing/retry-commands/{command_id}`
- **DB lineage invariants (3C.1C-A):** unique non-null `publish_attempts.retry_command_id`, unique non-null `publish_retry_commands.resulting_attempt_id`, worker lookup index `(status, created_at)`, CHECK that `provider_write_started` requires `provider_write_started_at`
- **Claim/lease foundation (3C.1C-B):** `FOR UPDATE SKIP LOCKED`, DB `now()` leases, reclaim only when `status=claimed` and `provider_write_started_at IS NULL`. Never crosses the provider-write barrier.
- **Pre-I/O preparation (3C.1C-C):** claimed command → eligibility + newer-success revalidation → create/reuse one linked `PublishAttempt` (`status=operator_review`, provider write not started) → bidirectional lineage → commit. No `PublishService.publish_content`, no adapters, no `provider_write_started`.
- **DB-only write barrier (3C.1C-D1):** claimed + prepared → `provider_write_started` with durable `provider_write_started_at` (DB `now()`); linked attempt stays `operator_review` with `failure_code=retry_command_write_started`. Lease expiry cleared; lease owner preserved for forensics. No provider I/O, no fake provider, not wired to worker. Explicit/test entrypoint only.
- **Unwired fake executor (3C.1C-D2-A):** `PublishRetryCommandExecutor` coordinates prepare → barrier → exactly one injected fake provider call → command-specific finalization. No real Telegram/Meta adapters. Not wired to worker/API/Workspace/mobile. Post-barrier outcomes are only success / definitive failure / ambiguous (never auto-retry). Duplicate or concurrent executor calls never re-invoke the provider after barrier.

## Future (not in scope)

- Autonomous remediation (no auto-execute of eligible actions)
- CRM / project management features
- AI prioritization
- Persistent task / action table
- Automation requeue from workspace
- OAuth reconnect from workspace
- Listening/Advertising intelligence feeds (unless operational failure)
- Phase E reconciliation for stale `provider_write_started` / post-provider finalize gaps
- Real provider adapters after barrier (3C.1C-D2-B / F+) — requires F0 selector hard-exclusion of `retry_command_id IS NOT NULL` before any real I/O
