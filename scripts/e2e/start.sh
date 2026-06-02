#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

# ── Prerequisite checks ──────────────────────────────────────────────────────
echo "🔍 Checking prerequisites ..."

missing=0

if ! command -v docker >/dev/null 2>&1; then
  echo "  ✗ docker is not installed or not on PATH." >&2
  missing=1
else
  echo "  ✓ docker  $(docker --version 2>&1 | head -1)"
fi

if docker compose version >/dev/null 2>&1; then
  echo "  ✓ compose $(docker compose version 2>&1 | head -1)"
elif command -v docker-compose >/dev/null 2>&1; then
  echo "  ✓ compose $(docker-compose version 2>&1 | head -1)"
else
  echo "  ✗ docker compose (or docker-compose) is not installed." >&2
  missing=1
fi

if ! docker info >/dev/null 2>&1; then
  if ! (command -v sg >/dev/null 2>&1 && sg docker -c 'docker info >/dev/null 2>&1'); then
    echo "  ✗ Docker daemon is not reachable." >&2
    missing=1
  else
    echo "  ✓ docker daemon reachable (via sg docker)"
  fi
else
  echo "  ✓ docker daemon reachable"
fi

require_env
echo "  ✓ .env found at ${ENV_FILE}"

if [ "$missing" -ne 0 ]; then
  echo "" >&2
  echo "Prerequisites not met. Install missing tools and retry." >&2
  exit 1
fi

echo ""

# ── Load env & start infra profile only ──────────────────────────────────────
load_env
echo "🚀 Starting infrastructure services (qdrant, ollama, wikijs) ..."
compose --profile infra up -d --remove-orphans

echo ""
echo "📦 Service status:"
compose --profile infra ps

# ── Wait for infra services to become healthy ────────────────────────────────
echo ""
echo "⏳ Waiting for infrastructure services to report healthy ..."

# Qdrant — health endpoint at /healthz
wait_for_healthy qdrant "http://localhost:${QDRANT_PORT:-6333}/healthz" 60 3 || true

# Wiki.js — health via HTTP on its port (no standard health endpoint, just check it responds)
wait_for_healthy wikijs "http://localhost:${WIKIJS_PORT:-3000}" 90 5 || true

# Ollama — responds on /api/version
wait_for_healthy ollama "http://localhost:${OLLAMA_PORT:-11434}/api/version" 120 5 || true

echo ""
echo "✅ Infrastructure services are up."
echo ""
echo "Next steps in the lab-up flow:"
echo "   1. Pull Ollama models      (scripts/e2e/pull-models.sh)"
echo "   2. Create Qdrant collection (scripts/e2e/create-qdrant-collection.sh)"
echo "   3. Start Synapse service   (scripts/e2e/start-synapse.sh)"