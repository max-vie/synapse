#!/usr/bin/env bash
set -euo pipefail

output_dir="${1:-.local-artifacts/sbom}"
trivy_image="${TRIVY_IMAGE:-aquasec/trivy:0.66.0}"
trivy_exit_code="${TRIVY_EXIT_CODE:-0}"
cache_dir="${TRIVY_CACHE_DIR:-${HOME}/.cache/trivy}"

mkdir -p "$output_dir" "$cache_dir"

mapfile -t images < <(
  python3 - <<'PY'
import json
import subprocess

report = json.loads(
    subprocess.check_output(
        ["python3", "-m", "scripts.checks", "images", "--offline-fixture", "--format", "json"],
        text=True,
    )
)
for image in sorted({item["pinned"] for item in report["images"]}):
    print(image)
PY
)

if [ "${#images[@]}" -eq 0 ]; then
  echo "no pinned images found" >&2
  exit 2
fi

scan_status=0

for image in "${images[@]}"; do
  # Skip locally-built images that cannot be pulled in CI (no registry prefix)
  if [[ "$image" != */* ]]; then
    echo "Skipping local-only image: $image"
    continue
  fi
  safe_name="${image//\//_}"
  safe_name="${safe_name//:/_}"
  sbom_path="$output_dir/${safe_name}.cdx.json"

  echo "Generating SBOM for $image -> $sbom_path"
  docker run --rm \
    -v "$PWD:/work:Z" \
    -v "$cache_dir:/root/.cache:Z" \
    "$trivy_image" \
    image \
    --format cyclonedx \
    --output "/work/$sbom_path" \
    "$image"

  echo "Scanning $image for HIGH/CRITICAL findings"
  if ! docker run --rm \
    -v "$PWD:/work:Z" \
    -v "$cache_dir:/root/.cache:Z" \
    "$trivy_image" \
    image \
    --severity HIGH,CRITICAL \
    --exit-code "$trivy_exit_code" \
    --ignore-unfixed \
    "$image"; then
    scan_status=1
  fi
done

exit "$scan_status"
