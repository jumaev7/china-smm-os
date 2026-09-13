# Phase E2-2 — Manual Resolution Contract

**Status:** `LOCAL IMPLEMENTED` / `DORMANT` / `NOT APPROVED FOR PRODUCTION`

**Baseline inspected (local):** `6402de83f04199b2607098839e37cede7ff5cb6f`
(`master` = `origin/master`; matches last accepted E2-1 land commit).

**Authority of this document:** records the approved Alternative A / success-only
decisions and what was implemented locally. It does **not** amend the landed
E2-1 contract in `docs/PHASE_E2_MANUAL_RESOLUTION.md`. It does **not** authorize
production enablement, migrations, env changes, provider I/O, claim, execution,
or replacement commands.

**Implementation slice (this edit):** local dormant `ACKNOWLEDGE_EXTERNAL_SUCCESS`
only, gated by `PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED` (default false).

---

## 0. Document control

| Item | Value |
|------|-------|
| Phase | E2-2 |
| Kind | Operator contract + local dormant implementation |
| Implements code? | Yes (local / dormant; success-only) |
| Changes E2-1 semantics? | No (compatibility required and preserved) |
| Production enablement? | NO-GO |

Related (verified existing, not rewritten here):

- `docs/PHASE_E2_MANUAL_RESOLUTION.md` — landed E2-1 `MARK_AMBIGUOUS` contract
- `docs/PHASE_E1_STRANDED_POST_BARRIER.md` — read-only stranded detection
- `docs/OPERATOR_WORKSPACE.md` — notes E2-2+ as not implemented
- Applicable workspace `AGENTS.md`: only `mobile/AGENTS.md` (Expo docs pointer);
  no docs-/backend-scoped AGENTS.md found for this phase

---

## 1. Verified existing contract (E2-1) — evidence only

### 1.1 Scope as shipped

E2-1 allows **one** action: `MARK_AMBIGUOUS`.

Verified sources:

- Doc: `docs/PHASE_E2_MANUAL_RESOLUTION.md` lines 9–24, 126–129
- Service: `backend/app/services/publish_retry_command_manual_resolution_service.py`
  lines 1–14, 42–43, 106–114
- Schema: `backend/app/schemas/publishing.py` lines 220–230
  (`Literal["MARK_AMBIGUOUS"]`)
- Route: `backend/app/api/v1/publishing.py` lines 404–449
- Flag: `PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED` default `false`
  (`backend/app/core/config.py` lines 154–156;
  `docker-compose.production.yml` pins `:-false`)

### 1.2 Entry gate and terminals (verified)

Entry (E2-1):

```text
status == 'provider_write_started'
AND provider_write_started_at IS NOT NULL
AND resulting_attempt_id IS NOT NULL
AND bidirectional lineage valid
```

Effects (E2-1):

| Entity | Mutation |
|--------|----------|
| `PublishRetryCommand.status` | → `ambiguous` |
| `PublishRetryCommand.provider_outcome` | → `ambiguous` |
| `PublishRetryCommand.finished_at` | → now |
| resulting `PublishAttempt.status` | → `operator_review` |
| resulting attempt `retryable` / `next_retry_at` | → `false` / `null` |
| original attempt | **not mutated** |
| ContentItem / `tenant_external_publications` | **not mutated** |

Verified: service lines 166–205; doc lines 28–50.

Permanent non-executability (verified):

- Claim selects only `status == 'pending'`
  (`publish_retry_command_claim_service.py` lines 178–188).
- Terminal set includes `ambiguous`
  (`publish_retry_command.py` lines 36–43).
- E2-1 never returns a command to `pending` / `claimed`
  (service lines 139–150; doc lines 34–35, 50).

### 1.3 Idempotency / conflict (verified)

- Same-action replay on already `ambiguous` + matching outcome →
  `resolution=already_resolved`, no new audit / alert / timestamp rewrite
  (service lines 131–137, 267–305; doc lines 104–109).
- Different action against terminal `ambiguous` → `409 already_resolved`
  (service lines 152–164; doc line 109: “not exposed in E2-1”).
- **Gap carried into E2-2:** E2-1 replay keys only on
  `status` + `provider_outcome` + action name. That is insufficient for
  success/failure terminals because the executor/finalizer can produce the
  same shape (see §6.2).

### 1.4 Same-TX audit / alert (verified)

Lock order: command `FOR UPDATE` → re-check → resulting attempt `FOR UPDATE`
→ lineage → mutate → mandatory audit (`commit=False`) → optional stranded
alert resolve → commit. Audit failure rolls back all mutations
(doc lines 87–102; service lines 207–226, 396–438).

Alert Auto-Ack exclusion preserved via `context.phase_e=stranded_post_barrier`
(doc lines 111–119; E1 doc lines 104–110).

### 1.5 E2-C8 status

**E2-C8** appears in the Phase E2 design-gate report
(chat [E2 design gate](84fb25bf-6e5d-4c5a-a03b-9d40559b36b8)) as:

> **E2-C8** No-effect initially requires strong (L4) evidence

No dedicated acceptance-record file for E2-C8 was found in the repository.
E2-1 explicitly deferred `MARK_NO_EFFECT_CONFIRMED`
(`docs/PHASE_E2_MANUAL_RESOLUTION.md` lines 15–17, 126).

**Verdict for this task:** E2-C8 is **documented in the prior design gate** as
an invariant for a future no-effect action. Its formal acceptance status for
implementation is **unknown** (no repo acceptance artifact found). This design
does **not** infer why it was omitted from E2-1. **E2-C8 remains deferred with
no-effect:** it does not apply to the included E2-2 action
(`ACKNOWLEDGE_EXTERNAL_SUCCESS`).

### 1.6 Name inventory (docs vs discussion)

Documented deferred names (E2-1 / E1):

- `ACKNOWLEDGE_EXTERNAL_SUCCESS`
- `MARK_FAILED_CONFIRMED`
- `MARK_NO_EFFECT_CONFIRMED`
- `CANCEL`
- `SUPERSEDE` (E1 / earlier design; defer E5)

Discussion candidates (not in landed E2-1 code):

- `CONFIRM_SUCCEEDED`
- `CONFIRM_FAILED`
- `KEEP_AMBIGUOUS`
- `MARK_SAFE_TO_RETRY`

---

## 2. Architectural conflict and recommended resolution

### 2.1 Conflict statement

Two incompatible operator stories exist:

1. **E2-1 as shipped:** first terminal writer wins. A command that becomes
   `ambiguous` is permanently non-executable, and a **different** future action
   against that terminal returns `409` (no terminal rewrite).
