#!/usr/bin/env bash
# Canonical production backend recreate helper (F3 immutable image contract).
#
# Always applies:
#   docker-compose.production.yml + cutover-safe.yml + backend image override + .env.production
#
# Required inputs (env):
#   BACKEND_IMAGE_REF          immutable image reference (digest preferred; SHA tag OK)
#   EXPECTED_BACKEND_IMAGE_ID  full image ID (sha256:…)
#   EXPECTED_SOURCE_SHA        full 40-char Git SHA associated with the image
#
# Optional:
#   EXPECTED_ALEMBIC_REVISION        if set, postcheck asserts alembic_version
#   EXPECTED_REGISTRY_ROW_COUNT      if set, postcheck asserts coordination registry count
#   DEPLOY_MODE=deploy|dry-run|rollback   (default: deploy; --dry-run / --rollback flags OK)
#
# Fail-closed: aborts unless resolved and runtime safety flags match the safe posture,
# and unless the selected image ID / source identity match expectations.
#
# Usage (from repo root on the production host):
#   BACKEND_IMAGE_REF=… EXPECTED_BACKEND_IMAGE_ID=… EXPECTED_SOURCE_SHA=… \
#     ./ops/deploy-backend-production.sh
#   … ./ops/deploy-backend-production.sh --dry-run
#   … ./ops/deploy-backend-production.sh --rollback
#
# Does NOT:
#   - broad compose up
#   - enable retry-command profile
#   - enable scheduled publishing
#   - retag `latest`
#   - pull / build images
#   - run Alembic / migrations
#   - modify providers / DB schema
#   - recreate backend a second time on readiness failure
#   - automatically roll back on postcheck failure

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/china-smm-os}"
ENV_FILE="${ENV_FILE:-.env.production}"
COMPOSE_PRODUCTION="docker-compose.production.yml"
COMPOSE_CUTOVER="cutover-safe.yml"
OVERRIDE_TEMPLATE="ops/compose-backend-image.override.yml.template"
BACKEND_SERVICE="backend"
BACKEND_CONTAINER_DEFAULT="china-smm-os-production-backend-1"
LATEST_IMAGE_NAME="china-smm-os-production-backend:latest"

# Bounded readiness polling after the single backend recreate.
# Override only in tests (short timeouts); production uses these defaults.
READINESS_POLL_INTERVAL_SEC="${READINESS_POLL_INTERVAL_SEC:-2}"
READINESS_TIMEOUT_SEC="${READINESS_TIMEOUT_SEC:-60}"

# Critical application paths hashed for source-identity proof (R3.1-style).
SOURCE_HASH_PATHS=(
  "/app/app/services/publish_service.py"
  "/app/app/core/config.py"
  "/app/app/main.py"
  "/app/app/api/v1/publishing.py"
  "/app/app/services/publish_resilience.py"
)

