# Integration Health Automation

Read-only integration diagnostics for Meta, Telegram, advertising, and listening
domains. The background scheduler evaluates health on a conservative cadence
without mutating provider configuration, credentials, or business state.

## Safety boundary

The scheduler and API health paths are **read-only toward providers**:

| Domain | Scheduler remote API | Notes |
|---|---|---|
| Meta (Facebook/Instagram) | `GET /debug_token` only on remote cycles | No publish, OAuth, or reconnect |
| Telegram | Local evaluation only | No webhook mutation |
| Advertising | Local evaluation | No provider writes |
| Listening | Local/capability evaluation | No provider writes |

Kill switches (production compose):

| Variable | Default | Purpose |
|---|---|---|
| `INTEGRATION_HEALTH_CHECK_ENABLED` | `false` | Master scheduler gate |
| `INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED` | `false` | Allow Meta remote probes |

## Cadence

- **Local cycle:** ~30 minutes (`INTERVAL_SECONDS = 1800`)
- **Remote Meta probes:** every 4th cycle (~120 minutes) when remote enabled
- Overlap guard: concurrent cycles are skipped (no duplicate work, no audit)

**Topology:** one production `backend` uvicorn process owns the in-process
scheduler. Do not scale backend replicas without a durable lease/advisory lock.

## Persisted diagnostics

Per-integration snapshots live in
`PublishingAccount.account_metadata_json` under key `integration_health`.
These provide per-account forensic detail between audit cycles.

## Scheduler audit observability

Automatic scheduler cycles emit durable batch audit events so operators can
reconstruct background health activity without relying on ephemeral logs.

### Event type

`integration_health.batch_check`

### Scope

Scheduler batch audits use **`tenant_id = null`** (platform/system scope).
They cover all tenants processed in one cycle. API-triggered batch checks
remain tenant-scoped (`tenant_id` = requested tenant).

Do not attach a global scheduler batch to an arbitrary tenant.

### Source distinction (`details.trigger`)

| Trigger | Origin | `tenant_id` |
|---|---|---|
| `scheduler` | Background `IntegrationHealthScheduler.run_once()` | `null` |
| `api_live_check` | `GET /integrations/health?live_check=true` or single integration live check | tenant UUID |

Single-integration API live checks use `integration_health.check` with
`details.trigger = api_live_check`. The `details.source` field on check events
remains the evaluation probe origin (`local` / `remote`), not the audit trigger.

### Scheduler batch fields

Safe fields written to `platform_audit_logs.details`:

| Field | Description |
|---|---|
| `trigger` | Always `scheduler` |
| `cycle` | Monotonic in-process cycle counter |
| `remote_check` | Whether this cycle performed remote Meta probes |
| `remote_enabled` | `INTEGRATION_HEALTH_REMOTE_CHECK_ENABLED` at cycle time |
| `started_at` | ISO-8601 UTC cycle start |
| `completed_at` | ISO-8601 UTC cycle end |
| `duration_ms` | Wall-clock duration |
| `tenant_count` | Tenants processed |
| `checked_count` | Publishing accounts evaluated |
| `error_count` | Evaluation errors |
| `meta_accounts` | Meta platform accounts seen |
| `remote_meta_probes` | Meta accounts where `live_check=true` was used |
| `status_summary` | Aggregate status counts (`healthy`, `degraded`, etc.) |
| `outcome` | `success` / `partial` / `failed` |

### Per-integration audit decision

**Batch-only for scheduler cycles.** At current scale (~48 local + ~12 remote
cycles/day) one batch event per cycle is ~60 audit rows/day. Per-integration
scheduler audits would add ~1,440+/day now and scale linearly with clients.
Persisted per-account diagnostics already capture account-level state; batch
audit plus diagnostics is sufficient for incident reconstruction.

### Failure isolation

Audit logging is **not** on the provider safety-critical path:

- Audit failure is logged (`warning`) and swallowed
- Health cycle results and diagnostic commits are unaffected
- No provider retry is triggered by audit failure
- Scheduler continues on the next interval

### Transaction semantics

1. `run_periodic_cycle`: commits diagnostic updates **per tenant**
2. `audit_scheduler_cycle`: separate DB session, **independent commit**
3. Audit failure cannot roll back successful diagnostic updates
4. One tenant's failure rolls back only that tenant's uncommitted work

### Delivery semantics

**At-least-once / best-effort.** Each completed cycle produces one audit row.
Manual `run_once()` invocations, process restarts, or repeated cycles each
create distinct audit records. Overlap-skipped cycles produce **no** audit.
Exact-once semantics are not attempted (single-backend topology; low volume).

### Secret scrubbing

All audit details pass through `scrub_audit_details()` before insert.
Tokens, OAuth codes/state, secrets, and ciphertext keys are dropped.

### Operator read path

Admin audit API (existing):

```
GET /api/v1/platform-ops/audit-logs?event_type=integration_health.batch_check
```

Filter scheduler cycles:

- `details.trigger = scheduler`
- `tenant_id` is null for scheduler batches
- `details.remote_check = true` for remote cycles

Tenant users see tenant-scoped API live-check audits via:

```
GET /api/v1/platform-ops/audit-logs/my
```

Scheduler-global batches are admin-visible only (null tenant scope).

### Metrics compatibility

Scheduler audit events do **not** affect Operator Workspace action metrics
(`operator_workspace.action`). Metrics query only that event type.

## API endpoints

Tenant-scoped (owner/manager/operator):

- `GET /api/v1/integrations/health` — list (`live_check` optional)
- `GET /api/v1/integrations/{id}/health` — single integration

`live_check=true` triggers provider probes (Meta) and writes API audit events.
`live_check=false` uses local evaluation with persisted diagnostics only.

## Production rollout (code-only)

When approved after review:

1. Deploy backend code (no DB migration — uses existing `platform_audit_logs`)
2. No OAuth / Meta configuration changes
3. No CHECK/REMOTE flag changes required for audit itself
4. Recreate **backend** service only if image rebuild is standard deploy practice
5. Verify: `GET /platform-ops/audit-logs?event_type=integration_health.batch_check`
   shows `trigger=scheduler` rows after ~30 minutes with CHECK enabled

## Next automation boundary

`acknowledge_alert` autonomous remediation is **not** part of this stage.
After scheduler audit is deployed and production-verified, guarded
`acknowledge_alert` automation may proceed under its own safety design
(recommendation/shadow-mode first).

Priority order: **Stability → Security/Safety → Observability → Maximum Safe Automation**
