#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ARTIFACT_DIR="$ROOT/.local-artifacts/ci-e2e"
ENV_FILE="$ARTIFACT_DIR/.env"
COMPOSE_FILE="$ROOT/docker-compose.ci-e2e.yml"

mkdir -p "$ARTIFACT_DIR"

{
cat <<'ENV'
SYNAPSE_SERVICE_PORT=6578
QDRANT_PORT=6633
QDRANT_IMAGE=qdrant/qdrant:v1.18.1
SYNAPSE_SERVICE_IMAGE=synapse-service:local
SYNAPSE_WEBHOOK_AUTH_TOKEN=ci-e2e-token
SYNAPSE_AUTH_DISABLED=false
OLLAMA_INTERNAL_BASE_URL=http://mock-ollama:11435
OLLAMA_CHAT_BASE_URL=http://mock-ollama:11435
OLLAMA_EMBED_MODEL=mock-embed
OLLAMA_FORMAT_MODEL=mock-format
OLLAMA_ANSWER_MODEL=mock-answer
QDRANT_COLLECTION=synapse_ci_e2e
SYNAPSE_MANAGE_QDRANT_COLLECTION=false
QDRANT_VECTOR_SIZE=8
RAG_TOP_K=3
RAG_CANDIDATE_K=10
RAG_SCORE_THRESHOLD=0
RAG_QUERY_TERM_MIN_COVERAGE=0.5
RAG_QUERY_TERM_MIN_MATCHES=2
RAG_DOMAIN_GLOSSARY_JSON={}
OBSIDIAN_VAULT_PATH=examples/obsidian-vault
ENV
} >"$ENV_FILE"

export SYNAPSE_ENV_FILE="$ENV_FILE"
export SYNAPSE_COMPOSE_FILE="$COMPOSE_FILE"
# shellcheck source=scripts/e2e/lib.sh
source "$ROOT/scripts/e2e/lib.sh"

cleanup() {
  local status=$?
  if [ "$status" -ne 0 ]; then
    echo "Mocked FastAPI/Qdrant e2e failed; Synapse service logs follow:" >&2
    compose logs --no-color --tail=200 synapse-service >&2 || true
    echo "Mock Ollama logs follow:" >&2
    compose logs --no-color --tail=200 mock-ollama >&2 || true
  fi
  compose down -v --remove-orphans >/dev/null 2>&1 || true
  exit "$status"
}
trap cleanup EXIT

wait_for_http() {
  local name="$1"
  local url="$2"
  local attempts="${3:-60}"
  local delay="${4:-2}"
  local i
  for ((i = 1; i <= attempts; i += 1)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      printf '%s ready: %s\n' "$name" "$url"
      return 0
    fi
    sleep "$delay"
  done
  echo "Timed out waiting for $name at $url" >&2
  return 1
}

compose up -d qdrant mock-ollama synapse-service
wait_for_http "Qdrant" "http://127.0.0.1:6633/collections" 60 2
wait_for_http "Synapse API" "http://127.0.0.1:6578/healthz" 120 2

"$ROOT/scripts/e2e/create-qdrant-collection.sh"

python3 "$ROOT/scripts/e2e/local_e2e_proof.py" --suite ci