DEPLOY_MODE="${DEPLOY_MODE:-deploy}"
for arg in "$@"; do
  case "$arg" in
    --dry-run|dry-run)
      DEPLOY_MODE="dry-run"
      ;;
    --rollback|rollback)
      DEPLOY_MODE="rollback"
      ;;
    --deploy|deploy)
      DEPLOY_MODE="deploy"
      ;;
    -h|--help)
      sed -n '1,40p' "$0"
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

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
# Looks only inside the named top-level service block (any indent under that service).
extract_service_env() {
  local service="$1"
  local key="$2"
  local config_file="$3"
  awk -v svc="$service" -v key="$key" '
    BEGIN { in_svc=0 }
    $0 ~ "^  " svc ":" { in_svc=1; next }
    in_svc && $0 ~ /^  [a-zA-Z0-9_-]+:/ { in_svc=0 }
    in_svc {
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

# Extract a service's image: line from resolved compose config.
extract_service_image() {
  local service="$1"
  local config_file="$2"
  awk -v svc="$service" '
    BEGIN { in_svc=0 }
    $0 ~ "^  " svc ":" { in_svc=1; next }
    in_svc && $0 ~ /^  [a-zA-Z0-9_-]+:/ { in_svc=0 }
    in_svc {
      line=$0
      sub(/\r$/, "", line)
      if (line ~ /^[[:space:]]*image:[[:space:]]*/) {
        sub(/^[[:space:]]*image:[[:space:]]*/, "", line)
        gsub(/^"/, "", line)
        gsub(/"$/, "", line)
        print line
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

assert_false_flag() {
  local label="$1"
  local actual="$2"
  case "${actual,,}" in
    false|0|no|"")
      # empty treated as missing → fail below unless explicitly false-ish.
      ;;
  esac
  if [[ -z "$actual" ]]; then
    die "preflight gate failed: ${label}=<missing> (expected false)"
  fi
  case "${actual,,}" in
    false|0|no) ;;
    *) die "preflight gate failed: ${label}=${actual} (expected false)" ;;
  esac
}

normalize_image_id() {
  local id="$1"
  id="${id#sha256:}"
  echo "sha256:${id}"
}

is_full_git_sha() {
  [[ "$1" =~ ^[0-9a-fA-F]{40}$ ]]
}

is_full_image_id() {
  [[ "$1" =~ ^sha256:[0-9a-fA-F]{64}$ ]]
}

# Mutable / unverified refs are rejected. Digest refs and non-latest tags are OK
# only after local image-ID verification (caller responsibility).
reject_mutable_image_ref() {
  local ref="$1"
  [[ -n "$ref" ]] || die "BACKEND_IMAGE_REF is missing"
  if [[ "$ref" == *:latest || "$ref" == latest || "$ref" == */latest ]]; then
    die "mutable image reference rejected: ${ref} (do not use :latest)"
  fi
  # Bare name with no tag and no digest ⇒ Docker treats as :latest.
  if [[ "$ref" != *@sha256:* && "$ref" != *:* ]]; then
    die "mutable/unverified image reference rejected: ${ref} (implicit :latest)"
  fi
  # Explicit digest form is preferred; SHA-specific tags still require ID check.
  if [[ "$ref" == *@sha256:* ]]; then
    info "image ref form: digest (preferred)"
  else
    info "image ref form: tag (accepted only with exact image-ID verification)"
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
  docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null \
    || echo "unknown"
}

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
  4. Fix root cause, then re-run once with the same immutable image inputs.
  5. Rollback (separate authorization): same helper --rollback with the previous EXPECTED_* values.
EOF
  exit 1
}

write_backend_image_override() {
  local dest="$1"
  local ref="$2"
  require_file "$OVERRIDE_TEMPLATE"
  # Escape sed replacement specials in ref minimally (& \).
  local escaped
  escaped="$(printf '%s' "$ref" | sed -e 's/[&\\]/\\&/g')"
  sed "s|__BACKEND_IMAGE_REF__|${escaped}|g" "$OVERRIDE_TEMPLATE" >"$dest"
  grep -q "image: ${ref}" "$dest" || die "override file missing expected image: ${ref}"
  # Safety: override must only mention backend service image.
  if grep -qE 'postgres:|frontend:|migrate:|automation-worker:|publish-retry' "$dest"; then
    die "override file unexpectedly references non-backend services"
  fi
}

# Record latest image ID before any action (must remain unchanged).
snapshot_latest_image_id() {
  docker image inspect -f '{{.Id}}' "$LATEST_IMAGE_NAME" 2>/dev/null || echo "absent"
}

assert_latest_unchanged() {
  local before="$1"
  local after
  after="$(snapshot_latest_image_id)"
  [[ "$before" == "$after" ]] || die "latest image ID changed during helper run (before=${before} after=${after})"
}

verify_local_image_identity() {
  local ref="$1"
  local expected_id="$2"
  local expected_sha="$3"

  local actual_id raw_id label
  raw_id="$(docker image inspect -f '{{.Id}}' "$ref" 2>/dev/null)" \
    || die "image not present locally (will not pull/build): ${ref}"
  actual_id="$(normalize_image_id "$raw_id")"
  expected_id="$(normalize_image_id "$expected_id")"
  assert_eq "local_image_id" "$expected_id" "$actual_id"

  label="$(docker image inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$ref" 2>/dev/null || true)"
  if [[ -z "$label" || "$label" == "<no value>" || "$label" == "unknown" ]]; then
    die "image missing org.opencontainers.image.revision label (expected ${expected_sha})"
  fi
  assert_eq "image_revision_label" "$expected_sha" "$label"

  # Env SOURCE_SHA when present must also match.
  local env_sha
  env_sha="$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$ref" 2>/dev/null \
    | awk -F= '/^SOURCE_SHA=/{print $2; exit}')"
  if [[ -n "$env_sha" && "$env_sha" != "unknown" ]]; then
    assert_eq "image_SOURCE_SHA_env" "$expected_sha" "$env_sha"
  fi
}

# Compare critical file hashes inside the image to the Git tree at EXPECTED_SOURCE_SHA.
# Uses an ephemeral `docker run --rm` (not a compose service). Skipped in dry-run.
verify_image_file_hashes_against_git() {
  local ref="$1"
  local expected_sha="$2"

  git cat-file -e "${expected_sha}^{commit}" 2>/dev/null \
    || die "EXPECTED_SOURCE_SHA not found in local git: ${expected_sha}"

  local path host_hash image_hash repo_path
  for path in "${SOURCE_HASH_PATHS[@]}"; do
    repo_path="${path#/app/}"
    host_hash="$(git show "${expected_sha}:${repo_path}" 2>/dev/null | sha256sum | awk '{print $1}')" \
      || die "cannot hash host path at ${expected_sha}:${repo_path}"
    image_hash="$(docker run --rm --entrypoint sha256sum "$ref" "$path" 2>/dev/null | awk '{print $1}')" \
      || die "cannot hash image path ${path} in ${ref}"
    assert_eq "file_hash:${repo_path}" "$host_hash" "$image_hash"
  done
  info "source file-hash proof: PASS (${#SOURCE_HASH_PATHS[@]} paths @ ${expected_sha})"
}

assert_resolved_safety_flags() {
  local resolved="$1"

  if ! grep -q "SCHEDULED_PUBLISH_ENABLED" "$resolved"; then
    die "resolved config missing SCHEDULED_PUBLISH_ENABLED"
  fi

  assert_eq "SCHEDULED_PUBLISH_ENABLED" "false" \
    "$(extract_service_env backend SCHEDULED_PUBLISH_ENABLED "$resolved")"

  assert_false_flag "PUBLISH_WRITE_COORDINATION_SHADOW" \
    "$(extract_service_env backend PUBLISH_WRITE_COORDINATION_SHADOW "$resolved")"
  assert_false_flag "PUBLISH_WRITE_COORDINATION_ENABLED" \
    "$(extract_service_env backend PUBLISH_WRITE_COORDINATION_ENABLED "$resolved")"
  assert_false_flag "PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED "$resolved")"
  assert_false_flag "PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED "$resolved")"
  assert_false_flag "PUBLISH_RETRY_STRANDED_LIST_API_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_STRANDED_LIST_API_ENABLED "$resolved")"
  assert_false_flag "PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED "$resolved")"

  assert_false_flag "PUBLISH_RETRY_COMMANDS_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_COMMANDS_ENABLED "$resolved")"
  assert_false_flag "PUBLISH_RETRY_COMMAND_WORKER_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_COMMAND_WORKER_ENABLED "$resolved")"
  assert_false_flag "PUBLISH_RETRY_COMMAND_CLAIM_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_COMMAND_CLAIM_ENABLED "$resolved")"
  assert_false_flag "PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED" \
    "$(extract_service_env backend PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED "$resolved")"
  assert_eq "PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND" "none" \
    "$(extract_service_env backend PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND "$resolved")"

  # Auto-Ack: execution must remain disabled (shadow may exist but is not activated here).
  assert_false_flag "OPERATOR_AUTO_ACK_ALERTS_ENABLED" \
    "$(extract_service_env backend OPERATOR_AUTO_ACK_ALERTS_ENABLED "$resolved")"

  if grep -qE '^  publish-retry-command-worker:' "$resolved"; then
    die "resolved config includes publish-retry-command-worker without profile — refuse recreate"
  fi
}

assert_override_scope() {
  local resolved="$1"
  local expected_ref="$2"

  local backend_image postgres_image
  backend_image="$(extract_service_image backend "$resolved")"
  postgres_image="$(extract_service_image postgres "$resolved")"

  if [[ -z "$backend_image" ]]; then
    echo "ERROR: could not extract backend image from resolved compose; head:" >&2
    head -n 60 "$resolved" >&2 || true
    die "preflight gate failed: resolved.backend.image=<missing> (expected ${expected_ref})"
  fi

  assert_eq "resolved.backend.image" "$expected_ref" "$backend_image"
  assert_eq "resolved.postgres.image" "postgres:16-alpine" "$postgres_image"

  # Frontend must not pick up the backend image override.
  if grep -qE '^  frontend:' "$resolved"; then
    local frontend_image
    frontend_image="$(extract_service_image frontend "$resolved")"
    if [[ -n "$frontend_image" && "$frontend_image" == "$expected_ref" ]]; then
      die "frontend image incorrectly set to backend override ref"
    fi
  fi
}

print_sanitized_plan() {
  local mode="$1"
  cat <<EOF
===== deployment plan (sanitized) =====
mode=${mode}
service=${BACKEND_SERVICE} only
compose_files=${COMPOSE_PRODUCTION} + ${COMPOSE_CUTOVER} + <ephemeral backend image override>
env_file=${ENV_FILE} (values not printed)
BACKEND_IMAGE_REF=${BACKEND_IMAGE_REF}
EXPECTED_BACKEND_IMAGE_ID=${EXPECTED_BACKEND_IMAGE_ID}
EXPECTED_SOURCE_SHA=${EXPECTED_SOURCE_SHA}
recreate_command=docker compose ... recreate-backend-only
migrations=NOT invoked
workers=NOT started (no retry-command profile)
retag_latest=NOT performed
pull_or_build=NOT performed
EOF
}

# ---------------------------------------------------------------------------
# Post-deploy verification helpers (reusable; no automatic rollback)
# ---------------------------------------------------------------------------
verify_running_container_image_id() {
  local cid="$1"
  local expected_id="$2"
  local actual
  actual="$(normalize_image_id "$(docker inspect -f '{{.Image}}' "$cid")")"
  expected_id="$(normalize_image_id "$expected_id")"
  assert_eq "running_container_image_id" "$expected_id" "$actual"
}

verify_running_source_identity() {
  local cid="$1"
  local expected_sha="$2"
  local label env_sha
  label="$(docker inspect -f '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$cid" 2>/dev/null || true)"
  if [[ -n "$label" && "$label" != "<no value>" ]]; then
    assert_eq "running_revision_label" "$expected_sha" "$label"
  fi
  env_sha="$(docker exec "$cid" printenv SOURCE_SHA 2>/dev/null || true)"
  if [[ -n "$env_sha" && "$env_sha" != "unknown" ]]; then
    assert_eq "running_SOURCE_SHA" "$expected_sha" "$env_sha"
  fi
}

