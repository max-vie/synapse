#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
require_env

# ---- Determine collection name from env for display ----
collection_base="${QDRANT_COLLECTION_BASE:-synapse_notes}"
embed_model="${OLLAMA_EMBED_MODEL:-nomic-embed-text}"

echo "🗂  Creating Qdrant collection (base=$collection_base, embed_model=$embed_model)"

# Run the Python creation script, capturing output for inspection
if output=$(python3 "$ROOT/scripts/e2e/create_qdrant_collection.py" --env-file "$ENV_FILE" 2>&1); then
  echo "$output"

  # Verify the collection actually exists by querying Qdrant
  qdrant_host="${QDRANT_HOST_BASE_URL:-http://127.0.0.1:${QDRANT_PORT:-6333}}"
  qdrant_host="${qdrant_host%/}"  # strip trailing slash

  # Extract collection name from the Python output
  collection_name=$(echo "$output" | grep -oP '(?<=Qdrant collection ready: )\S+' | cut -d'(' -f1 | xargs)

  if [ -n "$collection_name" ]; then
    echo -n "🔍  Verifying collection '$collection_name' exists in Qdrant … "
    verify_rc=0
    verify_output=$(curl -fsS "$qdrant_host/collections/$collection_name" 2>&1) || verify_rc=$?

    if [ $verify_rc -eq 0 ] && echo "$verify_output" | grep -q '"status":"ok"'; then
      echo "✔ confirmed"
    else
      echo "⚠ could not verify (Qdrant may not be reachable from host at $qdrant_host)"
    fi
  else
    echo "⚠ Could not extract collection name from output for verification."
  fi

  echo "✔ Qdrant collection setup complete."
else
  rc=$?
  echo "$output"

  # Detect already-exists case from Python output
  if echo "$output" | grep -qiE "already exist|collection.*exist"; then
    echo "ℹ  Collection appears to already exist. Continuing."
    exit 0
  fi

  echo "✘ Failed to create Qdrant collection (exit $rc)." >&2
  exit $rc
fi