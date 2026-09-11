# China SMM OS Production Runbook

This runbook deploys the existing named Cloudflare Tunnel with production-built containers. It does not change Cloudflare DNS or purchase infrastructure.

## Safety boundary

- Development remains on `docker-compose.yml`.
- Production stack definition lives in `docker-compose.production.yml`.
- **Backend recreate must use the canonical helper** (or both compose files below).
- Canonical production compose **hard-pins** backend `SCHEDULED_PUBLISH_ENABLED=false`.
  Turning scheduled publishing ON requires a separate deliberate override design
  (not shipped). Do not enable it via `.env.production` alone.
- `cutover-safe.yml` is **defense in depth** (also pins scheduled publish / automation /
  health-snapshot false). It is not the sole safety control, but deploy tooling
  still requires it so single-file recreates stay discouraged.
- PostgreSQL, backend, and frontend do not publish host ports in production.
- Cloudflare Tunnel is the only public ingress.
- R2 is the only production media store.
- Never commit `.env.production`.
- Keep retry-command worker profile unselected and all retry-command flags false.

### DO NOT recreate backend with production compose alone

**Unsafe / forbidden for backend recreate:**

```bash
# FOOTGUN — do not use for backend recreate
docker compose --env-file .env.production -f docker-compose.production.yml \
  up -d --no-deps --force-recreate backend
```

Even though canonical production compose now fail-closes scheduled publishing,
operators must still use the helper (or both files) so cutover-safe defense-in-depth
and pre/post hard gates run.

## One-time preparation

1. Run `powershell -ExecutionPolicy Bypass -File scripts/prepare-production-env.ps1`
   to copy the existing integration credentials and generate independent secrets.
2. Alternatively copy `.env.production.example` to `.env.production` and replace every placeholder.
3. URL-encode the PostgreSQL password inside `DATABASE_URL`.
4. Confirm `SCHEDULED_PUBLISH_ENABLED=false` in `.env.production` (defense in depth;
   compose already hard-pins false for backend).
5. In the named Cloudflare Tunnel configure:
   - `app.chinasmmos.com` -> `http://frontend:3000`
   - `api.chinasmmos.com` -> `http://backend:8000`
6. Keep `media.chinasmmos.com` attached to the R2 bucket, not to the tunnel.

## Validate without starting anything

Prefer validating the same file pair the deploy helper uses:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml -f cutover-safe.yml config --quiet
```

The env file is used for Compose interpolation only. Secrets are explicitly
assigned per service; the Cloudflare token and PostgreSQL password are not
injected into application containers.

## Backup and migrate

Take a database backup before every migration. Then run:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml -f cutover-safe.yml \
  --profile tools run --rm migrate
```

## Start production (full stack)

Initial bring-up of the full stack (not a routine backend-only recreate):

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml -f cutover-safe.yml up -d --build
docker compose --env-file .env.production \
  -f docker-compose.production.yml -f cutover-safe.yml ps
```

## Backend-only recreate (canonical)

Routine production backend recreates **must** use:

```bash
./ops/deploy-backend-production.sh
```

The helper:

- uses `docker-compose.production.yml` **and** `cutover-safe.yml`
- uses `.env.production`
- recreates **backend only** (`--no-deps --force-recreate`)
- does **not** select the `retry-command` profile
- **hard-fails** unless resolved compose has:
  - `SCHEDULED_PUBLISH_ENABLED=false`
  - all `PUBLISH_RETRY_COMMAND_*` gates false / backend `none`
- **hard-fails** after recreate unless runtime matches (container env, `/health=200`,
  retry worker absent)

If you cannot run the helper, the equivalent manual pair is:

```bash
docker compose --env-file .env.production \
  -f docker-compose.production.yml -f cutover-safe.yml \
  up -d --no-deps --force-recreate backend
```

…but you must still perform the same preflight/postflight gates the script enforces.

## Smoke checks

- `https://api.chinasmmos.com/health` returns HTTP 200.
- `https://app.chinasmmos.com/login` loads without mixed-content errors.
- Tenant and admin authentication both work.
- A client review link opens from outside the host computer.
- One approved test item completes through the scheduler exactly once.

