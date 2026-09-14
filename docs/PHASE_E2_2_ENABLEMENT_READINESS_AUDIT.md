# Phase E2-2 — Enablement Readiness Audit

**Status:** `FOLLOW-UP A + B IMPLEMENTED (LOCAL / DORMANT)` + `PRE-COMMIT TX BOUNDARY VERIFIED` / `ENABLEMENT NO-GO`

**Kind:** enablement readiness record updated after authorized Follow-up A
(success identity alignment), Follow-up B (local dormant write coordination),
and Follow-up B pre-commit transaction boundary verification.
**Does not:** authorize commit/push, registry implementation, production
deployment, flag enablement, claim/execution activation, or real provider I/O.

**Inspected / implementation baseline (local HEAD at start of Follow-up A/B):**
`2229bea692c1da9b589c19850aab58656b5c0d9e`
(`feat: add dormant manual retry success acknowledgment`)

**Applicable AGENTS.md:** only `mobile/AGENTS.md` (Expo docs pointer). No
docs-/backend-scoped `AGENTS.md` found for this phase.

**Related:**

- `docs/PHASE_E2_2_WRITE_COORDINATION_DESIGN.md` — Follow-up B decisions
- `docs/PHASE_E2_2_MANUAL_RESOLUTION_DESIGN.md` — landed minimal E2-2 contract
- `docs/PHASE_E2_MANUAL_RESOLUTION.md` — E2-1 `MARK_AMBIGUOUS`
- `backend/tests/test_e2_2_success_identity_publish_paths.py` — Follow-up A paths + updated C3
- `backend/tests/test_publish_write_coordination_e2_2.py` — Follow-up B path/concurrency + **TX boundary suite**

---

## 0. Verdict (evidence-based)

| Gate | Verdict |
|------|---------|
| Follow-up A local acceptance | **GO** |
| Follow-up B local acceptance (dormant) | **GO** |
| Pre-commit TX boundary verification | **GO** (matches established Meta early-commit contract; no fix required) |
| Commit/push | **NOT AUTHORIZED** |
| Registry implementation | **NOT AUTHORIZED** |
| Runtime deployment / E2-1 / E2-2 enablement | **NO-GO** |
| Provider reads/writes, replacement, claim/execution activation | **NO-GO** |

**Enablement readiness summary:** F1 reader inconsistency remains fixed locally.
Follow-up B adds dormant destination serialization + unresolved-write guard.
Same-intent duplicate starts are **prevented** when coordination is enabled;
already-in-flight adapter I/O is **rejected/deferred** on the ack side (`409
publication_in_progress`) and cannot be cancelled. Pre-commit TX verification
confirms early claim commit for non-Meta under coordination matches the
long-standing Meta early-commit caller contract — not a confirmed atomicity
regression. Registry/measurement (F2) and ContentItem non-repair (F3) remain
enablement blockers. Executor/barrier must join coordination before execution
enablement.

---

## 1. Follow-up A — implemented changes (retained)

### 1.1 Code

| File | Change |
|------|--------|
| `backend/app/services/publish_service.py` | `_prior_live_successes` recognizes durable `external_post_id` when `response` is absent; prefers column; conflict logs + suppress with column |
| `backend/tests/test_publish_retry_deduplication.py` | Column-only + conflict unit coverage |
| `backend/tests/test_publish_resilience.py` | Column-without-response unit coverage |
| `backend/tests/test_e2_2_success_identity_publish_paths.py` | Isolated PG path/concurrency suite |
| `docs/PHASE_E2_2_ENABLEMENT_READINESS_AUDIT.md` | This update |

### 1.2 Platform-keyed `_prior_live_successes` limitation (retained)

After ack on account A, `begin_attempt` / write-coordination correctly treat
account B as a new destination. `publish_content` may still platform-key skip
account B via `_prior_live_successes`. **Not redesigned in Follow-up B.**

---

## 2. Follow-up B — implemented changes (local / dormant)

| File | Change |
|------|--------|
| `backend/app/services/publish_write_coordination.py` | **New** shared destination identity, SHA-256 advisory keys, xact lock, unresolved + in_progress queries |
| `backend/app/services/publish_resilience.py` | `begin_attempt` optional `tenant_id`; when flag on: lock → unresolved guard → existing checks → claim; cross-version in_progress skip |
| `backend/app/services/publish_service.py` | Passes `tenant_id`; when coordination on, early-commits claim for **all** platforms before adapter I/O |
| `backend/app/services/publish_retry_command_manual_resolution_service.py` | E2-2 requires E2_2 **and** WRITE_COORDINATION; destination lock before mutate; `409 publication_in_progress` if competing in_progress |
| `backend/app/core/config.py` | `PUBLISH_WRITE_COORDINATION_ENABLED: bool = False` |
| `docker-compose.production.yml` | `PUBLISH_WRITE_COORDINATION_ENABLED:-false` pin only |
| `backend/tests/test_publish_write_coordination_e2_2.py` | **New** coordination suite + TX boundary verification |
| `backend/tests/test_e2_2_success_identity_publish_paths.py` | C3 updated (enabled + disabled-mode evidence) |
| `docs/PHASE_E2_2_WRITE_COORDINATION_DESIGN.md` | Implemented decisions |

