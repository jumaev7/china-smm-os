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
| `retry_publish` | `publish-attempt:*` failed / exhausted / due retrying | `PublishAttemptOpsService.manual_retry` | Yes | **Not** exposed for `operator_review` |
| `approve_content` | `content-review:*` | `ContentService.approve` | Yes | Does not bypass client approval; may start client review / Telegram preview via existing path |
| `open` | all | — | — | Navigation only; mutation endpoint rejects it |

### Explicitly excluded (navigation / deep-link only)

- Meta `operator_review` republish (ambiguous outcomes — fail-closed)
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

Actor attribution for alert ack/resolve uses existing `acknowledged_by` / `resolved_by` fields. Content approve and publish retry continue to use their canonical side effects / logs. No new analytics subsystem in Actions Phase 1 — future efficiency metrics (time-to-resolution, actions/day) can read existing audit fields.

## Future (not in scope)

- Autonomous remediation (no auto-execute of eligible actions)
- CRM / project management features
- AI prioritization
- Persistent task / action table
- Automation requeue from workspace
- OAuth reconnect from workspace
- Listening/Advertising intelligence feeds (unless operational failure)