Run the repeatable health audit:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/production-health.ps1
```

Create and validate a production database backup:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/backup-production.ps1
```

## Publishing resilience recovery

Transient Facebook/Instagram/Telegram publish failures are classified and retried
automatically with bounded exponential backoff (`PUBLISH_MAX_ATTEMPTS`,
`PUBLISH_RETRY_BASE_SECONDS`, `PUBLISH_RETRY_MAX_SECONDS`). Meta `Retry-After`
is respected when present.

Do **not** expect automatic retries for authentication, permission, validation,
or unsupported-media failures — those are terminal and need operator action.

Meta write timeouts and connection errors are treated as **ambiguous** (provider
may have accepted the post). Those attempts go to `operator_review` and are
**not** auto-retried.

### Operator checklist

1. Open **Publishing → Queue** (or content Publish history) and check attempt
   badges: `retrying`, `operator_review`, `exhausted`, `in_progress`, `failed`.
2. For `retrying`, wait for `next_retry_at` or use guarded **Retry**.
3. For `operator_review` (Meta timeout, connection loss, or stale in-progress):
   - Confirm in Meta Business Suite whether a live post already exists.
   - Only then use **Retry** — the UI asks for confirmation to avoid duplicates.
4. For `exhausted`: fix the underlying issue (token, media, permissions), then Retry.
5. Already-published destinations are blocked from creating a second external post
   (idempotency key + live `external_post_id` check).

### Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| Stuck `publishing` / `in_progress` | Worker restart mid-publish | Wait for stale recovery (`PUBLISH_STALE_ATTEMPT_MINUTES`) or cancel/recover from queue |
| Meta `operator_review` | Ambiguous timeout / connection / stale claim | Verify live post; retry only if absent |
| Repeated `rate_limited` | Meta throttling | Let backoff run; raise base/max seconds only if needed |
| Auth/permission failures | Expired token / missing scopes | Reconnect Meta; do not force duplicate publishes |
| Duplicate approval/webhook | Same content approved twice | Dedup suppresses second live post |

### Meta OAuth scopes (publish + Listening)

Default `META_OAUTH_SCOPES` includes the minimum set for publishing and Facebook
Listening read sources:

`pages_show_list`, `pages_read_engagement`, `pages_read_user_content`,
`instagram_basic`, `business_management`, `pages_manage_posts`,
`instagram_content_publish`.

**Existing Meta connections do not gain new permissions automatically.** After
deploying scope changes, each tenant must re-authorize Meta OAuth before
Facebook Listening (`facebook_page_comments` / `facebook_page_mentions`) will
pass capability checks. Publishing with previously granted publish scopes
continues to work until reconnect.

API (authenticated, tenant-scoped):

- `GET /api/v1/publishing/attempts?status=retrying|failed|operator_review|exhausted|in_progress`
- `POST /api/v1/publishing/attempts/{id}/retry`
- `GET /api/v1/publishing/alerts` — deduplicated operator alerts (`state`, `severity`, `platform`, `client_id` filters)
- `GET /api/v1/publishing/alerts/counts` — open critical/warning counts
- `POST /api/v1/publishing/alerts/{id}/acknowledge`
- `POST /api/v1/publishing/alerts/{id}/resolve` — optional `{ "note": "..." }`

### Publish operator alerts

Publishing failures and recoveries create **deduplicated** tenant-scoped alerts
(`publish_operator_alerts`) so operators do not need to poll the queue.

Events: `operator_review`, `exhausted`, `terminal_failure`, `stale_in_progress`,
`recovery`, `repeated_failure`. Open failure alerts for a destination auto-resolve
when that same content/platform/account publishes successfully.

Outbound Telegram/email delivery is **disabled by default**. Enable only after
migration `20260923_publish_alert_telegram_delivery` is applied, in-app alerts
are verified, and a tenant-admin has configured an **explicit numeric chat ID
allowlist** (never client intake groups or publish channels):