**Not changed:** executor activation, replacement commands, registry, ContentItem
repair, environment files, flag defaults to true.

### 2.1 Flag dependency truth table

| E2_2 | WRITE_COORD | begin_attempt coordination | E2-2 ack | E2-1 ambiguous |
|------|-------------|----------------------------|----------|----------------|
| false | false | off (legacy) | 403 | independent |
| true | false | off (legacy) | 403 (coord required) | independent |
| true | true | on | allowed (entry rules) | independent |
| false | true | on | 403 (E2-2 off) | independent |

---

## 3. Concurrency / path evidence (Follow-up B)

Isolated PG `:54329` / db `e2_2_write_coordination_test` (+ path db). Fake
adapters only. Separate sessions + asyncio barriers. No sleep-based proofs.

| Scenario | Adapter invokes | Notes |
|----------|-----------------|-------|
| Coordination disabled + stranded | **1** | Legacy behavior preserved |
| Unresolved `provider_write_started` + coord on | **0** | `unresolved_prior_write`, no synthetic retry |
| Ambiguous terminal + coord on | **0** | Fail closed, no auto-retry |
| Cross-version unresolved | **0** | Destination-level |
| Different account | **1** | Legitimate new intent |
| Ack before publish | **0** | Deduped |
| Overlapping: publish waits pre-claim; ack first | **0** | |
| Durable in_progress then ack (C3 enabled) | N/A (ack) | **409** `publication_in_progress`, no audit/mutation |
| Two ordinary same-intent | first **1**, second **0** | |
| Lock during fake provider | — | `pg_try_advisory_xact_lock` succeeds on peer session |
| Rollback | — | Lock released; claim not durable |
| E2-1 with coord off | — | Ambiguous still applies |
| Pre-barrier `claimed` | **1** | Excluded while execution disabled |

**Prevented vs unavoidable:** new claims/acks that race before provider entry are
prevented or rejected. Already-started provider I/O cannot be cancelled — ack
defers with 409 when a committed `in_progress` is visible.

**Do not treat helper-only tests as full publish-path proof.** Path rows use
`PublishService.publish_content` / resolution service with counting fakes.

---

## 3A. Pre-commit transaction boundary verification (Follow-up B)

**Disposition:** current behavior **matches the established caller contract**
(Meta always early-committed; coordination extends that to all platforms when
enabled). **No transaction redesign and no production code change** in this
verification pass. Confirmed: not a concrete atomicity/cleanup regression.

### 3A.1 Caller / session ownership (file/line evidence)

| Caller | Session owner | Pending before `publish_content` | Notes |
|--------|---------------|----------------------------------|-------|
| API `POST …/publish` | `get_db` request session (`database.py` 118–125) | None (clean session) | `content.py` 134–150 |
| `PublishAttemptOpsService.manual_retry` | Caller-supplied session | Clears `next_retry_at`; may set `retrying→failed` + `flush` (199–204) then calls `publish_content` (206–215) | Real pending mutations tested |
| `PublishingQueueService.retry_publish` | Caller-supplied session | May set `failed/partial_failed→scheduled` + `flush` (284–286) | Same session |
| Scheduler due item | Fresh `AsyncSessionLocal` after `_try_claim` already **committed** `scheduled→publishing` (167–185, 240–262) | No open pending claim on content status | `from_scheduler=True` skips re-set publishing |
| Scheduler due retries | Fresh session per content (95–116) | None beyond loads | wraps `publish_content` |
| Calendar `mark_published` | Caller session | None beyond loads | `content_service.py` 790 |

**Inside `PublishService.publish_content` (shared):**

- Sets `item.status = "publishing"` + `flush` when not test / not scheduler
  (`publish_service.py` 855–857).
- Per destination: `begin_attempt` (935–944) → optional early `db.commit()`
  (962–967) when Meta **or** `write_coordination_enabled()` → adapter I/O →
  `_record_attempt` / finalize → final `db.commit()` (1155).
- On unexpected exception: `db.rollback()` (1177 / 1182) — only undoes the
  **post**-early-commit transaction; early-committed claim stays durable
  (same as historical Meta path).
- `begin_attempt` is solely called from `publish_content` (design + grep).

**What early commit makes durable (coordination on, non-Meta):** the
`in_progress` claim row, any prior destination finalizations already in the
session, `ContentItem.status=publishing` (when ORM-tracked), and real caller
pending rows still attached to the session (e.g. manual_retry’s
`next_retry_at` clear). Advisory xact locks release on that commit before
provider I/O.

