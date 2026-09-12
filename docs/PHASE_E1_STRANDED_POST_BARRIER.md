# Phase E1 — stranded post-barrier detection (read-only)

**Status:** local / dormant implementation. No production scanner enablement.

**Scope:** observe and surface. Never mutate `PublishRetryCommand` execution
state, never call providers, never terminalize, never create replacement
commands.

## Canonical stranded predicate

A row is a stranded post-barrier candidate iff:

```text
status == 'provider_write_started'
AND provider_write_started_at IS NOT NULL
AND status NOT IN terminal statuses
```

**Excluded** (owned elsewhere):

- `pending`
- `claimed` (including expired pre-barrier leases)
- classic stale `PublishAttempt.in_progress`

## Quiet-period model (heuristic only)

```text
quiet_period_seconds =
  max(PUBLISH_RETRY_COMMAND_LEASE_SECONDS,
      PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS)
  + PUBLISH_RETRY_STRANDED_PROVIDER_SLACK_SECONDS
  + PUBLISH_RETRY_STRANDED_SAFETY_BUFFER_SECONDS
```

Defaults:

| Constant | Default | Role |
|----------|---------|------|
| lease | 180 | execution lease baseline |
| drain | 60 | known drain budget |
| provider_slack | 300 | conservative generic provider slack |
| safety_buffer | 120 | safety buffer |

**Default quiet period = 600 seconds.**

Quiet period affects **classification / surfacing only**. It never:

- authorizes provider write
- changes claim/execution
- proves orphanhood
- proves `provider_not_called`

## Classification semantics

| Label | When | Authority |
|-------|------|-----------|
| `still_in_progress` | age < quiet period | observational candidate only |
| `stranded_review_candidate` | age ≥ quiet period | review heuristic only |
| `outcome_stance=provider_outcome_ambiguous` | review candidate | default without stronger evidence |

**Never emitted from time/audit alone:**

- `definitely_orphaned`
- `provider_not_called` / `provider_not_called_proven`
- `provider_success` / `provider_failure`

## Provider-call-started audit semantics

Event: `publishing.retry_command_provider_call_started`

| Presence | Interpretation |
|----------|----------------|
| present | **intent evidence** — provider execution was intended to begin |
| absent | **unknown** |

Neither presence nor absence proves network call completion, success, failure,
or zero-effect. Neither authorizes replay.

## Operator payload

`GET /api/v1/publishing/retry-commands/stranded`

Read-only, operator/admin auth, tenant-scoped, paginated.

Includes command identity, ages, quiet-period state, historical `lease_owner`
(not liveness), audit intent evidence, `external_post_id` if already stored,
classification, and `recommended_action`.

## Alerting

Optional, behind `PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED=false`
(default).

- Reuses `alert_type=operator_review` (no migration)
- `context.phase_e = "stranded_post_barrier"`
- `severity=critical`
- `requires_operator_action=true` (context)
- `safe_auto_recheck=false` (context)
- `auto_ack_eligible=false` (context)
- Dedupe key: `phase_e:stranded_retry:<command_id>`

Repeated detector runs update the same open/acked alert (no spam).

## Auto-Ack exclusion

Hard exclusion in `evaluate_auto_ack_candidate` via:

- `context.phase_e == stranded_post_barrier`
- `failure_code == stranded_post_barrier`
- plus existing `operator_review` / critical exclusions

## Integration Health separation

Stranded retry commands are **operator alerts**, not Integration Health
provider-outage signals. E1 does not increment provider health counters.

## Flags

| Flag | Default | Meaning |
|------|---------|---------|
| `PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED` | false | durable alert writes |
| `PUBLISH_RETRY_STRANDED_SCANNER_ENABLED` | false | periodic scanner (unused in E1) |

No scheduler is wired in E1. Prefer on-demand read path.

## Non-goals (E2+)

- Command status transitions out of `provider_write_started`
- Provider reconciliation reads/writes
- ACKNOWLEDGE_EXTERNAL_SUCCESS / MARK_* / CANCEL / SUPERSEDE
- Replacement `PublishRetryCommand` creation