report_container_start_time() {
  local cid="$1"
  docker inspect -f '{{.State.StartedAt}}' "$cid" 2>/dev/null || echo "unknown"
}

count_retry_workers() {
  docker ps -a --filter "name=publish-retry-command-worker" --format '{{.ID}}' 2>/dev/null \
    | wc -l | tr -d ' '
}

verify_alembic_revision() {
  local cid="$1"
  local expected="${EXPECTED_ALEMBIC_REVISION:-}"
  local actual
  actual="$(docker exec "$cid" python - <<'PY' 2>/dev/null || true
from sqlalchemy import create_engine, text
import os
url = os.environ.get("DATABASE_URL", "")
if not url:
    print("unknown")
else:
    eng = create_engine(url)
    with eng.connect() as c:
        row = c.execute(text("select version_num from alembic_version")).fetchone()
        print(row[0] if row else "none")
PY
)"
  info "alembic_revision=${actual:-unknown}"
  if [[ -n "$expected" ]]; then
    assert_eq "alembic_revision" "$expected" "${actual:-}"
  fi
}

verify_registry_row_count() {
  local cid="$1"
  local expected="${EXPECTED_REGISTRY_ROW_COUNT:-}"
  local actual
  actual="$(docker exec "$cid" python - <<'PY' 2>/dev/null || true
from sqlalchemy import create_engine, text
import os
url = os.environ.get("DATABASE_URL", "")
if not url:
    print("unknown")
else:
    eng = create_engine(url)
    with eng.connect() as c:
        try:
            n = c.execute(text("select count(*) from publish_write_coordination_registry")).scalar()
            print(int(n))
        except Exception:
            print("unknown")
PY
)"
  info "registry_row_count=${actual:-unknown}"
  if [[ -n "$expected" ]]; then
    assert_eq "registry_row_count" "$expected" "${actual:-}"
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
require_file "$OVERRIDE_TEMPLATE"