**Caller rollback expectation:** callers do **not** rely on rolling back
early-committed claim / manual-retry supersede after a later failure — Meta
platforms already established that contract. Coordination-off Telegram still
defers commit until the end (legacy).

### 3A.2 Boundary tests (isolated PG + fake providers)

| Boundary | Durable outcome | Lock | Adapters |
|----------|-----------------|------|----------|
| Manual retry pending mutations before non-Meta publish (coord on) | Original `retrying`→`failed` + `next_retry_at` cleared **visible mid-I/O**; new claim `in_progress` mid-I/O; final success | Free during I/O | tg **1** |
| Provider exception after durable claim | Claim finalized (not left `in_progress`); result `success=False` | Free during I/O + after | tg **1** |
| First destination success, second fails | Telegram success durable; Facebook terminal non-`in_progress`; no leftover inflight | Both free after | tg **1**, fb **1** |
| Coordination-denied then eligible | Telegram `unresolved_prior_write`; Facebook success; **denied destination lock free during FB I/O** | Free | tg **0**, fb **1** |
| Every destination denied | Both unresolved codes; no `in_progress`; locks free after request cleanup | Free | **0** / **0** |
| Caller rollback after publish failure (finalize boom) | Early-committed `in_progress` **survives** session rollback | Free after | tg **1** |
| Coordination disabled | Mid-I/O: original still `retrying` with `next_retry_at`; claim **not** durable; rollback restores legacy | N/A (no xact lock) | tg **1** |

### 3A.3 Remaining TX limitations (not defects vs contract)

1. Early commit commits the **entire** shared session transaction (by design,
   same as Meta) — not a flush-only claim.
2. Non-Meta interrupt recovery in `finally` still special-cases Meta
   `in_progress` only (`publish_service.py` 1196–1206); stranded non-Meta
   `in_progress` after crash remains fail-closed via coordination /
   stale recovery — intentional durability, not silent auto-republish.
3. Denied/skip branches hold destination xact locks until the next
   early-commit or final request commit; verified **not** held across a
   subsequent provider invocation.

---

## 4. Test evidence

| Suite | Command | Result |
|-------|---------|--------|
| Follow-up B + A paths + E2-2/E2-1 + reader units + **TX boundaries** | `cd backend; python -m pytest tests/test_publish_write_coordination_e2_2.py tests/test_e2_2_success_identity_publish_paths.py tests/test_publish_retry_command_manual_resolution_e2_2.py tests/test_publish_retry_command_manual_resolution_e2.py tests/test_publish_retry_deduplication.py tests/test_publish_resilience.py::test_prior_live_successes_ignore_mock_and_test_attempts tests/test_publish_resilience.py::test_prior_live_successes_recognize_column_without_response -q --tb=line` | **93 passed** (~43s) |
| TX boundary subset only | `… -k "manual_retry_pending or provider_exception_after or second_destination or denied_then_eligible or all_destinations_skipped or caller_rollback or coordination_disabled_non_meta"` | **7 passed** |
| Production / staging / real providers | — | **NOT RUN** (not authorized) |

Flags remain default `false`. No `.env` changes.

---

## 5. Findings status

| ID | After Follow-up A | After Follow-up B | After TX verification |
|----|-------------------|-------------------|------------------------|
| **F1** column reader | Fixed locally | Retained | Retained |
| **F2** registry / measurement | Blocking | **Still blocking** | **Still blocking** |
| **F3** ContentItem unrepaired | Open | **Still open** | **Still open** |
| **F4** Ack vs publish concurrency | C3 residual | **Addressed locally (dormant)** | Retained |
| **F5** Registry ≠ publish safety | Binding | **Still binding** | **Still binding** |
| **F6** Executor second writer | Latent | **Documented prerequisite** | Retained |
| **F7** Platform-keyed prior map | Documented | **Retained limitation** | Retained |
| **F8** Pre-commit TX surface | — | Open verification concern | **Closed — contract match; no fix** |

---

## 6. Remaining blockers

1. Registry / measurement (F2).
2. ContentItem non-repair (F3).
3. Platform-keyed `_prior_live_successes` false suppression of other accounts.
4. Executor/barrier must participate in write coordination before execution on.
5. Production image/env / real providers — NO-GO.
6. Commit/push not authorized for this task.

---

## 7. Gates (binding)

- **Local Follow-up A + B acceptance:** **GO** (dormant; evidence above).
- **Pre-commit TX boundary verification:** **GO** (contract match; no code fix).
- **Scoped dormant commit readiness (Follow-up A/B):** **READY when authorized** — local evidence complete; this task does **not** authorize commit/push.
- **Commit/push:** **NOT AUTHORIZED**.
- **Registry implementation:** **NOT AUTHORIZED**.
- **Production deployment / enablement:** **NO-GO**.
- **Real provider I/O, replacement creation, claim/execution activation:** **NO-GO**.

**STOP.**
