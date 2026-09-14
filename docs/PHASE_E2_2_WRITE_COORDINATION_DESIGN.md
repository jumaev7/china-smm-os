# Phase E2-2 Follow-up B — C3 Duplicate-Write Prevention Design

**Status:** `LOCAL IMPLEMENTED / DORMANT` / `NOT APPROVED FOR ENABLEMENT`

**Kind:** design + local dormant implementation record for destination write
coordination (shared advisory lock + unresolved-write guard).

**Does not:** authorize commit/push, registry work, production deployment,
flag enablement, claim/execution activation, replacement commands, or real
provider I/O.

**Inspected baseline HEAD:**
`2229bea692c1da9b589c19850aab58656b5c0d9e`
(`feat: add dormant manual retry success acknowledgment`)

**Local context preserved:** Follow-up A uncommitted changes
(`publish_service._prior_live_successes` column recognition, path tests,
readiness audit) remain intact and are complementary.

**Applicable AGENTS.md:** only `mobile/AGENTS.md` (Expo docs pointer). No
docs-/backend-scoped `AGENTS.md` found for this phase.

**Related:**

- `docs/PHASE_E2_2_ENABLEMENT_READINESS_AUDIT.md`
- `docs/PHASE_E2_2_MANUAL_RESOLUTION_DESIGN.md`
- `docs/PHASE_E2_MANUAL_RESOLUTION.md` — E2-1 `MARK_AMBIGUOUS`
- `backend/tests/test_publish_write_coordination_e2_2.py`
- `backend/tests/test_e2_2_success_identity_publish_paths.py` — C3 updated

---

## 0. Gates (binding)

| Gate | Verdict |
|------|---------|
| Local Follow-up B implementation | **GO** (dormant; evidence below) |
| Commit / push | **NOT AUTHORIZED** |
| Registry implementation | **NOT AUTHORIZED** |
| Production deployment / E2-1 / E2-2 enablement | **NO-GO** |
| Real provider I/O, replacement creation, claim/execution activation | **NO-GO** |

---

## 1. Implemented decisions

### 1.1 Serialization identity

```text
DestinationIdentity = (tenant_id, content_id, platform, account_id|none)
```

- Cross-version: one destination lock serializes all publish versions for that
  identity (matches live-success cross-version suppression).
- Version / intent eligibility checks remain separate inside `begin_attempt`
  (live success, active claim, max attempts) — the lock does not itself prohibit
  legitimate new intent (different account / platform / content / tenant).
- Key derivation: `SHA-256` over
  `publish_write_coord_v1|tenant|content|platform|account_token` → two signed
  int32 keys for `pg_advisory_xact_lock(k1, k2)`. **Never** Python `hash()`.
- Null account token: `"none"` (identical to `build_idempotency_key`).
- Platform normalization: `.strip().lower()` in every participant.

### 1.2 Tenant ownership and lock ordering

| Participant | Tenant validation | Lock order |
|-------------|-------------------|------------|
| `begin_attempt` | Caller `tenant_id` required when coordination on; SQL join `content_items → clients` must match | 1) destination xact lock → 2) unresolved / live / claim checks → 3) insert claim |
| E2-2 ack apply | Preview load by `(command_id, tenant_id)`; destination lock; then `_lock_command` (tenant-scoped `FOR UPDATE`); re-validate identity; resulting attempt `FOR UPDATE` | 1) destination xact lock → 2) command `FOR UPDATE` → 3) competing `in_progress` check → 4) attempt `FOR UPDATE` |

**Never hold the destination lock across provider network I/O.**

### 1.3 Independent dormant gate

| Flag | Default | Compose pin |
|------|---------|-------------|
| `PUBLISH_WRITE_COORDINATION_ENABLED` | `false` | `:-false` only |
| `PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED` | `false` | `:-false` (unchanged) |
| `PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED` (E2-1) | `false` | independent |

**Truth table (E2-2 acknowledgment):**

| E2_2 | WRITE_COORD | Ack allowed? |
|------|-------------|--------------|
| false | * | 403 (E2-2 disabled) |
| true | false | 403 (coordination required) |
| true | true | proceed (entry rules apply) |

E2-1 `MARK_AMBIGUOUS` is independent of write coordination.

