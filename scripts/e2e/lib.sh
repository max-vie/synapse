#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${SYNAPSE_ENV_FILE:-$ROOT/.env}"
COMPOSE_FILE="${SYNAPSE_COMPOSE_FILE:-$ROOT/docker-compose.e2e.yml}"

compose() {
  local base=()
  if docker compose version >/dev/null 2>&1 || docker compose --version >/dev/null 2>&1; then
    base=(docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
  elif command -v docker-compose >/dev/null 2>&1; then
    base=(docker-compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
  else
    echo "Docker Compose is required." >&2
    return 1
  fi

  if docker info >/dev/null 2>&1; then
    "${base[@]}" "$@"
    return $?
  fi

  if command -v sg >/dev/null 2>&1 && sg docker -c 'docker info >/dev/null 2>&1'; then
    local cmd
    printf -v cmd '%q ' "${base[@]}" "$@"
    sg docker -c "$cmd"
    return $?
  fi

  echo "Docker daemon is not reachable. Try a fresh shell/session with docker group access." >&2
  return 1
}

require_env() {
  if [ ! -f "$ENV_FILE" ]; then
    echo "Missing $ENV_FILE. Run scripts/e2e/setup.sh first." >&2
    return 1
  fi
}

load_env() {
  require_env
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
}

# wait_for_healthy — block until a service responds on a URL or reports healthy.
#
# Usage:
#   wait_for_healthy SERVICE URL [TIMEOUT] [INTERVAL]
#
# Arguments:
#   SERVICE   — compose service name for display (required)
#   URL       — health endpoint URL to curl (required)
#   TIMEOUT   — max seconds to wait (default: 120)
#   INTERVAL  — seconds between polls (default: 5)
#
# Returns 0 on success, 1 on timeout.
wait_for_healthy() {
  local service="${1:?Usage: wait_for_healthy SERVICE URL [TIMEOUT] [INTERVAL]}"
  local url="${2:?Usage: wait_for_healthy SERVICE URL [TIMEOUT] [INTERVAL]}"
  local timeout="${3:-120}"
  local interval="${4:-5}"

  local deadline=$(( SECONDS + timeout ))
  local healthy=false

  echo "  Waiting for $service ... (timeout: ${timeout}s)"

  while [ "$SECONDS" -lt "$deadline" ]; do
    local http_code
    http_code="$(curl -sk -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo "000")"
    if [[ "$http_code" =~ ^2 ]]; then
      healthy=true
      break
    fi

    # also check Docker healthcheck if one exists
    local compose_health=""
    compose_health="$(compose ps --format json 2>/dev/null | python3 -c "
import json, sys
for line in sys.stdin:
    line = line.strip()
    if not line: continue
    try:
        o = json.loads(line)
        svc = o.get('Service','')
        h = o.get('Health','')
        if svc == '$service' and h == 'healthy':
            print('healthy')
            break
    except: pass
" 2>/dev/null || true)"
    if [ "$compose_health" = "healthy" ]; then
      healthy=true
      break
    fi

    sleep "$interval"
  done

  if $healthy; then
    echo "  [OK] $service is healthy."
    return 0
  else
    echo "  [FAIL] $service did not become healthy within ${timeout}s." >&2
    return 1
  fi
}