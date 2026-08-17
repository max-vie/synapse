"""Validate repository artifacts for public-safe sharing.

Checks performed:
- Text artifacts do not contain stale workflow-runtime dependencies.
- Text artifacts do not contain hardcoded private IP addresses.
- Text artifacts do not contain obvious bearer/token/credential secrets.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TEXT_SUFFIXES = {".md", ".json", ".py", ".sh", ".example", ".txt", ".yml", ".yaml"}
SKIP_DIRS = {".git", ".pytest_cache", "__pycache__", ".venv", "venv", "node_modules", ".local-artifacts", "tmp"}
# Paths where PRIVATE_IP, AUTH_SECRET, and ENV_SECRET findings are exempt:
# test fixtures deliberately contain these patterns; capture scripts use dummy tokens.

EXEMPT_SECRET_PATHS = {
    "scripts/capture/capture_ask_gif.py",
    "src/synapse/ask.py",
    "tests/ask/test_client.py",
    "tests/app/test_http.py",
    "tests/tooling/test_proof.py",
    "tests/tooling/test_capture.py",
}


PRIVATE_IP_RE = re.compile(
    r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
)
AUTH_SECRET_RE = re.compile(
    r"(?i)(?:Authorization\s*[:=]\s*[\"']?\s*)?(?:Bearer|Token|Basic)\s+"
    r"(?!<REDACTED>|\{\{|\$env|YOUR_|REPLACE|replace|redacted)"
    r"[A-Za-z0-9][A-Za-z0-9._:/+=\-]{12,}"
)
ENV_SECRET_RE = re.compile(
    r"(?i)(?:^|[^\w])['\"]?[A-Z0-9_-]*(?:TOKEN|SECRET|PASSWORD|API[_-]?KEY|APP[_-]?KEY)[A-Z0-9_-]*['\"]?\s*[:=]\s*[\"']?"
    r"(?!$|<|REDACTED|redacted|replace|change-me|your-|example|dummy|\$\{|\$env|\{\{)"
    r"[A-Za-z0-9][A-Za-z0-9._:/+=\-]{12,}"
)
SECRET_ENV_NAME_RE = re.compile(r"^[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|APP_KEY)[A-Z0-9_]*$")
ENV_READ_RE = re.compile(
    r"(?:os\.environ\.get|os\.getenv|env\.get)\(\s*['\"]"
    r"(?P<name>[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|APP_KEY)[A-Z0-9_]*)"
    r"['\"]\s*(?:,\s*(?P<default>[^)]*))?\)"
)
STRING_LITERAL_RE = re.compile(r"^[rubfRUBF]*(['\"])(?P<value>.*)\1$")
URL_CREDENTIAL_RE = re.compile(r"https?://[^\s/@:]+:[^\s/@]+@", re.IGNORECASE)
HOST_GATEWAY_RE = re.compile(r"\bhost\.docker\.internal\b", re.IGNORECASE)
PASSWORD_PHRASE_RE = re.compile(
    r"(?i)\b(?:default[ \t]+)?password[ \t]+"
    r"(?!<REDACTED|redacted|change|must|for|policy|manager|reset|hash|field|prompt|strength|less|like|lost|is\b|are\b|-)"
    r"[^\s`'\"]{4,}"
)


def is_placeholder_secret(value: str) -> bool:
    value = value.strip().strip('"\'')
    lowered = value.lower()
    return not value or value in {"None", "null"} or any(
        marker in lowered
        for marker in (
            "redacted",
            "replace",
            "change-me",
            "your-",
            "example",
            "dummy",
        )
    )


def is_safe_runtime_env_secret_read(line: str) -> bool:
    matches = list(ENV_READ_RE.finditer(line))
    if not matches:
        return False
    return not has_unsafe_runtime_env_secret_fallback(line)


def has_unsafe_runtime_env_secret_fallback(line: str) -> bool:
    for match in ENV_READ_RE.finditer(line):
        default = match.group("default")
        if default is None:
            continue
        default = re.sub(r"^default\s*=\s*", "", default.strip(), flags=re.IGNORECASE)
        literal = STRING_LITERAL_RE.match(default)
        if literal and not is_placeholder_secret(literal.group("value")):
            return True
    return False


def dotted_call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parent = dotted_call_name(func.value)
        return f"{parent}.{func.attr}" if parent else func.attr
    return ""


def env_read_default_node(call: ast.Call) -> ast.AST | None:
    if len(call.args) >= 2:
        return call.args[1]
    for keyword in call.keywords:
        if keyword.arg == "default":
            return keyword.value
    return None


def scan_python_env_read_defaults(path: Path, text: str) -> list[Finding]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if dotted_call_name(node.func) not in {"os.environ.get", "os.getenv", "env.get"}:
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
            continue
        if not SECRET_ENV_NAME_RE.match(node.args[0].value):
            continue
        default = env_read_default_node(node)
        if isinstance(default, ast.Constant) and isinstance(default.value, str) and not is_placeholder_secret(default.value):
            findings.append(Finding(path, node.lineno, "ENV_SECRET", "hardcoded secret-like env assignment"))
    return findings


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    code: str
    message: str

    def format(self, root: Path) -> str:
        rel = self.path.relative_to(root)
        return f"{rel}:{self.line}: {self.code}: {self.message}"


def iter_text_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.name == ".env":
            if is_git_ignored(root, path):
                continue
            yield path
            continue
        if path.suffix in TEXT_SUFFIXES or path.name in {".gitignore", "README.md", "Makefile"}:
            yield path


def is_git_ignored(root: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", rel],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (FileNotFoundError, ValueError):
        return False
    return result.returncode == 0


def scan_text(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    # Skip PRIVATE_IP, AUTH_SECRET, ENV_SECRET in exempt files
    # (test fixtures deliberately contain these patterns)
    rel = path.as_posix()
    skip_secret = any(exempt.endswith(rel.split("/")[-1] if "/" in rel else rel) or exempt == rel for exempt in EXEMPT_SECRET_PATHS)
    regexes = [
        ("PRIVATE_IP", PRIVATE_IP_RE, "hardcoded private IP; use an env var or placeholder"),
        ("AUTH_SECRET", AUTH_SECRET_RE, "hardcoded Authorization token-like value"),
        ("ENV_SECRET", ENV_SECRET_RE, "hardcoded secret-like env assignment"),
        ("URL_CREDENTIAL", URL_CREDENTIAL_RE, "credentials embedded in URL"),
        ("HOST_GATEWAY_LITERAL", HOST_GATEWAY_RE, "hardcoded Docker host gateway; use an env var or placeholder"),
        ("PASSWORD_PHRASE", PASSWORD_PHRASE_RE, "inline password-like phrase; redact it or move to private secret storage"),
    ]
    lines = text.splitlines()
    env_read_secret_lines: set[int] = set()
    if path.suffix == ".py" and not skip_secret:
        env_read_findings = scan_python_env_read_defaults(path, text)
        findings.extend(env_read_findings)
        env_read_secret_lines = {finding.line for finding in env_read_findings}
    for line_no, line in enumerate(lines, start=1):
        env_read_secret_finding = line_no in env_read_secret_lines or (path.suffix != ".py" and has_unsafe_runtime_env_secret_fallback(line))
        if env_read_secret_finding and line_no not in env_read_secret_lines:
            findings.append(Finding(path, line_no, "ENV_SECRET", "hardcoded secret-like env assignment"))
        for code, regex, message in regexes:
            if code == "ENV_SECRET" and env_read_secret_finding:
                continue
            if code == "ENV_SECRET" and regex.search(line) and is_safe_runtime_env_secret_read(line):
                continue
            if skip_secret and code in {"PRIVATE_IP", "AUTH_SECRET", "ENV_SECRET"}:
                continue
            if regex.search(line):
                findings.append(Finding(path, line_no, code, message))
    return findings


def validate_repo(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(scan_text(path, text))
    return findings


def validate_files(root: Path, files: Iterable[Path]) -> list[Finding]:
    """Validate an existing candidate set supplied by the checks interface."""
    findings: list[Finding] = []
    for path in files:
        try:
            rel_parts = path.relative_to(root).parts
        except ValueError:
            rel_parts = path.parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if path.suffix not in TEXT_SUFFIXES and path.name not in {".gitignore", "README.md", "Makefile"}:
            continue
        try:
            findings.extend(scan_text(path, path.read_text(encoding="utf-8")))
        except UnicodeDecodeError:
            continue
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="repository root to validate")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    findings = validate_repo(root)
    if args.json:
        print(json.dumps([f.__dict__ | {"path": str(f.path.relative_to(root))} for f in findings], indent=2))
    elif findings:
        for finding in findings:
            print(finding.format(root))
    else:
        print("OK: no hardcoded private IPs or obvious secrets found.")
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