2. **Post-ambiguous clarification story:** after `MARK_AMBIGUOUS`, an operator
   later records an authoritative “really succeeded / really failed”
   clarification for the **same** command.

These cannot both be true if “clarification” means rewriting
`status` from `ambiguous` → `succeeded` / `failed` under current E2-1 rules.
Changing terminal-state semantics is **not** treated as approved.

### 2.2 Alternatives compared

| Alt | Idea | Pros | Cons |
|-----|------|------|------|
| **A. Parallel first-terminalization** | E2-2 success (and any future failed) are alternative first terminals from `provider_write_started`, mutually exclusive with `MARK_AMBIGUOUS` | Fully compatible with E2-1; no terminal rewrite; matches prior design-gate E2-2 slice | Operators who already chose `MARK_AMBIGUOUS` cannot later “upgrade” outcome on the same row |
| **B. Overlay clarification** | Keep `status=ambiguous` forever for execution; store clarified business outcome in separate fields / append-only resolution model | Preserves permanent non-executability; allows later operator truth | Needs schema/API design; risk of dual sources of truth; not smallest |
| **C. Amend terminal rewrite** | Allow `ambiguous` → `succeeded`/`failed` with new confirmation | Matches “confirm after ambiguous” UX | **Changes E2-1 invariants**; needs explicit approval; weakens first-writer law |

### 2.3 Recommendation (proposed, not approved)

**Recommend Alternative A as the working design direction for E2-2.**

This is a **design direction**, not implementation approval.

- Source state that may accept E2-2 actions: **`provider_write_started` only**
  (same entry gate as E2-1, including timestamp + lineage).
- Clarified outcome is stored in the **existing lifecycle fields**
  (`status`, `provider_outcome`) as the **first** terminalization, not as a
  second rewrite.
- **No rewriting** of `ambiguous` or any other existing terminal.
- Original command remains permanently non-executable because every allowed
  E2-2 terminal is in `RETRY_COMMAND_TERMINAL_STATUSES` and claim only takes
  `pending`. E2-2 must never set `pending` / `claimed`.

**Explicit product limitation:** this slice does **not** resolve cases already
marked `ambiguous`. Post-ambiguous clarification remains **deferred** (Alt B
overlay or separately approved Alt C). Operators who terminalized with
`MARK_AMBIGUOUS` cannot later apply `ACKNOWLEDGE_EXTERNAL_SUCCESS` (or any
future failed action) to the same command row; they receive
`409 already_resolved`.

**Compatibility with E2-1:** E2-2 adds actions to the same resolve endpoint /
service framework; E2-1 `MARK_AMBIGUOUS` behavior remains unchanged.

---

## 3. Recommended minimal E2-2 scope

### 3.1 In scope (proposed) — narrowed

Reuse:

```http
POST /api/v1/publishing/retry-commands/{command_id}/resolve
```

**Include exactly one new action:**

| Canonical action | Discussion alias | Meaning |
|------------------|------------------|---------|
| `ACKNOWLEDGE_EXTERNAL_SUCCESS` | ≈ `CONFIRM_SUCCEEDED` | Operator asserts an external publication identity exists and attributes it to this command’s resulting attempt |

**Defer from this slice:** `MARK_FAILED_CONFIRMED` (see §4.3 — no defensible
server-validated failure-evidence contract without conflating operator
attestation with provider `DEFINITIVE_FAILURE` / `known_failure`).

Shared rules for the included action:

- **Separate feature flag** from E2-1 (see §5.5). Do not auto-enable E2-2 when
  E2-1 is enabled.
- Zero provider API requests; no automatic fetch of evidence URLs.
- No claim, execution, worker, barrier, finalizer, or replacement-command paths.
- Original attempt untouched; resulting attempt only.
- ContentItem **not** mutated in E2-2.
- `tenant_external_publications` **not** mutated in **minimal** E2-2
  (see §3.3 / §3.4 consequences and enablement blocker).

### 3.2 Explicitly deferred / excluded

| Candidate | Disposition | Why |
|-----------|-------------|-----|
| `MARK_FAILED_CONFIRMED` | **Defer (out of E2-2 minimal)** | No structural failure evidence the server can validate; reason/`evidence_source` alone must not authorize `known_failure` (see §4.3) |
| `KEEP_AMBIGUOUS` | **Exclude** (redundant) | Already covered by E2-1 `MARK_AMBIGUOUS` |
| `MARK_SAFE_TO_RETRY` | **Exclude** (do not ship under this name) | Implies a safety guarantee the system cannot establish without provider reconciliation / replacement policy; must **not** authorize automatic retry or replacement creation |
| `CANCEL` | Defer (E2-3+) | Abandon-without-outcome; lower urgency than success bookkeeping |
| `MARK_NO_EFFECT_CONFIRMED` | Defer (E2-4+; E2-C8 applies) | Requires strong L4 “no publication” evidence; absence-from-view / errors are **not** proof of no effect |
| `SUPERSEDE` / replacement | **NO-GO for E2** | E5 |
| Provider reads | **NO-GO** | E3/E4 |
| Post-ambiguous status rewrite | **NO-GO** without separate approval | Conflicts with E2-1 |
| Mobile mutations | Defer / NO-GO for first E2-2 | Match E2-1 |
| Publication-registry upsert | Defer (follow-up slice) | See §3.3–§3.4; not silently expanded here |

### 3.3 ContentItem / publication boundary (consequences)

**ContentItem:** leave unchanged. Multi-destination aggregate status is unsafe to
derive from one retry command (prior design gate). Audit should record
`content_repair=skipped_unsafe_aggregate`.

**`tenant_external_publications`:** minimal E2-2 **defers** upsert even on
confirmed success. This is an explicit **product/safety limitation**, not an
accepted claim of system-wide duplicate prevention.

### 3.4 Downstream safety of deferred publication registry (verified)

#### 3.4.1 Consumer / entry-point evidence table

