#!/usr/bin/env bash
set -euo pipefail

output_dir="${1:-.local-artifacts/sbom}"
trivy_image="${TRIVY_IMAGE:-aquasec/trivy:0.66.0}"
trivy_exit_code="${TRIVY_EXIT_CODE:-0}"
cache_dir="${TRIVY_CACHE_DIR:-${HOME}/.cache/trivy}"

mkdir -p "$output_dir" "$cache_dir"
output_dir="$(realpath "$output_dir")"
if [[ "$output_dir" == "$PWD"/* ]]; then
  output_mount=(-v "$PWD:/work:Z")
  output_root="/work/${output_dir#"$PWD"/}"
else
  output_mount=(-v "$output_dir:/output:Z")
  output_root=/output
fi

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
image_tar_dir="$output_dir/.image-tars"
mkdir -p "$image_tar_dir"
trap 'rm -rf "$image_tar_dir"' EXIT

if printf '%s\n' "${images[@]}" | grep -qx 'synapse-service:local'; then
  echo "Building local Synapse image before scanning"
  docker build --provenance=false -t synapse-service:local -f Dockerfile .
fi

for image in "${images[@]}"; do
  if [[ "$image" != synapse-service:* ]]; then
    docker pull "$image" >/dev/null
  fi
  safe_name="${image//\//_}"
  safe_name="${safe_name//:/_}"
  sbom_path="$output_dir/${safe_name}.cdx.json"
  image_tar="$image_tar_dir/${safe_name}.tar"

  echo "Generating SBOM for $image -> $sbom_path"
  docker save "$image" -o "$image_tar"
  docker run --rm \
    "${output_mount[@]}" \
    -v "$cache_dir:/root/.cache:Z" \
    "$trivy_image" \
    image \
    --format cyclonedx \
    --output "$output_root/${safe_name}.cdx.json" \
    --input "$output_root/.image-tars/${safe_name}.tar"

  echo "Scanning $image for HIGH/CRITICAL findings"
  if ! docker run --rm \
    "${output_mount[@]}" \
    -v "$cache_dir:/root/.cache:Z" \
    "$trivy_image" \
    image \
    --severity HIGH,CRITICAL \
    --exit-code "$trivy_exit_code" \
    --ignore-unfixed \
    --input "$output_root/.image-tars/${safe_name}.tar"; then
    scan_status=1
  fi
  rm -f "$image_tar"
done

exit "$scan_status"