BACKEND_IMAGE_REF="${BACKEND_IMAGE_REF:-}"
EXPECTED_BACKEND_IMAGE_ID="${EXPECTED_BACKEND_IMAGE_ID:-}"
EXPECTED_SOURCE_SHA="${EXPECTED_SOURCE_SHA:-}"

info "===== production backend deploy (immutable / safe) ====="
info "cwd=$(pwd)"
info "HEAD=$(git rev-parse HEAD)"
info "mode=${DEPLOY_MODE}"
info "compose=${COMPOSE_PRODUCTION} + ${COMPOSE_CUTOVER} + backend-image-override"
info "env-file=${ENV_FILE}"
info "service=${BACKEND_SERVICE} only (no broad up, no retry-command profile, no migrate)"

# ---------------------------------------------------------------------------
# Required immutable inputs
# ---------------------------------------------------------------------------
[[ -n "$BACKEND_IMAGE_REF" ]] || die "BACKEND_IMAGE_REF is required"
[[ -n "$EXPECTED_BACKEND_IMAGE_ID" ]] || die "EXPECTED_BACKEND_IMAGE_ID is required"
[[ -n "$EXPECTED_SOURCE_SHA" ]] || die "EXPECTED_SOURCE_SHA is required"
is_full_image_id "$(normalize_image_id "$EXPECTED_BACKEND_IMAGE_ID")" \
  || die "EXPECTED_BACKEND_IMAGE_ID must be full sha256:<64 hex> (got ${EXPECTED_BACKEND_IMAGE_ID})"
