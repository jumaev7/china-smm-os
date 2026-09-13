# Phase E2-1 — MARK_AMBIGUOUS manual resolution

**Status:** local / dormant implementation. Production enablement is **not**
authorized by this slice.

**Scope:** operator-confirmed bookkeeping terminalization for stranded
post-barrier retry commands. First E2 mutation slice only.

## Allowed action

`MARK_AMBIGUOUS` only.

No:

- `ACKNOWLEDGE_EXTERNAL_SUCCESS`
- `MARK_FAILED_CONFIRMED`
- `MARK_NO_EFFECT_CONFIRMED`
- `CANCEL`
- `SUPERSEDE`
- replacement command creation
- provider I/O / reconciliation reads
- ContentItem / `tenant_external_publications` mutation
- mobile mutations

## Entry gate

```text
status == 'provider_write_started'
AND provider_write_started_at IS NOT NULL
AND resulting_attempt_id IS NOT NULL
AND bidirectional lineage valid
```

Pending / claimed → `409 not_resolvable`.  
Other terminals → `409 already_resolved`.  
Lineage failures → `409 lineage_conflict` (fail closed, no silent repair).

## Transitions

| Entity | Field | Result |
|--------|-------|--------|
| `PublishRetryCommand` | `status` | `ambiguous` |
| `PublishRetryCommand` | `provider_outcome` | `ambiguous` |
| `PublishRetryCommand` | `finished_at` | now |
| resulting `PublishAttempt` | `status` | `operator_review` |
| resulting `PublishAttempt` | `retryable` | `false` |
| resulting `PublishAttempt` | `next_retry_at` | `null` |
| resulting `PublishAttempt` | `finished_at` | now |

Command remains non-executable forever. Original attempt is not mutated.

## API

`POST /api/v1/publishing/retry-commands/{command_id}/resolve`

Request (E2-1):

```json
{
  "action": "MARK_AMBIGUOUS",
  "confirm_permanent_resolution": true,
  "operator_reason": "operator note",
  "evidence_source": "optional label"
}
```

`confirm_permanent_resolution` must be `true` or the API returns `400` with
no mutation.

## Authorization

Stronger than E1 read:

- tenant role: `owner` | `manager` | `operator`
- or platform admin with explicit tenant scope

Reject: `viewer`, `sales`, unauthenticated, admin without `tenant_id`.

## Feature flag

| Flag | Default | Meaning |
|------|---------|---------|
| `PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED` | `false` | E2 mutation gate |

Independent of claim / execution / stranded-alert flags.

## Same-TX contract

Single transaction:

1. `SELECT PublishRetryCommand FOR UPDATE`
2. re-check status
3. `SELECT` resulting `PublishAttempt FOR UPDATE`
4. lineage validation
5. command + attempt terminalization
6. mandatory `PlatformAuditService.record(..., commit=False)`
7. resolve open/acked stranded alert if present
8. commit

Audit event: `publishing.retry_cmd_recon_ambiguous` (≤ 50 chars).

**Audit failure = full rollback** of command, attempt, and alert mutations.

## Concurrency / idempotency

- First concurrent terminal writer wins.
- Exact same-action replay → `resolution=already_resolved` without new audit,
  alert mutation, or `finished_at` rewrite.
- Different future action against `ambiguous` → `409` (not exposed in E2-1).

## Alert resolution

If an E1 stranded alert exists (`dedupe_key=phase_e:stranded_retry:<command_id>`):

- `state=resolved`
- `resolved_by=<actor>`
- `resolved_by_system=false`
- `resolve_note` includes `MARK_AMBIGUOUS`, `command_id`, terminal status
- context `phase_e=stranded_post_barrier` preserved (Auto-Ack exclusion)

Missing alert does not fail resolution. No alert is created merely to resolve it.
Notification delivery is not a prerequisite (`resolve_manual` is durable-row only).

## Non-goals (later slices)

- E2-2 success / failed / cancel / no-effect actions
- Provider reconciliation reads
- Replacement commands (E5)
- Production enablement of E1/E2 or claim/execution
