#!/usr/bin/env python3
"""Check local Markdown links without requiring network access."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
EXTERNAL_SCHEMES = {"http", "https", "mailto", "tel"}


def tracked_markdown_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(
            ["git", "ls-files", "*.md"], cwd=root, text=True, stderr=subprocess.DEVNULL
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(path for path in root.rglob("*.md") if ".git" not in path.parts)
    return [path for line in output.splitlines() if line and (path := root / line).exists()]


def github_anchor(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"[`*_~]", "", text).strip().lower()
    text = re.sub(r"[^a-z0-9\s-]", "", text)
    text = re.sub(r"[\s-]+", "-", text).strip("-")
    return text


def anchors_for(path: Path) -> set[str]:
    anchors: set[str] = set()
    seen: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING_RE.match(line)
        if not match:
            continue
        base = github_anchor(match.group(2))
        if not base:
            continue
        count = seen.get(base, 0)
        seen[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def check_link(root: Path, source: Path, raw_target: str) -> str | None:
    parsed = urlparse(raw_target)
    if parsed.scheme in EXTERNAL_SCHEMES:
        return None
    if raw_target.startswith("#"):
        target_path = source
        fragment = raw_target[1:]
    else:
        target, _, fragment = raw_target.partition("#")
        if not target or target.startswith("//"):
            return None
        target_path = (source.parent / unquote(target)).resolve()
        try:
            target_path.relative_to(root)
        except ValueError:
            return f"escapes repository: {raw_target}"
        if not target_path.exists():
            return f"missing file: {raw_target}"
        if target_path.is_dir():
            target_path = target_path / "README.md"
            if not target_path.exists():
                return f"directory has no README.md: {raw_target}"
    if fragment and target_path.suffix.lower() == ".md":
        wanted = unquote(fragment).lower()
        if wanted not in anchors_for(target_path):
            return f"missing anchor: {raw_target}"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    failures: list[str] = []

    for path in tracked_markdown_files(root):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in LINK_RE.finditer(line):
                target = match.group(1).strip()
                error = check_link(root, path.resolve(), target)
                if error:
                    failures.append(f"{path.relative_to(root)}:{line_number}: {error}")

    if failures:
        print("Markdown link check failed:", file=sys.stderr)
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("OK: Markdown links point to existing local files and anchors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
