#!/usr/bin/env python3
"""Fail if active repository artifacts still reference the removed publisher."""
from __future__ import annotations

import sys
from pathlib import Path

REMOVED_TERMS = ("BookStack", "BOOKSTACK", "bookstack")
SKIP_DIRS = {".git", ".local-artifacts", ".pytest_cache", "__pycache__", ".venv", "venv", "node_modules", "tmp"}
SKIP_FILES = {Path("tests/test_rag_grounding_regressions.py"), Path("scripts/check_removed_publisher.py")}
TEXT_SUFFIXES = {".md", ".json", ".py", ".sh", ".example", ".txt", ".yml", ".yaml"}


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    findings: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts) or rel in SKIP_FILES:
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {"README.md", "SECURITY.md", ".env.example"}:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if any(term in line for term in REMOVED_TERMS):
                findings.append(f"{rel}:{line_no}: removed publisher reference")
    if findings:
        print("Removed publisher references remain:")
        print("\n".join(findings))
        return 1
    print("OK: no removed publisher references in active artifacts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
