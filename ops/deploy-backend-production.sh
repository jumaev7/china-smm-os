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

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/china-smm-os}"
ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_PRODUCTION="docker-compose.production.yml"
COMPOSE_CUTOVER="cutover-safe.yml"
BACKEND_SERVICE="backend"
BACKEND_CONTAINER_DEFAULT="china-smm-os-production-backend-1"

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
# Recreate backend only
# ---------------------------------------------------------------------------
info "===== recreate backend only ====="
"${COMPOSE_BASE[@]}" up -d --no-deps --force-recreate "$BACKEND_SERVICE" \
  || die "backend recreate failed"

# ---------------------------------------------------------------------------
# Post-deploy hard gates
# ---------------------------------------------------------------------------
info "===== post-deploy verification ====="

# Resolve container name from compose
BACKEND_CID="$("${COMPOSE_BASE[@]}" ps -q "$BACKEND_SERVICE" || true)"
[[ -n "$BACKEND_CID" ]] || die "backend container id missing after recreate"
BACKEND_NAME="$(docker inspect -f '{{.Name}}' "$BACKEND_CID" | sed 's#^/##')"
BACKEND_NAME="${BACKEND_NAME:-$BACKEND_CONTAINER_DEFAULT}"

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

# Health
HEALTH_CODE="$(docker exec "$BACKEND_CID" python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health', timeout=5).status)" \
  2>/dev/null || echo "fail")"
[[ "$HEALTH_CODE" == "200" ]] || die "/health returned ${HEALTH_CODE} (expected 200)"

# Retry worker must be absent (profile not selected)
RETRY_COUNT="$(docker ps -a --filter "name=publish-retry-command-worker" --format '{{.ID}}' | wc -l | tr -d ' ')"
if [[ "$RETRY_COUNT" != "0" ]]; then
  die "publish-retry-command-worker container(s) present (count=${RETRY_COUNT}); expected absent"
fi

info "post-deploy gates: PASS"
info "backend_container=${BACKEND_NAME}"
info "SCHEDULED_PUBLISH_ENABLED=false"
info "retry-command worker absent"
info "===== DONE (safe recreate) ====="
