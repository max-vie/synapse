#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_env

# ---- Discover running services ----
echo "🛑  Stopping e2e environment …"

# List currently running services (silently skip if compose is already down)
running_services=""
if running_output=$(compose ps --services --filter "status=running" 2>/dev/null); then
  running_services=$(echo "$running_output" | grep -v '^$' || true)
fi

if [ -n "$running_services" ]; then
  service_count=$(echo "$running_services" | wc -l | tr -d ' ')
  echo "📋  Running services ($service_count):"
  # shellcheck disable=SC2001
  echo "$running_services" | sed 's/^/   • /'
else
  echo "📋  No running services detected."
fi

# ---- Shut down ----
echo "⏳  Running docker compose down …"
if compose --profile infra --profile full down 2>&1; then
  echo "✔ compose down succeeded."
else
  rc=$?
  echo "✘ compose down failed (exit $rc)." >&2
  exit $rc
fi

# ---- Confirm services are gone ----
echo -n "🔍  Verifying services stopped … "
remaining=""
if remain_output=$(compose ps --services --filter "status=running" 2>/dev/null); then
  remaining=$(echo "$remain_output" | grep -v '^$' || true)
fi

if [ -z "$remaining" ]; then
  echo "✔ all stopped"
else
  remain_count=$(echo "$remaining" | wc -l | tr -d ' ')
  echo "⚠ $remain_count service(s) still running:"
  # shellcheck disable=SC2001
  echo "$remaining" | sed 's/^/   • /'
fi

echo "✔ Stop complete."