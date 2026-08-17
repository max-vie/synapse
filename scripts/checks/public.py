"""Public-facing claim and path checks for repository files.

This is stricter than the workflow validator and focuses on public-release polish:
- no tracked or untracked public env files with real values
- no private IPs or local absolute home paths
- no public-ingress wildcard/all-interface bind examples
- no stale production/enterprise overclaims outside explicit non-claim text
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TEXT_SUFFIXES = {".md", ".json", ".py", ".sh", ".txt", ".yml", ".yaml", ".example", ".svg"}
TEXT_NAMES = {"README.md", "Makefile", ".gitignore"}
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", "venv", "node_modules", ".local-artifacts", "tmp"}
# Paths exempt from PRIVATE_IP, LOCAL_PATH, AUTH_SECRET, ENV_SECRET checks:
# test files deliberately contain these patterns for their own validation.
HYGIENE_EXEMPT_PATHS = {
    "scripts/capture/capture_ask_gif.py",
    "src/synapse/ask.py",
    "tests/ask/test_client.py",
    "tests/app/test_http.py",
    "tests/tooling/test_proof.py",
}


PRIVATE_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
LOCAL_HOME_RE = re.compile(r"/(?:home|Users)/(?!node(?:/|$))[A-Za-z0-9._-]+")
PUBLIC_BIND_RE = re.compile(r"\b0\.0\.0\.0\b")
URL_CREDENTIAL_RE = re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
CLAIM_RE = re.compile(
    r"(?i)\b(?:production[- ]ready|enterprise[- ]ready|commercial\s+(?:product|SaaS)|customer[- ]ready|run in production|managed service|production\s+SaaS|public\s+SaaS|enterprise\s+customers?|customer\s+deployments?)\b"
)
NON_CLAIM_RE = re.compile(r"(?i)\b(?:not|no|avoid|must not|do not claim|does not claim|is not|not a goal|not presented as)\b")
CLAIM_PROMPT_RE = re.compile(r"(?i)\b(?:unsupported claim|claim prompt|refuse (?:this|the) unsupported)\b")
CLAIM_EXEMPT_PREFIXES = ("scripts/benchmark/fixtures/",)
CLAIM_EXEMPT_PATHS = {"scripts/proof/scoring.py", "scripts/proof/scenarios.py"}
CLAIM_EXEMPT_FIELD_PATHS = {"scripts/proof/runner.py"}


def relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def is_claim_fixture_or_detector(root: Path, path: Path, line: str) -> bool:
    rel = relative_posix(root, path)
    return (
        rel in CLAIM_EXEMPT_PATHS
        or any(rel.startswith(prefix) for prefix in CLAIM_EXEMPT_PREFIXES)
        or (rel in CLAIM_EXEMPT_FIELD_PATHS and ("forbidden_facts" in line or "required_facts" in line))
    )


def is_non_claim_text(root: Path, path: Path, line: str) -> bool:
    saw_claim = False
    for match in CLAIM_RE.finditer(line):
        saw_claim = True
        before = line[: match.start()].casefold()
        clause = re.split(r"[.;:,]", before)[-1][-100:]
        negated_claim_context = (
            "does not claim" in clause
            or "do not claim" in clause
            or "not presented as" in clause
            or re.search(r"\b(?:not|no|avoid|must not|is not)\b(?:\W+\w+){0,6}\W*$", clause) is not None
        )
        if negated_claim_context:
            continue
        return False
    if saw_claim:
        return True
    return False


def is_allowed_public_bind_literal(root: Path, path: Path, line: str) -> bool:
    return relative_posix(root, path) == "scripts/benchmark/ollama_models.py" and "_LOCAL_HOSTS" in line


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    message: str

    def format(self, root: Path) -> str:
        return f"{self.path.relative_to(root)}:{self.line}: {self.code}: {self.message}"


def candidate_files(root: Path) -> list[Path]:
    try:
        tracked = subprocess.run(
            ["git", "ls-files"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.splitlines()
        return sorted({path for line in tracked + untracked if line and (path := root / line).exists()})
    except (subprocess.CalledProcessError, FileNotFoundError):
        return [p for p in root.rglob("*") if p.is_file() and p.name != ".env"]


def is_text_candidate(root: Path, path: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    if any(part in SKIP_DIRS for part in rel_parts):
        return False
    return path.suffix in TEXT_SUFFIXES or path.name in TEXT_NAMES


def scan_file(root: Path, path: Path) -> list[Finding]:
    findings: list[Finding] = []
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return findings

    rel = relative_posix(root, path)
    skip_hygiene = rel in HYGIENE_EXEMPT_PATHS

    for line_no, line in enumerate(text.splitlines(), start=1):
        if path.name == "public.py" and path.parent.name == "checks" and (
            "production[- ]ready" in line
            or "commercial\\s+" in line
            or "commercial product" in line
            or "managed service" in line
            or "production\\s+SaaS" in line
            or "public\\s+SaaS" in line
            or "enterprise\\s+customers" in line
            or "customer\\s+deployments" in line
        ):
            continue
        if PRIVATE_IP_RE.search(line) and not skip_hygiene:
            findings.append(Finding(path, line_no, "PRIVATE_IP", "replace concrete private IPs with placeholders"))
        if LOCAL_HOME_RE.search(line) and not skip_hygiene:
            findings.append(Finding(path, line_no, "LOCAL_PATH", "replace local absolute home paths with <REPO_ROOT> or placeholders"))
        if PUBLIC_BIND_RE.search(line) and not is_allowed_public_bind_literal(root, path, line):
            findings.append(Finding(path, line_no, "PUBLIC_BIND", "avoid public wildcard/all-interface bind examples in public docs/scripts"))
        if URL_CREDENTIAL_RE.search(line):
            findings.append(Finding(path, line_no, "URL_CREDENTIAL", "credentials embedded in URL"))
        if CLAIM_RE.search(line) and not is_non_claim_text(root, path, line) and not is_claim_fixture_or_detector(root, path, line):
            findings.append(Finding(path, line_no, "OVERCLAIM", "public repo should avoid production/enterprise/commercial claims"))
    return findings


def tracked_env_files(root: Path, files: Iterable[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.name.startswith(".env") and path.name not in {".env.example"}:
            findings.append(Finding(path, 1, "TRACKED_ENV", f"unexpected tracked env file: {rel}"))
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    files = candidate_files(root)
    findings = tracked_env_files(root, files)
    for path in files:
        if is_text_candidate(root, path):
            findings.extend(scan_file(root, path))

    if findings:
        for finding in findings:
            print(finding.format(root))
        return 1

    print("OK: public repository hygiene checks passed for tracked and nonignored untracked files.")
    print("OK: no real env files found in public candidates; only sanitized env examples are allowed.")
    print("OK: no concrete private IPs, local home paths, URL credentials, public bind examples, or unbounded production/enterprise claims found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