| Path | File:lines (verified) | Role |
|------|----------------------|------|
| Claim selector (command executability) | `publish_retry_command_claim_service.py` 178–188 | Selects `status == 'pending'` only |
| Command create-or-get | `publish_retry_command_service.py` 112–176, 306–341 | Eligibility on **original** attempt; active/terminal reuse by idempotency; `failed` → `terminal_failed_closed` |
| Preparation live-success check | `publish_retry_command_preparation_service.py` 845–859, 862–908 | `find_live_success` by idempotency + content/platform/account; resulting attempt uses same `build_idempotency_key(...)` |
| Manual retry eligibility | `manual_retry_eligibility.py` 280–440, 509–545 | Original-attempt status/failure_code gates; `has_live_success` via `find_live_success` |
| Workspace / ops manual retry | `publish_attempt_ops_service.py` 142–215; `operator_workspace_actions.py` ~582–603 | Can call `PublishService.publish_content` (new provider write path) when eligibility allows |
| Live-success / begin_attempt dedup | `publish_resilience.py` 261–302, 351–360, 361–382 | Suppresses new claims when a success attempt has `external_post_id` (or response `platform_post_id`) for same key or content+platform+account |
| PublishService prior-success helper | `publish_service.py` 702–743 | Alternate path keyed on `status==success` **and** parsed `response.platform_post_id` (does **not** use column `external_post_id` alone) |
| Publication registry upsert | `publication_registry.py` 113–171; `publish_service.py` 987–1008 | Only from verified successful **PublishService** results with `platform_post_id`; not called from retry-command finalizer/manual resolution |
| Retry-command finalizer success | `publish_retry_command_finalization_service.py` 428–492 | Sets attempt `success` + `external_post_id`; does **not** register publications or mutate ContentItem |
| Measurement readers | `measurement/read_service.py`, `campaign_measurement.py` | Consume `tenant_external_publications` rows — lag if registry deferred |

#### 3.4.2 Consequences matrix (minimal E2-2, registry deferred)

| Scenario | What happens | What does **not** happen |
|----------|--------------|---------------------------|
| **A. Mark resulting attempt successful; ContentItem + registry unchanged** | Command → `succeeded`/`known_success` (non-claimable). Resulting attempt → `success` + `external_post_id`. `find_live_success` / `begin_attempt` **can** suppress same-destination republish when they see the column (`publish_resilience.py` 271–301, 351–360). Same-identity `create_or_get_command` returns terminal reuse (306–341). | ContentItem aggregate status not repaired. Registry/measurement not updated. `_prior_live_successes` may **miss** the success if `response` JSON lacks `platform_post_id` (`publish_service.py` 724–737). Manual retry on **original** attempt still evaluates original row; live-success revalidation may block **if** keys align, but this is not a guarantee for every alternate publish entry. |
| **B. (Deferred action reference) Mark resulting attempt failed + non-retryable; original unchanged** | Command non-claimable; resulting attempt not auto-retried. Same-identity command recreate fail-closed if status `failed` (322–332). | Original attempt eligibility unchanged. `PublishAttemptOpsService.manual_retry` / `PublishService.publish_content` remain separate application paths that can still create a **new** publication when eligibility/publish gates allow. `retryable=false` on the resulting attempt does **not** system-wide-block duplicates. |

#### 3.4.3 Distinctions (required wording)

1. **Original command non-claimable** ≠ **no new publication can occur**.
   Claim only gates this command row (`status==pending`). Other paths
   (`PublishService.publish_content`, manual retry ops, future commands with
   different idempotency identity) are independent.
2. **Do not claim system-wide duplicate prevention** from claim-selector
   exclusion or `retryable=false` alone.
3. Partial mitigation for success-ack: storing `external_post_id` on a
   `success` resulting attempt participates in `find_live_success` /
   `begin_attempt` dedup for matching destination identity. That is
   **destination-attempt dedup**, not registry completeness and not a
   ContentItem repair.

#### 3.4.4 Enablement blocker (still blocking production)

Because deferred registry + unchanged ContentItem leave measurement lag and
secondary-path ambiguity (especially `_prior_live_successes` response-JSON
dependency), **production enablement of E2-2 success-ack remains blocked**
until a separately authorized follow-up either:

1. Adds same-TX (or explicitly ordered) publication-registry upsert on
   `(tenant_id, publishing_account_id, platform, provider_publication_id)` and
   documents ContentItem non-repair, **or**
2. Accepts an explicit product waiver that measurement lag and secondary-path
   gaps are tolerable for a named environment.

**Corrected enablement language (binding):**

- A future registry upsert alone is **not** proof that alternate publishing
  paths are safe.
- Before enablement, separately review and verify affected
  deduplication/publication paths, response-JSON consumers, and
  registry/measurement consistency.
- **No waiver is granted by the local E2-2 implementation task.**

This local slice must **not** silently expand into publication-registry
implementation.

---

## 4. Action contract (proposed)

### 4.0 Verified classifier / finalizer semantics (grounding)

Provider-agnostic classifier
(`publish_retry_command_outcome_classifier.py`):

| Input | Normalized outcome | Notes |
|-------|-------------------|-------|
| `ProviderExecutionResult.outcome == "success"` **with** non-empty `external_post_id` | `SUCCESS` | lines 52–71 |
| `success` missing `external_post_id` | `AMBIGUOUS` | lines 54–64 |
| `outcome == "definitive_failure"` | `DEFINITIVE_FAILURE` | lines 73–79 |
| timeout / exception / malformed / other | `AMBIGUOUS` | lines 44–50, 81–87, 90–108 |

Finalizer (`publish_retry_command_finalization_service.py`):

| Classified | Command | Attempt | Codes |
|------------|---------|---------|-------|
| SUCCESS | `succeeded` / `known_success` | `success` + external id; clear failure fields | reason `provider_success` (428–492) |
| DEFINITIVE_FAILURE | `failed` / `known_failure` | `failed`; `failure_category=command_orchestration`; provider/forensic `failure_code` | reason `provider_definitive_failure` (495–541) |
| AMBIGUOUS | `ambiguous` / `ambiguous` | `operator_review` | (544–588) |

**Definitive failure in this system** means: the provider port returned
`definitive_failure`, and the finalizer recorded `known_failure` /
attempt `failed` with a provider-supplied (or classifier-default)
`failure_code`. It is **not** synonymous with proof of no provider side
effect (that is the deferred no-effect / E2-C8 concern).

### 4.1 Shared entry / rejection

**Allowed source state (included E2-2 action):**

```text
status == 'provider_write_started'
AND provider_write_started_at IS NOT NULL
AND resulting_attempt_id IS NOT NULL
AND bidirectional lineage valid
```

Barrier invariant note: write-started attempts are created/mutated with
`external_post_id` / `external_post_url` unset
(`publish_retry_command_barrier_service.py` 814, 884). Conflict checks below
remain for races/corruption.

**Prohibited source states:**

