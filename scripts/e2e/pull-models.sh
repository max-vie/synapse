#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"
load_env

ollama_base="${OLLAMA_INTERNAL_BASE_URL:-http://ollama:11434}"
chat_base="${OLLAMA_CHAT_BASE_URL:-$ollama_base}"
internal_base="http://ollama:11434"

if [ "$#" -gt 0 ]; then
  models=("$@")
elif [ "$ollama_base" != "$internal_base" ]; then
  echo "⏭  Skipping local Ollama pulls because OLLAMA_INTERNAL_BASE_URL points at $ollama_base."
  exit 0
else
  models=("${OLLAMA_EMBED_MODEL:-nomic-embed-text}")
  if [ "$chat_base" != "$internal_base" ]; then
    echo "⏭  Skipping local chat model pulls because OLLAMA_CHAT_BASE_URL points at $chat_base."
  else
    models+=(
      "${OLLAMA_FORMAT_MODEL:-tinyllama:latest}"
      "${OLLAMA_ANSWER_MODEL:-tinyllama:latest}"
    )
  fi
fi

# ---- Deduplicate & announce ----
declare -A seen=()
unique_models=()
for model in "${models[@]}"; do
  [ -n "$model" ] || continue
  if [ -n "${seen[$model]:-}" ]; then
    continue
  fi
  seen[$model]=1
  unique_models+=("$model")
done

if [ ${#unique_models[@]} -eq 0 ]; then
  echo "No models to pull."
  exit 0
fi

echo "📦 Models to pull (${#unique_models[@]}): ${unique_models[*]}"
echo "────────────────────────────────────────"

failures=0
for model in "${unique_models[@]}"; do
  echo -n "⬇  Pulling $model … "

  # Capture output + exit code so we can detect "already exists" cases
  pull_output=$(compose exec -T ollama ollama pull "$model" 2>&1) && pull_rc=$? || pull_rc=$?

  if [ "$pull_rc" -eq 0 ]; then
    # Ollama prints a success line like "success" when the pull completes
    if echo "$pull_output" | grep -qi "success"; then
      echo "✔ done"
    else
      echo "✔ done"
    fi
  else
    # Check for common "already exists" / success-in-spite-of-rc patterns
    if echo "$pull_output" | grep -qiE "already|exists"; then
      echo "✔ already present"
    else
      echo "✘ FAILED (exit $pull_rc)"
      echo "   $pull_output" | head -5 | sed 's/^/   /'
      failures=$((failures + 1))
    fi
  fi
done

echo "────────────────────────────────────────"
if [ $failures -gt 0 ]; then
  echo "✘ $failures model(s) failed to pull."
  exit 1
else
  echo "✔ All models pulled successfully."
fi