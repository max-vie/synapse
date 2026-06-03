#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_env

echo "📦 Building Synapse image if needed ..."
docker build -t synapse-service:local . 2>/dev/null || true

echo "🚀 Starting Synapse service with profile 'full' ..."
compose --profile full up -d --force-recreate synapse-service

# Wait for Synapse to become healthy
wait_for_healthy synapse-service "http://localhost:${SYNAPSE_SERVICE_PORT:-15515}/readyz" 90 5 || true

echo ""
echo "✅ Synapse service is up."
echo "   Synapse API:  http://localhost:${SYNAPSE_SERVICE_PORT:-15515}"