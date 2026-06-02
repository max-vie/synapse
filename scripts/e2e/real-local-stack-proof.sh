#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${SYNAPSE_ENV_FILE:-$ROOT/.env}"

# This is an explicit manual proof, not a cheap CI gate. It expects a configured
# real local lab: real Ollama models, Wiki.js with a usable API token, Qdrant,
# and the FastAPI Synapse API. Do not auto-generate .env here; placeholder Wiki.js tokens would make
# the proof look wired while guaranteeing the GraphQL publish/readback check fails.
if [ ! -f "$ENV_FILE" ]; then
  echo "Missing $ENV_FILE. Run make lab-up, complete Wiki.js admin setup, set WIKIJS_API_TOKEN, run make configure, then retry." >&2
  exit 2
fi

if grep -Eq '^WIKIJS_API_TOKEN=(|replace-after-wikijs-admin-setup)$' "$ENV_FILE"; then
  echo "WIKIJS_API_TOKEN in $ENV_FILE is missing or still the placeholder. Create a Wiki.js API token first." >&2
  exit 2
fi

"$ROOT/scripts/e2e/start.sh"
"$ROOT/scripts/e2e/pull-models.sh"
"$ROOT/scripts/e2e/create-qdrant-collection.sh"
"$ROOT/scripts/e2e/start-synapse.sh"
python3 "$ROOT/scripts/e2e/local_e2e_proof.py" --suite real
