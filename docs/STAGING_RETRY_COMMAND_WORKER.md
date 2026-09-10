# Staging retry-command fake worker (D2-B2b1-A + B2b1-B)

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
| Pre-barrier (after prepare) | `should_stop_before_barrier` → outcome `stopped_before_barrier`; no barrier/provider/finalizer; exit **0** |
| Post-barrier | ignore stop for current command; drain provider+finalizer once; then exit; no next claim |
| Drain timeout | exit code **3**; **no** replay/reset/ambiguous-from-timeout; DB left as-is (Phase E later) |
| Bootstrap identity failure | exit code **2** |

Drain bound: `PUBLISH_RETRY_COMMAND_WORKER_DRAIN_SECONDS` (default **60**).

Implementation: `await wait_for(shield(active_executor_task), drain_seconds)` only after stop while in-flight. Shield prevents `wait_for` from cancelling a post-barrier executor.

### Process exit codes

| Code | Meaning |
|------|---------|
| 0 | graceful idle stop / pre-barrier stop / successful post-barrier drain |
| 2 | bootstrap / backend refusal |
| 3 | drain timeout |
| 4 | unexpected worker invariant failure |

## Marker hooks (SIGTERM campaigns)

Optional `PUBLISH_RETRY_COMMAND_STAGING_MARKER_DIR` — bootstrap injects DI `ExecutorHooks` **after** verified identity. External runner: wait for `after_prepare` / `after_barrier` file → `docker kill -s SIGTERM`.

No `os.getenv("FAILPOINT")` inside prep/barrier/finalizer/executor.

## Compose skeleton

```bash
docker compose -f docker-compose.staging.yml --env-file .env.staging.example \
  --profile retry-command up --build
```

Project: `china-smm-os-staging`. Services: staging Postgres + profile-gated retry-command worker (`restart: "no"`). No production volume, Cloudflare, API, frontend, or webhook worker.

Lifecycle campaign helper (local):

```bash
python backend/scripts/run_staging_retry_command_lifecycle_campaign.py --help
```

## Env contract

See `.env.staging.example`. Do not fall back to `.env.production`.

`PUBLISH_RETRY_COMMAND_FAKE_SINK_PATH` is staging observation only. Setting it alone cannot enable fake execution; production `backend=none` ignores it.