| State | Error |
|-------|-------|
| `pending`, `claimed` | `409 not_resolvable` |
| any terminal including `ambiguous` | `409 already_resolved` (except exact same-action **manual** replay — §6.2) |
| executor-produced `succeeded`/`failed` without manual provenance | `409 already_resolved` (not a manual replay) |
| missing write-started timestamp / missing resulting attempt / lineage break | `409 lineage_conflict` or `409 not_resolvable` as appropriate |
| E2-2 flag off | `403` |
| wrong role / missing tenant scope | `401` / `403` / admin without `tenant_id` |
| confirmation false/missing | `400` |

**Evidence limitations (all actions, including deferred ones):**

- Evidence is **operator-supplied only**.
- No provider HTTP; no server-side URL fetch; no scraping.
- Time / quiet period alone never satisfies success or failure evidence
  (inherits E2-C7 from design gate).
- An error message, timeout, or “I don’t see the post” is **not** proof of
  no provider effect and **must not** alone authorize success, failure, or
  no-effect claims.
- A non-empty `operator_reason` and `evidence_source` label alone are
  **never** sufficient proof of definitive failure or of success.

### 4.2 `ACKNOWLEDGE_EXTERNAL_SUCCESS` (included)

| Item | Contract |
|------|----------|
| Meaning | Operator confirms an external post identity exists and attributes it to this command’s resulting attempt (**operator attestation** of success identity, not a live provider read) |
| Source | `provider_write_started` only |
| Required confirmation | `confirm_permanent_resolution: true` |
| Required evidence | Non-empty `operator_reason`; non-empty `external_post_id`; non-empty `evidence_source`; optional `external_post_url`; optional `observed_at` |
| What server validates structurally | Non-empty trimmed strings; length bounds (§5.1); URL shape if provided (§5.1); confirmation boolean; action enum; tenancy/authz; entry state; lineage; conflict vs existing attempt `external_post_id` |
| What server must trust as attestation | That the id/url actually refers to a live provider object created by / for this stranded write — **not** re-verified in E2-2 |
| Insufficient evidence | Missing/blank id, reason, or evidence_source; URL-only without id; oversized fields → `400 evidence_insufficient` / validation error — **no mutation** |
| Contradictory evidence | If resulting attempt already has a **different** non-null `external_post_id` → `409 evidence_conflict`. Same id → compatible for apply/replay rules in §6.2 |
| Command effects | `status=succeeded`, `provider_outcome=known_success`, `finished_at=now`, `reason_code=operator_ack_external_success` |
| Resulting attempt | `status=success`, set `external_post_id` (+ optional url), `retryable=false`, `next_retry_at=null`, clear `failure_code`/`failure_category`/`error`, `finished_at=now`. **Do not** fabricate `response` JSON solely to satisfy `_prior_live_successes` unless a later approved slice explicitly requires it |
| Original attempt | **no mutation** |
| ContentItem | **no mutation** |
| `tenant_external_publications` | **no mutation** (minimal scope; enablement blocker §3.4.4) |
| Alert | Resolve open/acked stranded alert if present (`resolve_manual`); missing alert OK |
| Audit | Mandatory `publishing.retry_cmd_recon_success` (≤50 chars) in same TX; see §6.3 |
| Prohibited | provider I/O; replacement command; reset to pending/claimed; ContentItem/publication writes; claiming success from absence of error alone |

### 4.3 `MARK_FAILED_CONFIRMED` — deferred (not in minimal E2-2)

#### 4.3.1 Why deferred

Prior draft text rejected errors/timeouts/absence as sufficient evidence (§4.1)
while still allowing operator judgment to assign `known_failure` (§4.3). That
contradiction is removed by **deferring** the action.

Within this slice, a defensible contract cannot be specified because:

1. System `DEFINITIVE_FAILURE` is defined only by provider-port outcome
   (`outcome_classifier.py` 73–79), not by free-text attestation.
2. The server cannot structurally validate “definitive failure” without
   provider I/O (out of scope / NO-GO).
3. Assigning `provider_outcome=known_failure` would make an operator
   attestation **look identical** to executor finalization
   (`finalization_service.py` 513–514) to downstream readers of that field.
4. `operator_reason` + `evidence_source` alone must not be presented as proof
   of definitive failure.

**Recommendation:** narrow E2-2 to `ACKNOWLEDGE_EXTERNAL_SUCCESS` only.
Do not force both actions into scope.

#### 4.3.2 Semantics retained for a future failed-action design (not authorized)

If a later phase revisits failure confirmation, it must separately define:

| Topic | Requirement |
|-------|-------------|
| Definitive failure vs no-effect | Failure bookkeeping ≠ proof of zero provider side effects (E2-C8 / `MARK_NO_EFFECT_CONFIRMED`) |
| Operator-supplied evidence that could support classification | Only evidence types a future approved contract enumerates; weak narrative (`error`, timeout, “not visible”) remain **insufficient** → leave command unchanged |
| Structural validation vs attestation | Server may validate labels/enums/lengths; truth of failure remains attestation unless provider verification exists |
| Existing publication identity + failed request | If resulting attempt already has non-null `external_post_id` (or prior success identity) and the request is failed-confirmed → **`409 evidence_conflict`** (or require success/no-effect path). Do not clear a stored external id via failed-confirm |
| Failure codes | Must not invent provider codes; if ever implemented, use explicit operator forensic codes distinct from `retry_command_provider_failed` unless intentionally aligning — see §5.6 |

Until that contract exists, any `MARK_FAILED_CONFIRMED` request (if accidentally
exposed) must be rejected as unsupported (`400`), with **no mutation**.

### 4.4 Mutations permitted vs prohibited (summary)

**Permitted (minimal E2-2 — success only):**

- Command terminal fields listed in §4.2
- Resulting attempt bookkeeping fields listed in §4.2
- Stranded alert resolve row (if present)
- Append-only platform audit row

**Prohibited:**

- Any transition to `pending` / `claimed`
- Mutating original attempt
- Creating `PublishRetryCommand` rows
- Calling claim / worker / executor / provider adapters
- Fetching evidence URLs
- Mutating ContentItem
- Mutating `tenant_external_publications` (minimal scope)
- Rewriting an existing different terminal
- Auto-Ack of stranded / E2 alerts
- Applying `MARK_FAILED_CONFIRMED` / no-effect / cancel / supersede

---

## 5. API shapes (documentation only)

### 5.1 Request (proposed extension of E2-1 body)