EXPECTED_BACKEND_IMAGE_ID="$(normalize_image_id "$EXPECTED_BACKEND_IMAGE_ID")"
is_full_git_sha "$EXPECTED_SOURCE_SHA" \
  || die "EXPECTED_SOURCE_SHA must be full 40-char Git SHA (got ${EXPECTED_SOURCE_SHA})"
reject_mutable_image_ref "$BACKEND_IMAGE_REF"

OVERRIDE_FILE="$(mktemp)"
RESOLVED="$(mktemp)"
LATEST_BEFORE="$(snapshot_latest_image_id)"
cleanup() {
  rm -f "$OVERRIDE_FILE" "$RESOLVED"
}
trap cleanup EXIT

write_backend_image_override "$OVERRIDE_FILE" "$BACKEND_IMAGE_REF"

COMPOSE_BASE=(
  docker compose
  --env-file "$ENV_FILE"
  -f "$COMPOSE_PRODUCTION"
  -f "$COMPOSE_CUTOVER"
  -f "$OVERRIDE_FILE"
)

# ---------------------------------------------------------------------------
# Pre-deploy: local image identity (no pull/build)
# ---------------------------------------------------------------------------
info "===== preflight: local image identity ====="
verify_local_image_identity "$BACKEND_IMAGE_REF" "$EXPECTED_BACKEND_IMAGE_ID" "$EXPECTED_SOURCE_SHA"
assert_latest_unchanged "$LATEST_BEFORE"

if [[ "$DEPLOY_MODE" != "dry-run" ]]; then
  info "===== preflight: source file-hash proof ====="
  verify_image_file_hashes_against_git "$BACKEND_IMAGE_REF" "$EXPECTED_SOURCE_SHA"
  assert_latest_unchanged "$LATEST_BEFORE"
else
  info "dry-run: skipping ephemeral docker run file-hash probe (inspect+label only)"
  git cat-file -e "${EXPECTED_SOURCE_SHA}^{commit}" 2>/dev/null \
    || die "EXPECTED_SOURCE_SHA not found in local git: ${EXPECTED_SOURCE_SHA}"
fi

# ---------------------------------------------------------------------------
# Pre-deploy: resolved compose hard gates
# ---------------------------------------------------------------------------
info "===== preflight: resolved compose config ====="
"${COMPOSE_BASE[@]}" config >"$RESOLVED" \
  || die "docker compose config failed — aborting before recreate"

