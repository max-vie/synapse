#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DEMO=0
RUN_CHECK=0

usage() {
  cat <<'EOF'
Synapse compatibility setup helper

Usage:
  scripts/setup.sh [options]

Options:
  --demo           Run only the explicit no-credentials reviewer demo.
  --start-lab      Compatibility alias for the explicit lab-up flow.
  --check          Run the full make check gate after setup.
  -h, --help       Show this help.

This compatibility helper runs the first lab step (make lab-up):
- check required local commands;
- create .env with generated local-only secrets if missing;
- start the localhost-only Docker lab;
- pull local Ollama models, prepare Qdrant, and start the FastAPI Synapse service.

It does not complete the manual Wiki.js token step. After it finishes, run:
  make configure
  make proof

The reviewer demo is not part of default setup. Use --demo or make demo when you
intentionally want the no-Docker, no-network preview.

This helper does not delete Docker volumes and does not publish services publicly.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --demo|--reviewer-demo)
      RUN_DEMO=1
      shift
      ;;
    --start-lab)
      # Kept so older docs/scripts do not fail. Lab startup is now the default.
      shift
      ;;
    --check)
      RUN_CHECK=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[FAIL] Missing required command: $1" >&2
    return 1
  fi
}

cd "$ROOT"

echo "== Synapse setup =="
echo "Repository: $ROOT"
echo ""

require_cmd python3
require_cmd make

if [ "$RUN_DEMO" -eq 1 ]; then
  echo "Running explicit no-credentials reviewer demo ..."
  make demo

  if [ "$RUN_CHECK" -eq 1 ]; then
    echo "Running full local check ..."
    make check
  fi

  cat <<'EOF'

Reviewer demo complete.

To start services for the actual localhost Synapse lab, run:
  make lab-up
EOF
  exit 0
fi

require_cmd docker

# The individual e2e scripts handle prerequisite checks, wait-for-healthy,
# and progress output. Defer to them.
make lab-up

if [ "$RUN_CHECK" -eq 1 ]; then
  echo "Running full local check ..."
  make check
fi

cat <<'EOF'

Next manual step — configure Wiki.js:
  1. Open http://localhost:3000
  2. Complete the Wiki.js first-run admin setup if prompted.
  3. Go to Administration > API Keys, enable the API, and create a token
     with page create/update/read permission.
  4. Create a "synapse" group with admin permissions and assign the API key
     to that group.
  5. Update .env:  WIKIJS_API_TOKEN=your-real-token
  6. Restart if .env was already loaded:  make lab-down && make lab-up
  7. Verify:  make configure
  8. Run:  make proof

Reviewer demo is separate:  make demo
EOF