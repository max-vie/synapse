"""Safe `.env` creation and update helpers for local tooling."""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path
from typing import Mapping


class EnvFileError(ValueError):
    """Raised when a local environment file is missing or malformed."""


def parse_value(raw: str) -> str:
    raw = raw.strip()
    if not raw:
        return ""
    if raw[0] in {'"', "'"}:
        quote = raw[0]
        end = raw.find(quote, 1)
        return raw[1:] if end < 0 else raw[1:end]
    comment = raw.find("#")
    return (raw if comment < 0 else raw[:comment]).strip()


def load(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise EnvFileError(f"missing {path}; run make lab-up first")
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip():
            values[key.strip()] = parse_value(value)
    return values


def _atomic_write(path: Path, text: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def create_from_template(template: Path, destination: Path, *, force: bool = False) -> bool:
    """Create a private environment file; return False when it already exists."""
    if destination.exists() and not force:
        return False
    text = template.read_text(encoding="utf-8")
    output: list[str] = []
    for line in text.splitlines():
        if line.startswith("SYNAPSE_WEBHOOK_AUTH_TOKEN="):
            line = f"SYNAPSE_WEBHOOK_AUTH_TOKEN={secrets.token_urlsafe(48)}"
        elif line.startswith("WIKIJS_DB_PASSWORD="):
            line = f"WIKIJS_DB_PASSWORD={secrets.token_urlsafe(24)}"
        output.append(line)
    _atomic_write(destination, "\n".join(output) + "\n")
    return True


def write_values(path: Path, updates: Mapping[str, str], *, destination: Path | None = None) -> Path:
    """Update keys while preserving comments and unrelated values."""
    lines = path.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    output: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in remaining:
                output.append(f"{key}={remaining.pop(key)}")
                continue
        output.append(line)
    output.extend(f"{key}={value}" for key, value in remaining.items())
    target = destination or path
    _atomic_write(target, "\n".join(output) + "\n")
    return target
