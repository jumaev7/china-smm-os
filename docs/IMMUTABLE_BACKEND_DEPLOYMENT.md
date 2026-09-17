# F3 — Immutable Backend Deployment

**Status:** helper + tests landed. **Production runtime deployment remains NO-GO**
until a separately authorized task.

## Purpose

Deploy (or dry-run / roll back) an **exact** backend image without:

- retagging `latest`
- silent pull/build
- automatic migrations
- worker / retry-command profile startup
- changing Postgres, frontend, networks, volumes, or env semantics

## Required inputs

| Variable | Meaning |
|--|--|
| `BACKEND_IMAGE_REF` | Immutable ref (`name@sha256:…` preferred; SHA-specific tag OK) |
| `EXPECTED_BACKEND_IMAGE_ID` | Full image ID `sha256:` + 64 hex |
| `EXPECTED_SOURCE_SHA` | Full 40-char Git SHA baked into the image |

Rejected: `:latest`, bare names (implicit latest), missing/mismatched IDs or SHAs.

## Image / source proof

1. Local `docker image inspect` ID must equal `EXPECTED_BACKEND_IMAGE_ID` (no pull).
2. Label `org.opencontainers.image.revision` (and `SOURCE_SHA` env when set) must equal `EXPECTED_SOURCE_SHA`.
3. Deploy/rollback modes additionally hash critical `/app/...` files inside the image
   and compare them to `git show ${EXPECTED_SOURCE_SHA}:...` (label alone is insufficient).

Build future images with:

```bash
docker build -t china-smm-os-production-backend:r3-<shortsha> \
  --build-arg SOURCE_SHA=$(git rev-parse HEAD) \
  ./backend
```

Do **not** modify or rebuild the currently running production image as part of F3.

## Compose override

Template: `ops/compose-backend-image.override.yml.template`

The helper writes an ephemeral override that sets **only** `services.backend.image`.
Merged command:

```text
docker compose --env-file .env.production \
  -f docker-compose.production.yml \
  -f cutover-safe.yml \
  -f <ephemeral-override> …
```

## Modes

| Mode | Command | Mutations |
|--|--|--|
| Dry-run | `./ops/deploy-backend-production.sh --dry-run` | None |
| Deploy | `./ops/deploy-backend-production.sh` | Backend recreate once |
| Rollback | `./ops/deploy-backend-production.sh --rollback` | Backend recreate once on old image |

Rollback preserves the R1 DB schema (no Alembic downgrade). Postcheck failure does
**not** auto-rollback.

## Safety flags (resolved compose + runtime)

Must be `false` / `none` as applicable:

- `PUBLISH_WRITE_COORDINATION_SHADOW`
- `PUBLISH_WRITE_COORDINATION_ENABLED`
- `PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED`
- `PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED`
- `PUBLISH_RETRY_STRANDED_LIST_API_ENABLED`
- `PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED`
- retry command / worker / claim / execution activation
- `SCHEDULED_PUBLISH_ENABLED`
- `PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=none`
- `OPERATOR_AUTO_ACK_ALERTS_ENABLED=false`