assert_override_scope "$RESOLVED" "$BACKEND_IMAGE_REF"
assert_resolved_safety_flags "$RESOLVED"

info "preflight gates: PASS"
print_sanitized_plan "$DEPLOY_MODE"
assert_latest_unchanged "$LATEST_BEFORE"

if [[ "$DEPLOY_MODE" == "dry-run" ]]; then
  info "===== dry-run complete (zero mutations) ====="
  info "latest_image_id_unchanged=${LATEST_BEFORE}"
  info "no compose up / build / pull / tag / migrate performed"
  exit 0
fi

# ---------------------------------------------------------------------------
# Recreate backend only (exactly once — never retry recreate on readiness miss)
# ---------------------------------------------------------------------------
if [[ "$DEPLOY_MODE" == "rollback" ]]; then
  info "===== rollback: recreate backend only on previous immutable image ====="
  info "rollback preserves R1 schema (no Alembic downgrade); workers remain disabled"
else
  info "===== recreate backend only ====="
fi

# Guard: refuse any accidental migrate / profile activation in this command.
RECREATE_CMD=( "${COMPOSE_BASE[@]}" up -d --no-deps --force-recreate "$BACKEND_SERVICE" )
info "exec: docker compose ... recreate-backend-only (${BACKEND_SERVICE})"
"${RECREATE_CMD[@]}" || die "backend recreate failed"
assert_latest_unchanged "$LATEST_BEFORE"

# ---------------------------------------------------------------------------
# Post-deploy: readiness, image identity, then hard safety gates
# ---------------------------------------------------------------------------
info "===== post-deploy verification ====="

BACKEND_CID="$("${COMPOSE_BASE[@]}" ps -q "$BACKEND_SERVICE" || true)"
[[ -n "$BACKEND_CID" ]] || die "backend container id missing after recreate"
BACKEND_NAME="$(docker inspect -f '{{.Name}}' "$BACKEND_CID" | sed 's#^/##')"
BACKEND_NAME="${BACKEND_NAME:-$BACKEND_CONTAINER_DEFAULT}"
STARTED_AT="$(report_container_start_time "$BACKEND_CID")"
info "backend_container=${BACKEND_NAME} started_at=${STARTED_AT}"

verify_running_container_image_id "$BACKEND_CID" "$EXPECTED_BACKEND_IMAGE_ID"
verify_running_source_identity "$BACKEND_CID" "$EXPECTED_SOURCE_SHA"

wait_for_backend_readiness "$BACKEND_CID"

RUNTIME_SCHED="$(docker exec "$BACKEND_CID" printenv SCHEDULED_PUBLISH_ENABLED || true)"
if [[ "$RUNTIME_SCHED" != "false" ]]; then
  cat >&2 <<EOF
ERROR: post-deploy gate failed: container SCHEDULED_PUBLISH_ENABLED=${RUNTIME_SCHED:-<missing>} (expected false)

Remediation:
  1. Do NOT leave the backend in this state without investigation.
  2. Do NOT automatically roll back unless separately authorized.
  3. Re-run with the same immutable inputs only after root-cause fix, or
     invoke --rollback with the previous verified EXPECTED_* values.
EOF
  exit 1
fi

post_assert_env_false() {
  local key="$1"
  local val
  val="$(docker exec "$BACKEND_CID" printenv "$key" || true)"
  [[ "$val" == "false" ]] || die "post-deploy gate failed: ${key}=${val:-<missing>} (expected false)"
}

post_assert_env_false PUBLISH_WRITE_COORDINATION_SHADOW
post_assert_env_false PUBLISH_WRITE_COORDINATION_ENABLED
post_assert_env_false PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED
post_assert_env_false PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED
post_assert_env_false PUBLISH_RETRY_STRANDED_LIST_API_ENABLED
post_assert_env_false PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED
post_assert_env_false PUBLISH_RETRY_COMMANDS_ENABLED
post_assert_env_false PUBLISH_RETRY_COMMAND_WORKER_ENABLED
post_assert_env_false PUBLISH_RETRY_COMMAND_CLAIM_ENABLED
post_assert_env_false PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED
post_assert_env_false OPERATOR_AUTO_ACK_ALERTS_ENABLED

