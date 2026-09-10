# Staging retry-command fake worker bootstrap (D2-B2b1-A)

Long-running worker path for:

`claim → prepare → barrier → fake provider ×1 → finalize`

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

## Compose skeleton

```bash
docker compose -f docker-compose.staging.yml --env-file .env.staging.example \
  --profile retry-command up --build
```

Project: `china-smm-os-staging`. Services: staging Postgres + profile-gated retry-command worker (`restart: "no"`). No production volume, Cloudflare, API, frontend, or webhook worker.

## Env contract

See `.env.staging.example`. Do not fall back to `.env.production`.

## SIGTERM note (B2b1-A)

`request_stop()` sets a stop event only. It does **not** cancel an already-running executor. In-flight prepare/barrier/provider/finalize continues to completion; new claims/orchestration starts are blocked. B2b1-B owns stronger drain semantics.
