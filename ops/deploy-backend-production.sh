#!/usr/bin/env bash
# Canonical production backend recreate helper.
#
# Always applies:
#   docker-compose.production.yml + cutover-safe.yml + .env.production
#
# Fail-closed: aborts unless resolved and runtime scheduled-publish /
# retry-command flags match the safe production posture.
#
# Usage (from repo root on the production host):
#   ./ops/deploy-backend-production.sh
#
# Does NOT:
#   - broad compose up
#   - enable retry-command profile
#   - enable scheduled publishing
#   - modify providers / DB schema
#   - recreate backend a second time on readiness failure

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/china-smm-os}"
ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_PRODUCTION="docker-compose.production.yml"
COMPOSE_CUTOVER="cutover-safe.yml"
BACKEND_SERVICE="backend"
BACKEND_CONTAINER_DEFAULT="china-smm-os-production-backend-1"

# Bounded readiness polling after the single backend recreate.
# Override only in tests (short timeouts); production uses these defaults.
READINESS_POLL_INTERVAL_SEC="${READINESS_POLL_INTERVAL_SEC:-2}"
READINESS_TIMEOUT_SEC="${READINESS_TIMEOUT_SEC:-60}"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

info() {
  echo "$*"
}

require_file() {
  [[ -f "$1" ]] || die "missing required file: $1"
}

