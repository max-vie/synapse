#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_env

# --- service definitions: name, compose-service, port, health-path ---
declare -A SVC_PORT
declare -A SVC_HEALTH
SERVICES=(qdrant ollama synapse-service wikijs)

SVC_PORT[qdrant]="${QDRANT_PORT:-6333}"
SVC_HEALTH[qdrant]="/collections"

SVC_PORT[ollama]="${OLLAMA_PORT:-11434}"
SVC_HEALTH[ollama]="/api/tags"

SVC_PORT[synapse-service]="${SYNAPSE_SERVICE_PORT:-15515}"
SVC_HEALTH[synapse-service]="/readyz"

SVC_PORT[wikijs]="${WIKIJS_PORT:-3000}"
SVC_HEALTH[wikijs]=""

# --- gather compose container state ---
declare -A CSTATE
declare -A CHEALTH
while IFS=$'\t' read -r name state health; do
  CSTATE["$name"]="$state"
  CHEALTH["$name"]="$health"
done < <(compose --profile full ps --format '{{.Name}}\t{{.State}}\t{{.Health}}' 2>/dev/null | sed 's/^synapse-e2e-//; s/-[0-9]*$//' || true)

# --- per-service status report ---
printf '%-20s %-10s %-12s %-8s %s\n' "SERVICE" "STATE" "HEALTH" "HTTP" "ENDPOINT"
printf '%-20s %-10s %-12s %-8s %s\n' "-------" "-----" "------" "----" "--------"

overall=0
for svc in "${SERVICES[@]}"; do
  port="${SVC_PORT[$svc]}"
  health_path="${SVC_HEALTH[$svc]}"

  # container state
  cstate="${CSTATE[$svc]:-}"
  chealth="${CHEALTH[$svc]:-}"
  if [ -z "$cstate" ]; then
    state_str="stopped"
    health_str="N/A"
  else
    state_str="$cstate"
    health_str="${chealth:-N/A}"
  fi

  # HTTP probe
  if [ -n "$health_path" ]; then
    url="http://localhost:${port}${health_path}"
  else
    url="http://localhost:${port}"
  fi

  http_code=""
  http_ok="[FAIL]"
  if [ "$state_str" = "running" ]; then
    http_code=$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 5 "$url" 2>/dev/null || echo "000")
    case "$http_code" in
      2[0-9][0-9]) http_ok="[OK]" ;;
      *)           http_ok="[FAIL]"; overall=1 ;;
    esac
  else
    http_code="---"
    overall=1
  fi

  if [ "$state_str" != "running" ]; then
    overall=1
  fi

  printf '%-20s %-10s %-12s %-8s %s\n' "$svc" "$state_str" "$health_str" "$http_ok" "$url  ($http_code)"
done

echo ""
if [ "$overall" -eq 0 ]; then
  echo "All services [OK]."
else
  echo "One or more services [FAIL]. Check logs with: make lab-logs"
fi

echo ""
echo "Synapse readiness:"
echo "  liveness  : http://localhost:${SYNAPSE_SERVICE_PORT:-15515}/healthz  (always 200 if process up)"
echo "  readiness : http://localhost:${SYNAPSE_SERVICE_PORT:-15515}/readyz   (503 if dependencies down)"

echo ""
echo "Local endpoints:"
echo "  Synapse API : http://localhost:${SYNAPSE_SERVICE_PORT:-15515}"
echo "  Wiki.js     : http://localhost:${WIKIJS_PORT:-3000}"
echo "  Qdrant      : http://localhost:${QDRANT_PORT:-6333}"
echo "  Ollama      : http://localhost:${OLLAMA_PORT:-11434}"