```json
{
  "action": "ACKNOWLEDGE_EXTERNAL_SUCCESS",
  "confirm_permanent_resolution": true,
  "operator_reason": "Verified live Telegram message in channel UI",
  "evidence_source": "operator_provider_ui",
  "external_post_id": "12345",
  "external_post_url": "https://t.me/c/…/12345",
  "observed_at": "2026-09-13T12:00:00Z"
}
```

Field rules (proposed):

| Field | Required | Limits / validation |
|-------|----------|---------------------|
| `action` | yes | enum: E2-1 `MARK_AMBIGUOUS` \| E2-2 `ACKNOWLEDGE_EXTERNAL_SUCCESS` (failed deferred) |
| `confirm_permanent_resolution` | yes | E2-2: raw JSON boolean `true` only (schema rejects `"true"` / `1` / `false` / `null` / missing → API **422**). E2-1: coercible bool preserved; service rejects non-True → **400** |
| `operator_reason` | yes | 1–1000 chars after trim |
| `evidence_source` | E2-2 yes; E2-1 optional | ≤80 chars; labels only; **not** proof by itself |
| `external_post_id` | success yes | trim; non-empty; **≤255** to match `PublishAttempt.external_post_id` / registry `provider_publication_id` (`publish_attempt.py` 63; `measurement.py` / registry truncate at 255). Reject `>`255 — do not silent-truncate operator input. Opaque string; no platform-specific format enforcement in first E2-2 |
| `external_post_url` | optional | If present: align with registry permalink rules (`publication_registry.py` 42–55): http/https only; netloc required; ≤2000; reject signed-URL markers; store as reference only; **never fetched** |
| `observed_at` | optional | timestamptz |

Sensitive-data limits: no access tokens, cookies, raw provider payloads,
message bodies, or PII dumps in reason/evidence fields. Audit stores the same
bounded fields.

### 5.2 Response (proposed)

```json
{
  "command_id": "…",
  "resulting_attempt_id": "…",
  "status": "succeeded",
  "provider_outcome": "known_success",
  "attempt_status": "success",
  "resolution": "applied",
  "finished_at": "…",
  "action": "ACKNOWLEDGE_EXTERNAL_SUCCESS",
  "audit_event_type": "publishing.retry_cmd_recon_success",
  "audit_id": "…",
  "correlation_id": "…",
  "alert_resolved": true,
  "external_post_id": "12345"
}
```

`resolution`: `applied` | `already_resolved`.

On **replay** (`already_resolved`): return the **prior** `audit_id` /
`audit_event_type` from provenance lookup when available; `alert_resolved`
must be `false` (no alert mutation on replay, matching E2-1). Do not mint a
new audit id.

### 5.3 Error codes (proposed)

| HTTP | `error` | When |
|------|---------|------|
| 400 | (detail string / `evidence_insufficient`) | bad action, service-level confirmation False, evidence normalization |
| 401 | — | unauthenticated |
| 403 | — | role / E2-2 flag disabled |
| 404 | — | command not found in tenant (anti-enumeration) |
| 409 | `not_resolvable` | wrong active state |
| 409 | `already_resolved` | terminal mismatch / other action / executor terminal |
| 409 | `lineage_conflict` | attempt linkage broken |
| 409 | `evidence_conflict` | contradictory durable ids, replay evidence mismatch, or fail-closed audit provenance |
| 422 | request validation | E2-2 `confirm_permanent_resolution` not JSON boolean `true` (Pydantic/FastAPI boundary) |

`stale_state` was **not** introduced. Finalizer/operator races fold into
`already_resolved` / `not_resolvable` / `lineage_conflict` as appropriate.

### 5.4 AuthZ / tenancy (proposed = E2-1)

- Tenant roles: `owner` | `manager` | `operator`
- Platform admin: allowed only with **explicit** `tenant_id` query scope
- Reject: `viewer`, `sales`, unauthenticated, admin without tenant scope

Verified E2-1 actor helper: `publishing.py` lines 118–141.

### 5.5 Feature flag recommendation (proposed)

| Flag | Default | Coupling |
|------|---------|----------|
| `PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED` | `false` (existing) | Gates **E2-1** `MARK_AMBIGUOUS` only (as shipped) |
| `PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED` | `false` (implemented) | Gates **E2-2** `ACKNOWLEDGE_EXTERNAL_SUCCESS` only |

**Selected:** separate flags. Enabling E2-1 must **not** activate E2-2.
Enabling E2-2 must **not** require E2-1 to be on (they are alternative first
terminals from the same entry state). Shared endpoint/service code is used;
activation coupling is not. Isolation is covered by tests.

### 5.6 Failure codes / categories (for deferred failed action only)

Grounded in current consumers:

- Finalizer definitive path sets `failure_category="command_orchestration"` and
  `failure_code` from provider/classifier (`finalization_service.py` 70–71,
  508–510; classifier defaults `retry_command_provider_failed` at
  `outcome_classifier.py` 22).
- Manual retry eligibility taxonomy (`manual_retry_eligibility.py` 62–95)
  does **not** list `retry_command_*` codes as conditional-allow; unknown codes
  deny (`failure_code_unknown`).

**If** failed-confirm is later designed: prefer an explicit operator forensic
code (e.g. `operator_mark_failed_confirmed`) + `failure_category=command_orchestration`
(or a new category), and document that this is attestation — not provider
definitive failure. **Not part of minimal E2-2.**

---

## 6. Transaction, concurrency, audit, replay provenance

### 6.1 Lock order / TX boundary (proposed = E2-1 pattern)

Single transaction:

1. `SELECT PublishRetryCommand FOR UPDATE` (id + tenant)
2. Re-validate status under lock
3. `SELECT` resulting `PublishAttempt FOR UPDATE`
4. Bidirectional lineage validation (fail closed; no silent repair)
5. Apply command + attempt mutations
6. Mandatory `PlatformAuditService.record(..., commit=False)`
7. Resolve open/acked stranded alert if present
8. Commit

**Audit failure ⇒ full rollback** of command, attempt, and alert mutations.

Out of TX / non-fatal: notification delivery, metrics.

### 6.2 Replay provenance and exact compatibility

Matching `status` + `provider_outcome` alone does **not** establish that a
manual resolution previously occurred: the executor/finalizer may produce
`succeeded`/`known_success` (`finalization_service.py` 462–463) or
`failed`/`known_failure` (513–514) with system audit events
`publishing.retry_command_provider_*` (620–624).

#### 6.2.1 Authoritative provenance source (proposed)

For `ACKNOWLEDGE_EXTERNAL_SUCCESS` replay:

1. **Primary durable discriminator:** `command.reason_code ==
   "operator_ack_external_success"` (distinct from `provider_success`).
