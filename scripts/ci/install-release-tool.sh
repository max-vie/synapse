#!/usr/bin/env bash
set -euo pipefail

if [ "$#" -ne 6 ]; then
  echo "usage: $0 <owner/repo> <version> <asset> <sha256> <binary> <destination-dir>" >&2
  exit 2
fi

repo="$1"
version="$2"
asset="$3"
expected_sha256="$4"
binary="$5"
destination_dir="$6"

case "$repo" in
  gitleaks/gitleaks|rhysd/actionlint) ;;
  *)
    echo "unsupported release tool: $repo" >&2
    exit 2
    ;;
esac

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

archive="$tmp_dir/$asset"
extract_dir="$tmp_dir/extract"
url="https://github.com/$repo/releases/download/v$version/$asset"

mkdir -p "$extract_dir" "$destination_dir"
curl --proto '=https' --tlsv1.2 --retry 3 -sSfL "$url" -o "$archive"
printf '%s  %s\n' "$expected_sha256" "$archive" | sha256sum --check --status
tar -xzf "$archive" -C "$extract_dir" "$binary"
install -m 0755 "$extract_dir/$binary" "$destination_dir/$binary"
"$destination_dir/$binary" --version || "$destination_dir/$binary" version