# Extract a service environment value from `docker compose config` YAML-ish output.
# Looks only inside the named top-level service block.
extract_service_env() {
  local service="$1"
  local key="$2"
  local config_file="$3"
  awk -v svc="$service" -v key="$key" '
    BEGIN { in_svc=0; in_env=0 }
    $0 ~ "^  " svc ":" { in_svc=1; in_env=0; next }
    in_svc && $0 ~ /^  [a-zA-Z0-9_-]+:/ { in_svc=0; in_env=0 }
    in_svc && $0 ~ /^    environment:/ { in_env=1; next }
    in_svc && in_env && $0 ~ /^    [a-zA-Z0-9_]+:/ { in_env=0 }
    in_svc && in_env {
      # Match KEY: value or KEY: "value"
      line=$0
      sub(/^[[:space:]]+/, "", line)
      if (index(line, key ":") == 1) {
        val=substr(line, length(key)+2)
        gsub(/^[[:space:]]+/, "", val)
        gsub(/^"/, "", val)
        gsub(/"$/, "", val)
        print val
        exit
      }
    }
  ' "$config_file"
}

assert_eq() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [[ "$actual" != "$expected" ]]; then
    die "preflight gate failed: ${label}=${actual:-<missing>} (expected ${expected})"
  fi
}

probe_http_health() {
  local cid="$1"
  docker exec "$cid" python -c \
    "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health', timeout=5).status)" \
    2>/dev/null || echo "fail"
}

docker_health_status() {
  local cid="$1"
  # "none" when the image/container has no Docker HEALTHCHECK.
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null \
    || echo "unknown"
}

# Exact readiness order after the single recreate:
#   1) resolve container id/name (caller)
#   2) each poll tick: sample Docker health (report only / soft wait)
#   3) each poll tick: probe HTTP GET /health (hard gate: must be 200)
#   4) ready when HTTP=200 AND (no healthcheck OR docker health=healthy)
# Docker health is never required *before* HTTP is attempted; if health status
# is unavailable ("none"), HTTP 200 alone is sufficient.
wait_for_backend_readiness() {
  local cid="$1"
  local started_at="$SECONDS"
  local deadline=$(( started_at + READINESS_TIMEOUT_SEC ))
  local http_code="fail"
  local docker_health="unknown"
  local attempt=0
  local container_status="unknown"

  info "===== readiness wait (interval=${READINESS_POLL_INTERVAL_SEC}s timeout=${READINESS_TIMEOUT_SEC}s) ====="
  info "order: docker health sample → HTTP /health → ready on HTTP 200 (+ healthy when healthcheck present)"

  while (( SECONDS < deadline )); do
    attempt=$((attempt + 1))
    docker_health="$(docker_health_status "$cid")"
    http_code="$(probe_http_health "$cid")"
    info "readiness attempt=${attempt} docker_health=${docker_health} http=${http_code}"

    if [[ "$http_code" == "200" ]]; then
      # Re-sample Docker health after HTTP success — healthcheck often flips on the same endpoint.
      docker_health="$(docker_health_status "$cid")"
      if [[ "$docker_health" == "none" || "$docker_health" == "healthy" ]]; then
        info "readiness: PASS (http=200 docker_health=${docker_health})"
        return 0
      fi
      info "HTTP 200 observed; continuing until docker_health=healthy (current=${docker_health}) or timeout"
    fi

    local remaining=$(( deadline - SECONDS ))
    if (( remaining <= 0 )); then
      break
    fi
    local sleep_for=$READINESS_POLL_INTERVAL_SEC
    if (( sleep_for > remaining )); then
      sleep_for=$remaining
    fi
    sleep "$sleep_for"
  done

  # Final sample: succeed if ready on the last tick (avoids false timeout when
  # HTTP/Docker flip ready during the last sleep window).
  docker_health="$(docker_health_status "$cid")"
  http_code="$(probe_http_health "$cid")"
  if [[ "$http_code" == "200" ]]; then
    docker_health="$(docker_health_status "$cid")"
    if [[ "$docker_health" == "none" || "$docker_health" == "healthy" ]]; then
      info "readiness: PASS (http=200 docker_health=${docker_health}) [final sample]"
      return 0
    fi
  fi

  container_status="$(docker inspect -f '{{.State.Status}}' "$cid" 2>/dev/null || echo unknown)"
  cat >&2 <<EOF
ERROR: backend readiness timeout after ${READINESS_TIMEOUT_SEC}s
  last_http=${http_code} (expected 200)
  last_docker_health=${docker_health}
  container_status=${container_status}
  container_id=${cid}
  attempts=${attempt}

Remediation:
  1. Inspect logs: docker logs ${cid}
  2. Do NOT broad-restart services.
  3. Do NOT automatically re-run deploy without diagnosing startup failure.
  4. Fix root cause, then re-run once: ./ops/deploy-backend-production.sh
EOF
  exit 1
}

# ---------------------------------------------------------------------------
# Repo / cwd checks
# ---------------------------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]] && [[ "$(pwd -P)" != "$(cd "$APP_DIR" && pwd -P)" ]]; then
  info "Switching to ${APP_DIR}"
  cd "$APP_DIR"
fi

[[ -d .git ]] || die "not a git repository (cwd=$(pwd))"
[[ -f "$COMPOSE_PRODUCTION" ]] || die "expected $COMPOSE_PRODUCTION in $(pwd)"
require_file "$COMPOSE_PRODUCTION"
require_file "$COMPOSE_CUTOVER"
require_file "$ENV_FILE"
require_file "ops/deploy-backend-production.sh"

info "===== production backend deploy (safe) ====="
info "cwd=$(pwd)"
info "HEAD=$(git rev-parse HEAD)"
info "compose=${COMPOSE_PRODUCTION} + ${COMPOSE_CUTOVER}"
info "env-file=${ENV_FILE}"
info "service=${BACKEND_SERVICE} only (no broad up, no retry-command profile)"

COMPOSE_BASE=(
  docker compose
  --env-file "$ENV_FILE"
  -f "$COMPOSE_PRODUCTION"
  -f "$COMPOSE_CUTOVER"
)

# ---------------------------------------------------------------------------
# Pre-deploy: resolved compose hard gates
# ---------------------------------------------------------------------------
info "===== preflight: resolved compose config ====="
RESOLVED="$(mktemp)"
trap 'rm -f "$RESOLVED"' EXIT

"${COMPOSE_BASE[@]}" config >"$RESOLVED" \
  || die "docker compose config failed — aborting before recreate"

# Sanity: both compose files appear in config labels / comment trail when present
if ! grep -q "SCHEDULED_PUBLISH_ENABLED" "$RESOLVED"; then
  die "resolved config missing SCHEDULED_PUBLISH_ENABLED"
fi

SCHED="$(extract_service_env backend SCHEDULED_PUBLISH_ENABLED "$RESOLVED")"
assert_eq "SCHEDULED_PUBLISH_ENABLED" "false" "$SCHED"

assert_eq "PUBLISH_RETRY_COMMANDS_ENABLED" "false" \
  "$(extract_service_env backend PUBLISH_RETRY_COMMANDS_ENABLED "$RESOLVED")"
assert_eq "PUBLISH_RETRY_COMMAND_WORKER_ENABLED" "false" \
  "$(extract_service_env backend PUBLISH_RETRY_COMMAND_WORKER_ENABLED "$RESOLVED")"
assert_eq "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED" "false" \
  "$(extract_service_env backend PUBLISH_RETRY_COMMAND_CLAIM_ENABLED "$RESOLVED")"
assert_eq "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED" "false" \
  "$(extract_service_env backend PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED "$RESOLVED")"
assert_eq "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND" "none" \
  "$(extract_service_env backend PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND "$RESOLVED")"

# Ensure retry-command worker is not part of the default project (no profile).
if grep -qE '^  publish-retry-command-worker:' "$RESOLVED"; then
  die "resolved config includes publish-retry-command-worker without profile — refuse recreate"
fi

info "preflight gates: PASS"

# ---------------------------------------------------------------------------
# Recreate backend only (exactly once — never retry recreate on readiness miss)
# ---------------------------------------------------------------------------
info "===== recreate backend only ====="
"${COMPOSE_BASE[@]}" up -d --no-deps --force-recreate "$BACKEND_SERVICE" \
  || die "backend recreate failed"

# ---------------------------------------------------------------------------
# Post-deploy: readiness, then hard safety gates
# ---------------------------------------------------------------------------
info "===== post-deploy verification ====="

# Resolve container name from compose
BACKEND_CID="$("${COMPOSE_BASE[@]}" ps -q "$BACKEND_SERVICE" || true)"
[[ -n "$BACKEND_CID" ]] || die "backend container id missing after recreate"
BACKEND_NAME="$(docker inspect -f '{{.Name}}' "$BACKEND_CID" | sed 's#^/##')"
BACKEND_NAME="${BACKEND_NAME:-$BACKEND_CONTAINER_DEFAULT}"

wait_for_backend_readiness "$BACKEND_CID"

RUNTIME_SCHED="$(docker exec "$BACKEND_CID" printenv SCHEDULED_PUBLISH_ENABLED || true)"
if [[ "$RUNTIME_SCHED" != "false" ]]; then
  cat >&2 <<EOF
ERROR: post-deploy gate failed: container SCHEDULED_PUBLISH_ENABLED=${RUNTIME_SCHED:-<missing>} (expected false)

Remediation:
  1. Do NOT leave the backend in this state.
  2. Re-run: ./ops/deploy-backend-production.sh
  3. Confirm both compose files are present and canonical production pins false.
  4. Do not enable providers or flip .env flags as a workaround.
EOF
  exit 1
fi

RUNTIME_RETRY_CMDS="$(docker exec "$BACKEND_CID" printenv PUBLISH_RETRY_COMMANDS_ENABLED || true)"
RUNTIME_RETRY_WORKER="$(docker exec "$BACKEND_CID" printenv PUBLISH_RETRY_COMMAND_WORKER_ENABLED || true)"
RUNTIME_RETRY_CLAIM="$(docker exec "$BACKEND_CID" printenv PUBLISH_RETRY_COMMAND_CLAIM_ENABLED || true)"
RUNTIME_RETRY_EXEC="$(docker exec "$BACKEND_CID" printenv PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED || true)"
RUNTIME_RETRY_BACKEND="$(docker exec "$BACKEND_CID" printenv PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND || true)"

[[ "$RUNTIME_RETRY_CMDS" == "false" ]] \
  || die "post-deploy gate failed: PUBLISH_RETRY_COMMANDS_ENABLED=${RUNTIME_RETRY_CMDS:-<missing>} (expected false)"
[[ "$RUNTIME_RETRY_WORKER" == "false" ]] \
  || die "post-deploy gate failed: PUBLISH_RETRY_COMMAND_WORKER_ENABLED=${RUNTIME_RETRY_WORKER:-<missing>} (expected false)"
[[ "$RUNTIME_RETRY_CLAIM" == "false" ]] \
  || die "post-deploy gate failed: PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=${RUNTIME_RETRY_CLAIM:-<missing>} (expected false)"
[[ "$RUNTIME_RETRY_EXEC" == "false" ]] \
  || die "post-deploy gate failed: PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=${RUNTIME_RETRY_EXEC:-<missing>} (expected false)"
[[ "$RUNTIME_RETRY_BACKEND" == "none" ]] \
  || die "post-deploy gate failed: PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=${RUNTIME_RETRY_BACKEND:-<missing>} (expected none)"

# Application Settings when practical (best-effort; fail if importable and True)
SETTINGS_OUT="$(docker exec -i "$BACKEND_CID" python - <<'PY' 2>/dev/null || true
from app.core.config import settings
print(f"SCHEDULED_PUBLISH_ENABLED={settings.SCHEDULED_PUBLISH_ENABLED}")
print(f"PUBLISH_RETRY_COMMANDS_ENABLED={settings.PUBLISH_RETRY_COMMANDS_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_WORKER_ENABLED={settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_CLAIM_ENABLED={settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED={settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND={settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND}")
PY
)"

if [[ -n "$SETTINGS_OUT" ]]; then
  echo "$SETTINGS_OUT" | grep -q '^SCHEDULED_PUBLISH_ENABLED=False$' \
    || die "application Settings.SCHEDULED_PUBLISH_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_COMMANDS_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_COMMANDS_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_COMMAND_WORKER_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_COMMAND_CLAIM_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=none$' \
    || die "application Settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND is not none"
  info "application Settings: PASS"
else
  info "application Settings probe skipped (import unavailable); container env gate still enforced"
fi

# Retry worker must be absent (profile not selected)
RETRY_COUNT="$(docker ps -a --filter "name=publish-retry-command-worker" --format '{{.ID}}' | wc -l | tr -d ' ')"
if [[ "$RETRY_COUNT" != "0" ]]; then
  die "publish-retry-command-worker container(s) present (count=${RETRY_COUNT}); expected absent"
fi

info "post-deploy gates: PASS"
info "backend_container=${BACKEND_NAME}"
info "SCHEDULED_PUBLISH_ENABLED=false"
info "retry-command flags=false backend=none"
info "retry-command worker absent"
info "===== DONE (safe recreate) ====="