2. **Authoritative evidence snapshot:** the mandatory applied
   `PlatformAuditLog` row with
   `event_type=publishing.retry_cmd_recon_success`,
   `resource_type=publish_retry_command`,
   `resource_id=<command_id>`,
   and `details.action=ACKNOWLEDGE_EXTERNAL_SUCCESS`
   (`platform_ops.py` 73–87 stores JSONB `details`).

Assessment of existing fields:

| Need | Existing? | Verdict |
|------|-----------|---------|
| Distinguish manual vs executor success | `reason_code` + distinct audit `event_type` | **Sufficient if** E2-2 always sets `operator_ack_external_success` and never rewrites it |
| Compare operator_reason / evidence_source / url / observed_at | Only in audit `details` today (E2-1 pattern) | **Sufficient with audit lookup**; no migration required for correctness **if** replay fails closed when audit missing |
| Stable audit identity on replay | `PlatformAuditLog.id` | Return prior id; do not insert |

**Proposed schema need (only if audit-lookup is rejected as too weak):** add
nullable durable columns or an append-only resolutions table for last manual
action + evidence hash. **Not required** for the preferred audit-lookup design;
document only — do not implement in this task. Prefer correctness over
“no migration” slogans if a future implementer rejects audit lookup.

#### 6.2.2 Replay decision table (`ACKNOWLEDGE_EXTERNAL_SUCCESS`)

| Case | Behavior |
|------|----------|
| Applied path from `provider_write_started` with valid evidence | Mutate; write audit; optional alert resolve; `resolution=applied` |
| Terminal `succeeded` + `known_success` + `reason_code=operator_ack_external_success` + matching audit + **same** `external_post_id` + **same** `evidence_source` + **same** trimmed `operator_reason` + same optional url/observed_at (null≡null) | `already_resolved`; **no** mutation; **no** new audit; **no** alert change; **no** timestamp rewrite; return prior `audit_id` |
| Same action, changed `external_post_id` | `409 evidence_conflict` — do not replace stored id/evidence |
| Same action, changed reason / evidence_source / url / observed_at | `409 evidence_conflict` — do not silently replace prior evidence |
| Terminal `succeeded`/`known_success` but `reason_code=provider_success` (or missing manual audit) | `409 already_resolved` — executor-produced terminal; **not** a manual replay; do not fabricate manual audit |
| Terminal `ambiguous` / `failed` / other | `409 already_resolved` |
| Missing audit while reason_code claims manual success | `409 evidence_conflict` or `409 lineage_conflict` (fail closed) — do not treat as replay |
| Inconsistent lineage on replay | `409 lineage_conflict` |
| Two concurrent E2 actions / finalizer vs operator | First commit wins under `FOR UPDATE`; loser sees terminal → `409 already_resolved` |

**Ignored without mutation on compatible replay:** client-supplied
`confirm_permanent_resolution` repeats; actor identity differences; alert
already resolved. Do **not** silently replace prior evidence or fabricate a
manual-resolution audit for executor terminals.

### 6.3 Audit details (append-only)

Required details keys on **applied** success:

- actor_id, actor_type, tenant_id
- command_id, original_attempt_id, resulting_attempt_id
- action, old/new status, old/new provider_outcome, old/new reason_code
- attempt_status (after); attempt external_post_id/url (after)
- operator_reason, evidence_source, external_post_id/url (if any)
- observed_at (if any)
- correlation_id, timestamp
- `content_repair=skipped_unsafe_aggregate`
- `publication_repair=deferred_minimal_e2_2`
- `provenance=manual_resolution_e2_2`

Event types (≤50):

| Action | event_type |
|--------|------------|
| success (E2-2) | `publishing.retry_cmd_recon_success` |
| (existing) ambiguous | `publishing.retry_cmd_recon_ambiguous` |
| (executor, not manual) | `publishing.retry_command_provider_succeeded` / `_failed` / `_ambiguous` |

**Rollback requirements:** any failure after mutation start and before commit —
including audit flush failure — rolls back command, attempt, and alert changes
(same as E2-1).

### 6.4 Alerts / Auto-Ack

On applied E2-2 resolution: same stranded-alert resolve behavior as E2-1.
Preserve Auto-Ack exclusion (`phase_e`, `failure_code`, critical /
`operator_review` exclusions). Never Auto-Ack these alerts.

### 6.5 Stale-state / races with executor finalization

Not only operator-versus-operator:

| Race | Expected behavior |
|------|-------------------|
| Operator vs operator (different actions) | First `FOR UPDATE` commit wins; loser `409 already_resolved` |
| Operator vs executor finalizer | Same lock/terminal rules: whichever commits first terminalizes; the other short-circuits (`already_finalized` in finalizer 193–210, or `409` in manual resolve) |
| Operator reads stale `provider_write_started`, finalizer commits before lock | Under lock, status is terminal → not entry gate → `409 already_resolved` |
| Finalizer sees manual success terminal | `already_finalized`; must **not** rewrite manual reason_code / external id |

---

## 7. State-transition and effects table (proposed E2-2)

| Action | From command | To command status | To provider_outcome | Resulting attempt | Original attempt | Alert | Audit |
|--------|--------------|-------------------|---------------------|-------------------|------------------|-------|-------|
| `ACKNOWLEDGE_EXTERNAL_SUCCESS` | `provider_write_started` | `succeeded` | `known_success` | `success` + external id; non-retryable; clear failure fields | unchanged | resolve if present | mandatory success event |
| (E2-1) `MARK_AMBIGUOUS` | `provider_write_started` | `ambiguous` | `ambiguous` | `operator_review`; non-retryable | unchanged | resolve if present | existing ambiguous event |
| `MARK_FAILED_CONFIRMED` | — | — | — | — | — | — | **not in scope** |

All included paths: command forever non-claimable / non-executable.

### 7.1 Field preserve / clear / set (success apply)

| Field | Preserve | Clear | Set |
|-------|----------|-------|-----|
| command.status | | | `succeeded` |
| command.provider_outcome | | | `known_success` |
| command.reason_code | | | `operator_ack_external_success` |
| command.finished_at / updated_at | | | now |
| command.lease_* / claimed_at / provider_write_started_at | preserve existing | | |
| attempt.status | | | `success` |
| attempt.external_post_id | | | request id |
| attempt.external_post_url | | | request url or null |
| attempt.failure_code / failure_category / error | | clear | |
| attempt.retryable / next_retry_at | | next_retry_at null | retryable false |
| attempt.finished_at | | | now |
| attempt.response | preserve (typically null at write-started) | | **do not invent** in minimal slice |
| original attempt / ContentItem / registry | preserve all | | |

