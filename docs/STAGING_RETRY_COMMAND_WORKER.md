# Staging retry-command fake worker (D2-B2b1-A + B2b1-B + B2b2-0B+0C)

Long-running worker path for:

`claim → prepare → [pre-barrier stop?] → barrier → fake provider ×1 → finalize`

**Staging only.** Requires verified identity before any claim. **No** real providers.

One-shot harness remains available: see `docs/STAGING_RETRY_COMMAND_HARNESS.md`.

## Hard identity (all must hold before claim)

1. `APP_ENV=staging` (exactly)
2. `PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=fake`
3. `PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED=true`
4. Authoritative: `SELECT current_database()` → `china_smm_os_staging`
5. Database name is **not** production denylist `china_smm_os`
6. `TELEGRAM_BOT_TOKEN` and `META_APP_SECRET` empty
7. `PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE=1`

## Entrypoint dispatch

- `backend=none` → D2-B1 safe pre-executor stop (`execution=None`)
- `backend=fake` → `bootstrap_staging_fake_worker_execution` **first**; worker starts only after success
- real / unknown → `SystemExit(2)`

Resolver classifies `fake` as requested; it does **not** approve it.

## Graceful shutdown (B2b1-B)

SIGINT ≡ SIGTERM → `worker.request_stop()` (sets Event only; **never** `task.cancel()`).

| Phase | Behavior |
|-------|----------|
| Idle / between commands | exit loop; exit code **0** |
| After claim, before executor | leave lease; no executor; exit **0** |
| Pre-barrier (after prepare) | `should_stop_before_barrier` → outcome `stopped_before_barrier`; no barrier/provider/finalizer; exit **0** (no hard exit) |
| Final pre-barrier check returned false | **drain territory** — SIGTERM must not cancel; await barrier + provider + finalizer |
| Post-barrier | ignore stop for current command; drain provider+finalizer once; then exit; no next claim |
| Drain timeout (drain territory only) | **`os._exit(3)`** — abrupt process death; **no** `asyncio.run` cleanup cancellation; **no** replay/reset; DB left as-is (Phase E later) |
| Bootstrap identity failure | exit code **2** |

Drain bound: `PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS` (default **60**). Applies only after the executor enters drain territory (final pre-barrier stop check returned false / `cross_barrier` in progress or later).

Implementation notes:

* `await wait_for(shield(active_executor_task), drain_seconds)` only after stop while in drain territory. Shield prevents `wait_for` from cancelling the executor.
* Returning `SystemExit(3)` through `asyncio.run` is **unsafe**: `Runner.close` → `_cancel_all_tasks` would still deliver `CancelledError` into the pending provider/finalizer. Post-barrier drain timeout therefore uses `os._exit(3)` after flushing log handlers only (non-authoritative diagnostics). Correctness relies on durable DB state, not Python cleanup.
* Pre-barrier stop never uses `os._exit`.

### Process exit codes

| Code | Meaning |
|------|---------|
| 0 | graceful idle stop / pre-barrier stop / successful post-barrier drain |
| 2 | bootstrap / backend refusal |
| 3 | post-barrier drain timeout (`os._exit`; staging fake worker only) |
| 4 | unexpected worker invariant failure |

## Staging lifecycle coordination (B2b2-0B+0C)

`StagingLifecycleCoordinator` is constructed **only** after verified staging bootstrap.

| Setting | Role |
|---------|------|
| `PUBLISH_RETRY_COMMAND_STAGING_EVIDENCE_ROOT` | Mounted root (default compose: `/var/lib/retry-command-staging`) |
| `PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR` | Durable markers (`…/markers/<campaign_id>/<point>`) |
| `PUBLISH_RETRY_COMMAND_STAGING_CONTROL_DIR` | Release files (`…/control/<campaign_id>/release_<point>`) |
| `PUBLISH_RETRY_COMMAND_STAGING_HOLD_POINT` | Optional single hold point (independent of fake outcome mode) |
| `PUBLISH_RETRY_COMMAND_STAGING_HOLD_TIMEOUT_SECONDS` | Optional hold timeout (≤0 = wait until release / external kill) |
| `PUBLISH_RETRY_COMMAND_STAGING_CAMPAIGN_ID` | Observability / stale-release isolation (not a security authority) |

Allowed points: `after_prepare`, `after_barrier`, `before_provider`, `provider_entered`, `after_provider`, `before_finalize`.

Marker durability: write temp → flush → `os.fsync` → close → `os.replace` → fsync parent directory.

Hold semantics: emit durable marker → async poll for campaign-scoped release file → consume once → continue. Hold itself mutates no DB rows and does not authorize provider replay.

`provider_entered` ordering inside fake `execute`:

1. sink `fake_invoke` durable append (invocation started)
2. `provider_entered` marker (+ optional hold)
3. modeled fake effect/result

Fake outcome mode (`success` / `ambiguous` / …) stays separate from hold point.

`backend=none` and production defaults ignore all coordination settings. Claim / Preparation / Barrier / Finalization services do not import the coordinator.

Hold/release campaign (no SIGKILL):

```bash
python backend/scripts/run_staging_retry_command_hold_release_campaign.py \
  --hold-point after_barrier --campaign-id demo
```

## Marker hooks (SIGTERM campaigns)

Bootstrap injects DI `ExecutorHooks` from the coordinator **after** verified identity. External runner: wait for campaign-scoped marker → `docker kill -s SIGTERM` (B2b1) or write `release_<point>` (0B+0C).

No `os.getenv("FAILPOINT")` inside prep/barrier/finalizer/executor.

## Compose skeleton

```bash
docker compose -f docker-compose.staging.yml --env-file .env.staging.example \
  --profile retry-command up --build
```

Project: `china-smm-os-staging`. Services: staging Postgres + profile-gated retry-command worker (`restart: "no"`). Evidence volume: `china-smm-os-staging-evidence` → `/var/lib/retry-command-staging`. No production volume, Cloudflare, API, frontend, or webhook worker.

Lifecycle campaign helper (local SIGTERM):

```bash
python backend/scripts/run_staging_retry_command_lifecycle_campaign.py --help
```

## Env contract

See `.env.staging.example`. Do not fall back to `.env.production`.

`PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH` is staging observation only. Setting it alone cannot enable fake execution; production `backend=none` ignores it.