| Variable | Default | Purpose |
|---|---|---|
| `PUBLISH_ALERT_REPEATED_FAILURE_THRESHOLD` | `3` | Failures on a destination before `repeated_failure` |
| `PUBLISH_ALERT_REPEATED_FAILURE_WINDOW_MINUTES` | `60` | Sliding window for the threshold |
| `PUBLISH_ALERT_TELEGRAM_ENABLED` | `false` | **Master kill switch** for Telegram outbox enqueue + send |
| `PUBLISH_ALERT_EMAIL_ENABLED` | `false` | Opt-in email stub (no SMTP yet — stays no-op) |
| `PUBLISH_ALERT_DELIVERY_COOLDOWN_SECONDS` | `300` | Min gap between outbound orchestration per alert |
| `PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED` | `false` | Run the durable Telegram delivery worker |
| `PUBLISH_ALERT_TELEGRAM_WORKER_POLL_SECONDS` | `5` | Worker poll interval |
| `PUBLISH_ALERT_TELEGRAM_WORKER_BATCH_SIZE` | `10` | Max outbox rows claimed per tick |
| `PUBLISH_ALERT_TELEGRAM_MAX_ATTEMPTS` | `8` | Max send attempts per delivery |
| `PUBLISH_ALERT_TELEGRAM_RETRY_BASE_SECONDS` | `30` | Exponential backoff base |
| `PUBLISH_ALERT_TELEGRAM_RETRY_MAX_SECONDS` | `3600` | Backoff cap (also respects Telegram retry-after) |
| `PUBLISH_ALERT_TELEGRAM_LEASE_SECONDS` | `120` | Claim lease for concurrent workers |
| `PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED` | `false` | Global gate for recovery messages (tenant flag also required) |
| `PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED` | `false` | Allow tenant owners to mint Connect Telegram deep links |
| `PUBLISH_ALERT_TELEGRAM_ENROLLMENT_TOKEN_TTL_SECONDS` | `600` | Enrollment token TTL (clamped 60–1800) |
| `PUBLISH_ALERT_TELEGRAM_ENROLLMENT_POLL_SECONDS` | `3` | UI poll interval while waiting for `/start` |
| `PUBLISH_RETRY_COMMANDS_ENABLED` | `false` | Durable retry-command create/get subsystem gate (3C.1B) |
| `PUBLISH_RETRY_COMMAND_WORKER_ENABLED` | `false` | Claim/orchestration worker process loop (idles when false) |
| `PUBLISH_RETRY_COMMAND_CLAIM_ENABLED` | `false` | Permit pending→claimed / stale claimed reclaim mutations |
| `PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED` | `false` | Preparation + barrier + executor gate (keep false) |
| `PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND` | `none` | D2-B1/B2a: only `none` is worker-runnable. Missing → `none`. `fake` is staging-harness-only (D2-B2a), not worker-executable. |
| `PUBLISH_RETRY_COMMAND_FAKE_EXECUTION_ALLOWED` | `false` | Explicit ack required (with APP_ENV=staging + china_smm_os_staging) before staging harness may resolve fake |
| `PUBLISH_RETRY_COMMAND_FAKE_OUTCOME_MODE` | `success` | Staging CLI/harness fake outcome mode only |
| `PUBLISH_RETRY_COMMAND_WORKER_POLL_SECONDS` | `5` | Worker poll interval |
| `PUBLISH_RETRY_COMMAND_WORKER_BATCH_SIZE` | `1` | Max commands claimed/reclaimed per tick (capped at 5) |
| `PUBLISH_RETRY_COMMAND_LEASE_SECONDS` | `180` | Claim lease duration (DB clock; clamped 30–3600) |
| `PUBLISH_ALERT_TELEGRAM_MAX_CONFIRMED_RECIPIENTS` | `1` | Max confirmed operator recipients per tenant |
| `TELEGRAM_BOT_USERNAME` | *(empty)* | Public bot username for deep links (validated; `getMe` fallback) |
| `PUBLISH_ALERT_APP_BASE_URL` | `https://app.chinasmmos.com` | Deep-link origin in Telegram messages |

