# Operator Workspace — Phase 1

## Purpose

Operator Workspace is the daily operational view for SMM operators managing multiple client companies. It answers one question:

**What requires my attention today?**

It is a **read-only aggregation layer** — not a new task system, approval workflow, or publishing engine.

## Source-of-truth boundaries

| Domain | Canonical system | Workspace role |
|--------|------------------|----------------|
| Content editing & status | Content (`/content`, ContentItem) | Surfaces items needing internal review or client review |
| Publishing operations | Publishing Queue & Attempts (`/publishing/queue`, PublishAttempt) | Surfaces failed, stuck, operator-review, and overdue scheduled items |
| Integrations | Integrations Center (`/integrations`, PublishingAccount) | Surfaces disconnected/expired/missing-permission accounts |
| Automation | Automation Center (`/automation`, TenantAutomationJob) | Surfaces recent failed/dead-letter jobs |
| Telegram ingestion | Telegram webhook queue (platform admin) | Surfaces recent terminal failed webhook events to admins only |
| Publishing alerts | Publishing Alerts (`/publishing/alerts`) | Surfaces open/acknowledged operator alerts |

Operator Workspace **does not** mutate canonical state. Each item deep-links to the existing screen where the issue is resolved.

## Attention categories (Phase 1)

1. **content_internal_review** — draft/ready/needs_review content awaiting operator review
2. **waiting_for_client** — client approval pending or changes requested (lower urgency; responsible party = client); aggregated **one row per client** via SQL `GROUP BY`
3. **publishing_issue** — failed publish, operator review, stale in-progress, due retries, stuck publishing, open publish alerts
4. **scheduling_issue** — scheduled time passed but content not published (canonical overdue semantics)
5. **integration_issue** — publishing accounts in attention statuses (disconnected, expired, etc.)
6. **telegram_ingestion_issue** — recent terminal failed Telegram webhook events (**admin only**; events are platform-global)
7. **automation_failure** — failed/dead-letter automation jobs within the **7-day actionable window**

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

This is a derived recency/actionability rule for the daily workspace. Historical dead letters (e.g. known July jobs older than the window) remain in the automation system unchanged and simply age out of “today”.

## API

- `GET /api/v1/operator-workspace/summary` — optional `client_id`
- `GET /api/v1/operator-workspace/items` — `client_id`, `category`, `priority`, `responsible_party`, pagination

Category/priority/responsibility filters change the **items list** only. Summary cards stay based on the full client-scoped attention set.

## Authorization

Tenant roles: **owner**, **manager**, **operator**.

Denied: **sales**, **viewer**.

Platform admins may access via existing admin session. Frontend nav/route guards use the same role list.

## Tenant isolation

Uses existing `ApiAuthContext` + `scope_select()` for client-scoped content/publishing queries and `apply_tenant_direct_scope()` for tenant-level integration/automation resources. Cross-tenant access returns 403 via existing guards.

## Phase 2+ (not in scope)

- CRM / project management features
- AI prioritization
- Persistent task table
- In-app resolution forms (retry publish, edit content) inside workspace
- Listening/Advertising intelligence feeds (unless operational failure)
- Per-job automation deep pages beyond existing center drawer
- Tenant-scoped Telegram webhook event projection (requires schema work)