With coordination **disabled**, `begin_attempt` preserves prior behavior (no
destination lock, no unresolved-command guard).

### 1.4 Durable unresolved-write guard

Under the destination lock, before creating/claiming a new attempt, block when a
relevant retry command exists for the same destination identity with status:

- `provider_write_started` (including incomplete timestamp — fail closed)
- `ambiguous` (does not establish absence of provider effect)

Matching is by tenant + content + platform + account (cross-version), grounded in
command/attempt lineage fields — **not** command idempotency key alone.

A new publish version **cannot** bypass this guard.

Denial returns `ClaimResult(skip=True, reason=unresolved_prior_write)` with
`failure_code=unresolved_prior_write`, `retryable=false`. **No** synthetic failed
attempt and **no** automatic retry schedule.

**Pre-barrier `claimed` exclusion:** `claimed` commands are **not** included in
the unresolved guard while retry execution remains disabled. Documented
prerequisite: executor/barrier must join this lock + guard before any future
execution enablement.

### 1.5 Acknowledgment vs in-flight publishing

On the E2-2 apply path (after destination lock + command lock + identity
re-validation):

- If another relevant `in_progress` attempt exists for the destination (any
  version): HTTP `409` with `error=publication_in_progress`.
- Do not wait for the provider operation; do not attempt to cancel it.
- No acknowledgment / audit / alert mutations on rejection.
- Compatible replay of already-terminal manual success skips first-application
  conflict checks (replay path unchanged aside from taking the destination lock).

### 1.6 Transaction lifetime (verified callers)

**Sole production caller of `begin_attempt`:** `PublishService.publish_content`
(manual retry and scheduler inherit via that path).

| Guarantee | How |
|-----------|-----|
| Guard + claim serialized | Same TX holds destination xact lock through checks + insert |
| `in_progress` durable before serialization ends | When coordination enabled, `publish_content` **commits after claim for all platforms** (Meta already did; Telegram now does too under the flag) — lock releases on commit; peers see the row |
| Ack cannot slip between guard and durable claim | Peer ack blocks on same xact lock until claim TX commits or rolls back |
| Lock released before provider I/O | Early commit after claim when coordination on |
| Rollback releases lock | `pg_advisory_xact_lock` is transaction-scoped |
| Caller-owned TX | begin_attempt uses caller's session; early commit is owned by `publish_content` |

No migration required. No substantial transaction redesign beyond extending the
existing Meta early-commit pattern to all platforms **when coordination is on**.

**Pre-commit boundary verification (local):** callers already depended on Meta
early-commit durability (manual_retry pending supersede, content
`publishing`, claim visibility). Coordination-on non-Meta matches that
contract; coordination-off non-Meta retains deferred commit. Denied/skip
destination locks are not held across a later provider invocation. See
`docs/PHASE_E2_2_ENABLEMENT_READINESS_AUDIT.md` §3A and
`test_publish_write_coordination_e2_2.py` TX boundary tests. **No fix applied**
— behavior matches the established contract.

---

## 2. What C3 proves now

| Mode | Behavior |
|------|----------|
| Coordination **disabled** | Ordinary publish can still invoke adapter while stranded `provider_write_started` exists; E2-2 ack alone is gate-rejected (403) without coordination |
| Coordination **enabled** | Unresolved `provider_write_started` blocks new provider invocation (adapter 0). If a durable same-destination `in_progress` already exists, ack returns `409 publication_in_progress` with no mutation. Already in-flight adapter I/O cannot be rewound |

---

## 3. Remaining limitations / enablement blockers

1. Registry / measurement lag (F2) — still blocking enablement.
2. ContentItem non-repair (F3) — still open.
3. Platform-keyed `_prior_live_successes` account-selection limitation — **retained**
   (Follow-up A); not redesigned here. Account-aware safety remains in
   `begin_attempt` / write-coordination identity.
4. In-flight provider HTTP cannot be revoked by DB locks.
5. Executor/barrier not participants yet — enablement blocker before execution on.
6. Provider-native idempotency not established.
7. Flags / production image / real providers — still NO-GO.

---

## 4. Document control

| Item | Value |
|------|-------|
| Phase | E2-2 Follow-up B |
| Deliverable | Local dormant implementation + tests + this design update |
| Enablement | **NO-GO** |

**STOP.**