RUNTIME_RETRY_BACKEND="$(docker exec "$BACKEND_CID" printenv PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND || true)"
[[ "$RUNTIME_RETRY_BACKEND" == "none" ]] \
  || die "post-deploy gate failed: PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND=${RUNTIME_RETRY_BACKEND:-<missing>} (expected none)"

# Application Settings when practical (best-effort; fail if importable and unsafe)
SETTINGS_OUT="$(docker exec -i "$BACKEND_CID" python - <<'PY' 2>/dev/null || true
from app.core.config import settings
print(f"SCHEDULED_PUBLISH_ENABLED={settings.SCHEDULED_PUBLISH_ENABLED}")
print(f"PUBLISH_WRITE_COORDINATION_SHADOW={settings.PUBLISH_WRITE_COORDINATION_SHADOW}")
print(f"PUBLISH_WRITE_COORDINATION_ENABLED={settings.PUBLISH_WRITE_COORDINATION_ENABLED}")
print(f"PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED={settings.PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED}")
print(f"PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED={settings.PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED}")
print(f"PUBLISH_RETRY_STRANDED_LIST_API_ENABLED={settings.PUBLISH_RETRY_STRANDED_LIST_API_ENABLED}")
print(f"PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED={settings.PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED}")
print(f"PUBLISH_RETRY_COMMANDS_ENABLED={settings.PUBLISH_RETRY_COMMANDS_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_WORKER_ENABLED={settings.PUBLISH_RETRY_COMMAND_WORKER_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_CLAIM_ENABLED={settings.PUBLISH_RETRY_COMMAND_CLAIM_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED={settings.PUBLISH_RETRY_COMMAND_EXECUTION_ENABLED}")
print(f"PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND={settings.PUBLISH_RETRY_COMMAND_EXECUTION_BACKEND}")
print(f"OPERATOR_AUTO_ACK_ALERTS_ENABLED={settings.OPERATOR_AUTO_ACK_ALERTS_ENABLED}")
PY
)"

if [[ -n "$SETTINGS_OUT" ]]; then
  echo "$SETTINGS_OUT" | grep -q '^SCHEDULED_PUBLISH_ENABLED=False$' \
    || die "application Settings.SCHEDULED_PUBLISH_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_WRITE_COORDINATION_SHADOW=False$' \
    || die "application Settings.PUBLISH_WRITE_COORDINATION_SHADOW is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_WRITE_COORDINATION_ENABLED=False$' \
    || die "application Settings.PUBLISH_WRITE_COORDINATION_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_MANUAL_RESOLUTION_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_MANUAL_RESOLUTION_E2_2_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_STRANDED_LIST_API_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_STRANDED_LIST_API_ENABLED is not False"
  echo "$SETTINGS_OUT" | grep -q '^PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED=False$' \
    || die "application Settings.PUBLISH_RETRY_STRANDED_ALERT_SURFACING_ENABLED is not False"
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
  echo "$SETTINGS_OUT" | grep -q '^OPERATOR_AUTO_ACK_ALERTS_ENABLED=False$' \
    || die "application Settings.OPERATOR_AUTO_ACK_ALERTS_ENABLED is not False"
  info "application Settings: PASS"
else
  info "application Settings probe skipped (import unavailable); container env gate still enforced"
fi

RETRY_COUNT="$(count_retry_workers)"
if [[ "$RETRY_COUNT" != "0" ]]; then
  die "publish-retry-command-worker container(s) present (count=${RETRY_COUNT}); expected absent"
fi

verify_alembic_revision "$BACKEND_CID"
verify_registry_row_count "$BACKEND_CID"

assert_latest_unchanged "$LATEST_BEFORE"

info "post-deploy gates: PASS"
info "backend_container=${BACKEND_NAME}"
info "image_id=${EXPECTED_BACKEND_IMAGE_ID}"
info "source_sha=${EXPECTED_SOURCE_SHA}"
info "started_at=${STARTED_AT}"
info "SCHEDULED_PUBLISH_ENABLED=false"
info "write-coordination/shadow/manual/stranded/retry flags=false backend=none"
info "retry-command worker absent"
info "latest unchanged"
if [[ "$DEPLOY_MODE" == "rollback" ]]; then
  info "===== DONE (immutable rollback recreate) ====="
else
  info "===== DONE (immutable safe recreate) ====="
fi
