#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${SYNAPSE_ENV_FILE:-$ROOT/.env}"

# --- determine what exists before removing anything ---
items=()

if [ -f "$ENV_FILE" ]; then
  items+=("env:$ENV_FILE")
fi

# check for running compose project
compose_running=false
if [ -f "$ENV_FILE" ]; then
  if compose ps -q 2>/dev/null | grep -q .; then
    compose_running=true
    items+=("containers+network+volumes (compose project)")
  fi
elif compose ps -q 2>/dev/null | grep -q .; then
  compose_running=true
  items+=("containers+network+volumes (compose project)")
fi

if [ -d "$ROOT/.local-artifacts" ]; then
  items+=("dir:$ROOT/.local-artifacts")
fi

# --- nothing to remove? ---
if [ ${#items[@]} -eq 0 ]; then
  echo "Nothing to remove. No running containers, volumes, .env, or local artifacts found."
  exit 0
fi

# --- show what will be removed ---
echo "The following will be removed:"
for item in "${items[@]}"; do
  echo "  - $item"
done
echo ""

# --- remove compose resources ---
if $compose_running; then
  echo -n "Removing containers, network, and Docker volumes... "
  if [ -f "$ENV_FILE" ]; then
    compose --profile infra --profile full down --remove-orphans -v 2>&1
  else
    compose --profile infra --profile full down --remove-orphans -v 2>/dev/null || true
  fi
  echo "[OK] Removed."
elif [ -f "$ENV_FILE" ]; then
  echo -n "Stopping compose project (no running containers found)... "
  compose --profile infra --profile full down --remove-orphans -v 2>/dev/null || true
  echo "[OK] Done."
fi

# --- remove .env ---
if [ -f "$ENV_FILE" ]; then
  echo -n "Removing $ENV_FILE... "
  rm -f "$ENV_FILE"
  echo "[OK] Removed."
fi

# --- remove local artifacts ---
if [ -d "$ROOT/.local-artifacts" ]; then
  echo -n "Removing $ROOT/.local-artifacts/... "
  rm -rf "$ROOT/.local-artifacts"
  echo "[OK] Removed."
fi

echo ""
echo "Removal complete. Run 'make lab-up' to start fresh."