---

## 8. Migration / model proposal (proposal only — do not create)

**Minimal E2-2 (preferred):** **no migration** if replay uses
`reason_code` + existing `platform_audit_logs` provenance (§6.2.1).

Existing command statuses / provider_outcome values already include
`succeeded` / `known_success` (`publish_retry_command.py` lines 18–53).

**If audit-lookup provenance is rejected during implementation authorization**,
propose (do not implement now):

1. Nullable columns on `publish_retry_commands` for last manual action +
   evidence hash / external_post_id snapshot, or
2. Append-only `publish_retry_command_resolutions` table

**If Alt B (post-ambiguous clarification) is later approved**, same overlay
options apply. **Not part of minimal E2-2.**

---

## 9. Acceptance matrix (proposed E2-2) + future test plan

Distinguish:

- **Verified existing:** E2-1 behavior already tested/landed.
- **Proposed:** requirements for a future E2-2 implementation (do not write
  or run tests in this documentation task).

### 9.1 Numbered acceptance criteria

| ID | Criterion | Kind |
|----|-----------|------|
| E2-2-A1 | Only `provider_write_started` (+ timestamp + lineage) accepts E2-2 success action | Proposed |
| E2-2-A2 | `pending` / `claimed` → `409 not_resolvable` | Proposed (mirror E2-1 verified) |
| E2-2-A3 | Terminal commands reject different actions with `409 already_resolved` | Proposed (E2-1 verified for ambiguous) |
| E2-2-A4 | Exact same-action compatible **manual** replay → `already_resolved` without audit spam; returns prior audit identity | Proposed |
| E2-2-A5 | Success requires `external_post_id` + reason + evidence_source + confirm | Proposed |
| E2-2-A6 | `MARK_FAILED_CONFIRMED` not exposed / rejected without mutation | Proposed (narrowed scope) |
| E2-2-A7 | Insufficient success evidence → `400`; no partial mutation | Proposed |
| E2-2-A8 | Contradictory external ids → `409 evidence_conflict` | Proposed |
| E2-2-A9 | Tenant isolation + role gate (`owner|manager|operator` or admin+tenant) | Proposed (E2-1 verified pattern) |
| E2-2-A10 | Lineage conflicts fail closed | Proposed (E2-1 verified pattern) |
| E2-2-A11 | Concurrent resolutions: one applied winner | Proposed (E2-1 verified pattern) |
| E2-2-A12 | Audit failure rolls back command/attempt/alert | Proposed (E2-1 verified pattern) |
| E2-2-A13 | No provider I/O / no URL fetch in resolution module | Proposed |
| E2-2-A14 | No replacement command creation; no claim/execution calls | Proposed |
| E2-2-A15 | Original command never returns to `pending`/`claimed` | Proposed |
| E2-2-A16 | ContentItem unchanged; publication registry unchanged (minimal); enablement blocked until follow-up/waiver (§3.4.4) | Proposed |
| E2-2-A17 | Stranded alert resolve + Auto-Ack exclusion preserved | Proposed |
| E2-2-A18 | E2-1 `MARK_AMBIGUOUS` remains behavior-compatible | Proposed compatibility |
| E2-2-A19 | `MARK_SAFE_TO_RETRY` / `KEEP_AMBIGUOUS` / cancel / no-effect / supersede / failed-confirm not exposed | Proposed deferrals |
| E2-2-A20 | Production flags remain disabled unless a separate enablement gate | Proposed |
| E2-2-A21 | Weak failure evidence (if failed endpoint accidentally called) rejected without mutation | Proposed |
| E2-2-A22 | Existing publication identity conflicting with any future failed action → conflict (documented); success path conflicts on mismatched ids | Proposed |
| E2-2-A23 | Executor-produced `succeeded`/`known_success` not misidentified as manual replay | Proposed |
| E2-2-A24 | Replay evidence differences (id/reason/source/url/observed_at) → conflict; missing provenance → fail closed | Proposed |
| E2-2-A25 | Operator-versus-finalizer races: first writer wins; no terminal rewrite | Proposed |
| E2-2-A26 | Downstream: document/test that claim/`retryable=false` ≠ system-wide duplicate prevention; success id participates in `find_live_success` | Proposed |
| E2-2-A27 | Feature-flag isolation: E2-2 flag independent of E2-1 flag (explicit coupling tests) | Proposed |
| E2-2-A28 | Post-ambiguous commands cannot be success-acked (`409`) | Proposed product limitation |

### 9.2 Future test plan (do not implement now)

1. Allowed source: success applied path only.
2. Prohibited sources: pending, claimed, each terminal including ambiguous.
3. Insufficient evidence matrix (missing id, empty reason/source, confirm false, URL-only, oversized id/url).
4. Weak failure / unsupported `MARK_FAILED_CONFIRMED` → 400, no mutation.
5. Existing attempt `external_post_id` mismatch → `409 evidence_conflict`.
6. Tenant mismatch / viewer / sales / admin without tenant_id.
7. Lineage: wrong `retry_command_id`, content/platform/account mismatch, missing attempt.
8. Compatible manual replay vs conflicting replay (id/reason/source/url/observed_at).
9. Seed executor-finalized success (`reason_code=provider_success`) → manual success request is not `already_resolved` replay (no fabricated manual audit).
10. Missing manual audit with manual-looking reason_code → fail closed.
11. Concurrent success vs ambiguous; operator vs finalizer race.
12. Audit raise → assert no durable command/attempt/alert change.
13. Static/import proofs: no provider client imports; no replacement factory calls; no registry upsert calls in resolution module.
14. Claim eligibility: terminal rows never selected.
15. Downstream: after success-ack, `find_live_success` sees resulting attempt; ContentItem/registry unchanged; original attempt unchanged.
16. Flag isolation: E2-1 enabled / E2-2 disabled rejects success action; reverse configuration documented.
17. Regression: existing E2-1 tests still pass unchanged in spirit.
18. Compose/config: both manual-resolution flags default false.

---

## 10. Unresolved questions

### 10.1 Implementation blockers (resolved for this local slice)

1. ~~Approval of Alternative A + narrowed scope~~ — selected for this task.
2. ~~Approval of separate E2-2 feature flag name/default/compose pin~~ — implemented dormant.
3. ~~Approval of audit-lookup replay provenance~~ — implemented fail-closed.
4. ~~Inventing attempt `response` JSON out of scope~~ — confirmed; not invented.
5. ~~Exact HTTP error for finalizer races~~ — `already_resolved` (no `stale_state`).

