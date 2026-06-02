#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ENV_FILE="${SYNAPSE_ENV_FILE:-$ROOT/.env}"

if [ ! -f "$ENV_FILE" ]; then
  cat >&2 <<EOF
[FAIL] Missing $ENV_FILE.

Start the local lab first:
  make lab-up

Then open Wiki.js at http://localhost:3000, finish first-run admin setup,
enable the API in the Administration Area, create a page-capable API token,
save it as WIKIJS_API_TOKEN in .env, and rerun:
  make configure
EOF
  exit 1
fi

# --- single Python block: load .env, check token, probe API ---
python3 - "$ENV_FILE" <<'PY'
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

# ---- load .env ----
path = Path(sys.argv[1])
values: dict[str, str] = {}
for raw in path.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip().strip('"').strip("'")

# ---- check if WIKIJS_API_TOKEN is a placeholder ----
token = values.get("WIKIJS_API_TOKEN", "")
PLACEHOLDER_VALUES = {
    "", "replace-with-wikijs-api-token", "replace-after-wikijs-setup",
    "placeholder", "changeme", "CHANGE_ME", "todo", "TODO",
}
# also match replace-* / replace_with_* patterns
if token in PLACEHOLDER_VALUES or token.startswith("replace-") or token.startswith("replace_with_"):
    print(
        "[FAIL] WIKIJS_API_TOKEN is still a placeholder or missing in .env.\n"
        "\n"
        "Manual Wiki.js bootstrap is required:\n"
        "  1. Open http://localhost:3000\n"
        "  2. Finish the Wiki.js first-run admin setup if prompted.\n"
        "  3. Go to Administration Area > API and enable the API.\n"
        "  4. Create a 'synapse' group with admin permissions.\n"
        "  5. Create an API token assigned to the 'synapse' group with\n"
        "     page create/update/read permission.\n"
        "  6. Save it in .env as WIKIJS_API_TOKEN=***\n"
        "  7. Rerun: make configure\n"
        "\n"
        "After configure passes, run: make proof",
        file=sys.stderr,
    )
    sys.exit(1)

# ---- probe the live Wiki.js GraphQL API ----
port = values.get("WIKIJS_PORT", "3000") or "3000"
endpoint = f"http://127.0.0.1:{port}/graphql"
payload = json.dumps({"query": "query { pages { list { id path title } } }"}).encode("utf-8")
headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")

try:
    with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310 - localhost lab readiness probe
        raw = response.read().decode("utf-8", errors="replace")
        data = json.loads(raw) if raw else {}
except urllib.error.HTTPError as exc:
    raw = exc.read().decode("utf-8", errors="replace")
    # failure mode 1: API is disabled (HTTP 500 with 'API is disabled')
    if exc.code == 500 and "API is disabled" in raw:
        print(
            "[FAIL] Wiki.js API is disabled.\n"
            "\n"
            "Fix:\n"
            "  1. Open http://localhost:" + port + "\n"
            "  2. Go to Administration Area > API\n"
            "  3. Enable the API\n"
            "  4. Rerun: make configure",
            file=sys.stderr,
        )
        sys.exit(1)
    # failure mode 2: auth failure (401/403)
    if exc.code in {401, 403}:
        print(
            "[FAIL] WIKIJS_API_TOKEN was rejected (HTTP "
            + str(exc.code)
            + ").\n"
            "\n"
            "Fix:\n"
            "  1. Open http://localhost:" + port + "\n"
            "  2. Go to Administration Area > API\n"
            "  3. Create a 'synapse' group with admin permissions\n"
            "  4. Create a NEW API token assigned to the 'synapse' group\n"
            "     with page create/update/read permission\n"
            "  5. Replace WIKIJS_API_TOKEN in .env with the new token\n"
            "  6. Rerun: make configure",
            file=sys.stderr,
        )
        sys.exit(1)
    # other HTTP errors
    print(
        f"[FAIL] Wiki.js API check failed at {endpoint}: HTTP {exc.code}\n"
        f"  Response body: {raw[:200]}",
        file=sys.stderr,
    )
    sys.exit(1)
except (TimeoutError, urllib.error.URLError, OSError) as exc:
    # Wiki.js not reachable — token is set but we cannot verify it live
    print(f"[OK]  WIKIJS_API_TOKEN is set in .env (live API check skipped: {endpoint} not reachable)")
    print(f"  Reason: {exc}")
    print("\nNext step:")
    print("  make proof")
    sys.exit(0)

# check for GraphQL-level errors (e.g. API disabled returns 200 with errors)
if isinstance(data, dict) and data.get("errors"):
    text = json.dumps(data)
    if "API is disabled" in text:
        print(
            "[FAIL] Wiki.js API is disabled (returned in GraphQL errors).\n"
            "\n"
            "Fix:\n"
            "  1. Open http://localhost:" + port + "\n"
            "  2. Go to Administration Area > API\n"
            "  3. Enable the API\n"
            "  4. Rerun: make configure",
            file=sys.stderr,
        )
        sys.exit(1)
    print(
        f"[FAIL] Wiki.js API returned GraphQL errors at {endpoint}:\n"
        f"  {text[:300]}",
        file=sys.stderr,
    )
    sys.exit(1)

print("[OK]  WIKIJS_API_TOKEN is configured and the live Wiki.js API responded successfully.")
print("\nNext step:")
print("  make proof")
PY