**Retry-command worker (3C.1C-D2-B1):** Compose service `publish-retry-command-worker` is
profile-gated (`profiles: [retry-command]`). Normal `docker compose up -d` does **not**
instantiate it; start only with an explicit profile (e.g. `--profile retry-command`).
Even when profile-started, the process idles when `PUBLISH_RETRY_COMMAND_WORKER_ENABLED=false`
(default). Claim/reclaim requires **all** of `PUBLISH_RETRY_COMMANDS_ENABLED`,
`PUBLISH_RETRY_COMMAND_WORKER_ENABLED`, and `PUBLISH_RETRY_COMMAND_CLAIM_ENABLED`.
`PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND` defaults to `none`: after claim the worker records
observation/metrics and **stops** before Preparation / Barrier / provider / Finalizer.
If WORKER=true and backend ≠ `none`, startup exits non-zero (fail closed). Real provider
execution remains unimplemented (F1/F2/F3). Prefer keeping the profile unselected and all
flags false until staged claim observation is intentional.

**Enrollment vs delivery:** Enabling enrollment (`PUBLISH_ALERT_TELEGRAM_ENROLLMENT_ENABLED=true`)
only lets an authenticated tenant owner generate a short-lived Connect Telegram deep link
and confirm a private-chat candidate after `/start`. It does **not** enable alert delivery,
does not create outbox rows, and does not use `TELEGRAM_ADMIN_ID` / client intake groups /
publishing destinations as recipients. Keep delivery kill switches false until a recipient
is confirmed and outbound send is intentionally approved:

- `PUBLISH_ALERT_TELEGRAM_ENABLED=false`
- `PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED=false`
- `PUBLISH_ALERT_TELEGRAM_RECOVERY_ENABLED=false`

Migration `20260924_telegram_operator_enrollment` creates `publish_alert_telegram_enrollments`
(hash-only tokens, single-use consume, private-chat only). Webhook handling lives in
`telegram-webhook-worker` (same bot webhook path); the delivery worker stays idle while its
flag is false.

Telegram delivery uses a durable outbox (`publish_alert_telegram_deliveries`) with
dedupe keys so worker restarts cannot double-send. Recipients come only from
`tenant_publish_alert_telegram_settings` (numeric chat ID + allowlist). The shared
`TELEGRAM_BOT_TOKEN` is used to send; `TELEGRAM_ADMIN_ID` is **not** used as the
operator-alert destination.

Failed alert delivery never blocks publishing or creates social posts.

UI: **Publishing → Alerts** (`/publishing/alerts`) — in-app inbox plus separate
Telegram delivery settings / Connect Telegram enrollment / recent outbox attempts.

API (tenant owner/manager for mutating Telegram settings):

- `GET/PUT /api/v1/publishing/alerts/telegram-settings`
- `POST/GET /api/v1/publishing/alerts/telegram-enrollment` (+ revoke/confirm/reject)
- `GET /api/v1/publishing/alerts/telegram-recipients` (+ remove)
- `GET /api/v1/publishing/alerts/telegram-deliveries`
- `POST /api/v1/publishing/alerts/telegram-deliveries/{id}/cancel`
- `POST /api/v1/publishing/alerts/telegram-deliveries/{id}/retry`
- `POST /api/v1/publishing/alerts/telegram-deliveries/test` — requires `confirm=true`;
  refused while the global kill switch is false

Compose service `publish-alert-telegram-worker` runs
`python scripts/run_publish_alert_telegram_worker.py` and **idles** while
`PUBLISH_ALERT_TELEGRAM_WORKER_ENABLED=false` (no claims, no Telegram API calls).
Enable the worker flag only after tenant recipients are configured and the global
kill switch is intentionally turned on.

Never enable live Meta smoke flags unless intentionally publishing for real.

## Rollback

Do not delete volumes. Redeploy the last known-good image/commit, then recreate via
`./ops/deploy-backend-production.sh` (backend-only) or the full-stack pair that
includes both `docker-compose.production.yml` and `cutover-safe.yml`. Restore
PostgreSQL only if the migration itself changed data incompatibly.

Never roll back backend by recreating with `docker-compose.production.yml` alone.