### 10.2 Enablement blockers (separate from implementation)

1. Publication-registry follow-up or signed product waiver (§3.4.4).
2. Production compose/env pins remain `false` until enablement gate.
3. Claim/execution/provider-write flags remain independently gated (NO-GO here).

### 10.3 Deferred / out-of-scope questions (not blockers for selected scope)

1. Post-ambiguous Alt B overlay design.
2. `MARK_FAILED_CONFIRMED` evidence taxonomy.
3. Formal E2-C8 acceptance artifact (applies to no-effect only).
4. Platform-specific `external_post_id` format strictness beyond length/opacity.
5. ContentItem aggregate repair policy.

---

## 11. GO / NO-GO gates

| Gate | Verdict |
|------|---------|
| Local Alternative A / success-only implementation | **GO for local dormant acceptance** when acceptance matrix evidence passes |
| Production enablement | **NO-GO** (also blocked on §3.4.4; no waiver) |
| Commit / push | **NOT AUTHORIZED** by the local implementation task |
| E3/E4 provider reads | **NO-GO** |
| E5 replacement commands | **NO-GO** |
| Claim / execution / real provider writes | **NO-GO** |
| Provider reads/writes, replacement creation | **NO-GO** |

---

## 12. Selected decisions + local implementation record

### 12.1 Selected decisions (authorized for this slice)

1. **Alternative A**, success-only: `ACKNOWLEDGE_EXTERNAL_SUCCESS` from
   `provider_write_started` only; never rewrite terminals / reopen commands.
2. **Separate flag** `PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED` default
   `false`, with production compose pin `:-false`. Independent of E2-1.
3. **Replay provenance:** `reason_code=operator_ack_external_success` + exactly
   one consistent authoritative `publishing.retry_cmd_recon_success` audit.
   Missing / duplicate / inconsistent / wrong-tenant provenance →
   `409 evidence_conflict`. Executor `provider_success` →
   `409 already_resolved` (not manual replay; no fabricated audit).
4. **Errors:** pending/claimed → `not_resolvable`; incompatible terminal /
   finalizer race → `already_resolved`; broken lifecycle/lineage →
   `lineage_conflict`; evidence mismatches → `evidence_conflict`. No
   `stale_state`.
5. **Data boundary:** mutate command + resulting attempt + mandatory audit +
   optional stranded alert only. Original attempt / ContentItem / registry /
   `attempt.response` unchanged. No provider I/O or URL fetch.

### 12.2 What was implemented

| Area | Change |
|------|--------|
| Config | `PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED: bool = False` |
| Compose | production pin `PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED:-false` |
| Schema / route | request accepts both actions + success evidence fields; response includes `external_post_id` |
| Service | same TX apply for success; write-started lifecycle validation; audit provenance replay; alert resolve; independent gates |
| Tests | `backend/tests/test_publish_retry_command_manual_resolution_e2_2.py` (+ E2-1 regression updates) |

### 12.3 Remaining enablement blockers

1. §3.4.4 registry / measurement / alternate-path review (no waiver).
2. Both manual-resolution flags must remain false until a separate enablement
   gate.
3. Claim / execution / provider-write flags remain independently gated (NO-GO).
4. Registry upsert alone is not sufficient proof of alternate-path safety;
   response-JSON consumers and dedup paths need separate verification.

### 12.4 Acceptance status note

Acceptance criteria in §9 are marked PASS/FAIL/NOT RUN only in the
implementation task final report, with corresponding test evidence. This
document does **not** mark criteria passed without that evidence.

### 12.5 Pre-commit correctness fixes (local / dormant)

Two review findings addressed before local acceptance (no commit/push,
no flag enablement, no provider I/O):

#### Finding 1 — Fail closed on contradictory audit provenance

**Defect:** `_load_authoritative_success_audit` filtered candidate rows by
`details` *before* uniqueness, so one valid row plus a contradictory sibling
for the same tenant/resource/event could authorize replay.

**Fix:** Query candidates by `tenant_id` + `resource_type` + `resource_id` +
manual-success `event_type` only. Require **exactly one** candidate, then
validate action / provenance / tenant / command / attempt ids and recorded
successful terminal outcome fields. Zero, multiple, malformed, or
inconsistent details → `409 evidence_conflict`. Other-tenant rows never
authorize replay (tenant scoping + explicit tenant consistency check).

**Regression coverage:**
- `test_valid_plus_contradictory_audit_candidate_fails_closed`
- `test_single_inconsistent_outcome_provenance_fails_closed`
- Existing `test_missing_manual_audit_*`, `test_duplicate_manual_audit_*`,
  `test_wrong_tenant_audit_*` (strengthened: rejected replay → no new audit /
  no command mutation)

#### Finding 2 — Require explicit JSON `true` for E2-2 confirmation

**Defect:** Schema used coercible `bool`; service `is True` cannot detect
`"true"` / `1` after Pydantic conversion.

**Fix:** Action-specific Pydantic v2 `model_validator(mode="before")` on
`PublishRetryCommandResolveRequest`: for `ACKNOWLEDGE_EXTERNAL_SUCCESS` the
raw confirmation value must be Python/`JSON` boolean `true`. E2-1
`MARK_AMBIGUOUS` keeps prior coercible-bool semantics.

**API status (documented):** FastAPI/Pydantic request validation → **422**
for E2-2 non-explicit confirmation. Service-level `False` (when reached) →
**400** (unchanged).

**Boundary coverage:**
- `test_e2_2_confirm_requires_explicit_json_true_at_schema_boundary`
- `test_e2_2_confirm_coercion_rejected_at_fastapi_boundary_returns_422`
- `test_e2_1_confirm_coercion_semantics_preserved`

#### Validation record (local isolated PostgreSQL `:54329`; no production access)

| Suite | Command | Result |
|-------|---------|--------|
| E2-2 | `cd backend; python -m pytest tests/test_publish_retry_command_manual_resolution_e2_2.py -q --tb=line` | **30 passed** (29.20s) |
| E2-1 regression | `cd backend; python -m pytest tests/test_publish_retry_command_manual_resolution_e2.py -q --tb=line` | **22 passed** (15.62s) |

Flags remain default `false` (`config.py` + compose `:-false`). No `.env`
changes. Commit/push / production enablement / provider I/O: **NOT AUTHORIZED**.

**STOP.** Local dormant implementation only. No production enablement.
