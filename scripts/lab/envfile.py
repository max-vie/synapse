"""Safe `.env` creation and update helpers for local tooling."""

from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path
from typing import Mapping


class EnvFileError(ValueError):
    """Raised when a local environment file is missing or malformed."""


SECRET_FILES = {
    "SYNAPSE_WEBHOOK_AUTH_TOKEN": "synapse_webhook_auth_token",
    "WIKIJS_DB_PASSWORD": "wikijs_db_password",
    "WIKIJS_API_TOKEN": "wikijs_api_token",
}
SECRET_DIR_KEY = "SYNAPSE_SECRET_DIR"
SECRET_FILE_MODE = 0o640
SECRET_DIR_MODE = 0o700


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


def _secret_dir(values: Mapping[str, str], *, env_path: Path) -> Path:
    raw = str(values.get(SECRET_DIR_KEY) or "secrets").strip()
    directory = Path(raw)
    return directory if directory.is_absolute() else env_path.parent / directory


def _secret_path(values: Mapping[str, str], key: str, *, env_path: Path) -> Path:
    explicit = str(values.get(f"{key}_FILE") or "").strip()
    if explicit:
        path = Path(explicit)
        return path if path.is_absolute() else env_path.parent / path
    return _secret_dir(values, env_path=env_path) / SECRET_FILES[key]


def write_secret(path: Path, key: str, value: str) -> Path:
    """Write one managed secret and update the environment file to reference it."""
    if key not in SECRET_FILES:
        raise EnvFileError(f"unsupported managed secret: {key}")
    values = load(path)
    secret_path = _secret_path(values, key, env_path=path)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(secret_path.parent, SECRET_DIR_MODE)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    _atomic_write(secret_path, f"{value.rstrip(chr(10))}\n", mode=SECRET_FILE_MODE)
    updates = {
        SECRET_DIR_KEY: str(_secret_dir(values, env_path=path)),
        f"{key}_FILE": str(secret_path),
        key: "",
    }
    write_values(path, updates)
    return secret_path


def migrate_legacy_secrets(path: Path) -> bool:
    """Move inline legacy secrets into ignored files; return whether the env changed."""
    values = load(path)
    changed = False
    secret_dir = _secret_dir(values, env_path=path)
    secret_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secret_dir, SECRET_DIR_MODE)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    updates: dict[str, str] = {
        SECRET_DIR_KEY: str(secret_dir),
        "SYNAPSE_CONTAINER_UID": str(values.get("SYNAPSE_CONTAINER_UID") or os.getuid()),
        "SYNAPSE_CONTAINER_GID": str(values.get("SYNAPSE_CONTAINER_GID") or os.getgid()),
    }
    for key in SECRET_FILES:
        value = str(values.get(key) or "")
        secret_path = _secret_path(values, key, env_path=path)
        if value and (not secret_path.exists() or not secret_path.read_text(encoding="utf-8").strip()):
            _atomic_write(secret_path, f"{value}\n", mode=SECRET_FILE_MODE)
            changed = True
        if values.get(f"{key}_FILE") != str(secret_path):
            changed = True
        if value:
            changed = True
        updates[f"{key}_FILE"] = str(secret_path)
        updates[key] = ""
    if changed or SECRET_DIR_KEY not in values or "SYNAPSE_CONTAINER_UID" not in values or "SYNAPSE_CONTAINER_GID" not in values:
        write_values(path, updates)
    return changed


def resolve_secret_values(values: Mapping[str, str], *, env_path: Path | None = None) -> dict[str, str]:
    """Return environment values with managed file-backed secrets loaded."""
    resolved = dict(values)
    anchor = (env_path or Path.cwd() / ".env").resolve()
    for key in SECRET_FILES:
        path = _secret_path(resolved, key, env_path=anchor)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value:
            resolved[key] = value
    return resolved


def create_from_template(template: Path, destination: Path, *, force: bool = False) -> bool:
    """Create private configuration and file-backed secrets from the template.

    Existing files are preserved unless forced. Secret values never pass through
    the generated environment text; only their protected file paths do.
    """
    if destination.exists() and not force:
        return False
    template_text = template.read_text(encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    template_values = load(template)
    secret_dir = destination.parent / "secrets"
    secret_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(secret_dir, SECRET_DIR_MODE)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions
    output_lines: list[str] = []
    secret_dir_seen = False
    secret_keys_seen: set[str] = set()
    container_uid_seen = False
    container_gid_seen = False
    # Phase 1: preserve template order while replacing managed values in place.
    for line in template_text.splitlines():
        stripped = line.strip()
        if stripped.startswith(f"{SECRET_DIR_KEY}="):
            line = f"{SECRET_DIR_KEY}={secret_dir}"
            secret_dir_seen = True
        elif stripped.startswith("SYNAPSE_CONTAINER_UID="):
            line = f"SYNAPSE_CONTAINER_UID={os.getuid()}"
            container_uid_seen = True
        elif stripped.startswith("SYNAPSE_CONTAINER_GID="):
            line = f"SYNAPSE_CONTAINER_GID={os.getgid()}"
            container_gid_seen = True
        for key, filename in SECRET_FILES.items():
            if stripped.startswith(f"{key}="):
                secret_keys_seen.add(key)
                value = template_values.get(key, "")
                if key == "SYNAPSE_WEBHOOK_AUTH_TOKEN":
                    value = secrets.token_urlsafe(48)
                elif key == "WIKIJS_DB_PASSWORD":
                    value = secrets.token_urlsafe(24)
                elif not value:
                    value = "replace-after-wikijs-admin-setup"
                _atomic_write(secret_dir / filename, f"{value}\n", mode=SECRET_FILE_MODE)
                line = f"{key}_FILE={secret_dir / filename}"
                break
            if stripped.startswith(f"{key}_FILE="):
                secret_keys_seen.add(key)
                value = template_values.get(key, "")
                if key == "SYNAPSE_WEBHOOK_AUTH_TOKEN":
                    value = secrets.token_urlsafe(48)
                elif key == "WIKIJS_DB_PASSWORD":
                    value = secrets.token_urlsafe(24)
                elif not value:
                    value = "replace-after-wikijs-admin-setup"
                _atomic_write(secret_dir / filename, f"{value}\n", mode=SECRET_FILE_MODE)
                line = f"{key}_FILE={secret_dir / filename}"
                break
        output_lines.append(line)

    # Phase 2: append required managed values missing from an older template.
    if not secret_dir_seen:
        output_lines.append(f"{SECRET_DIR_KEY}={secret_dir}")
    if not container_uid_seen:
        output_lines.append(f"SYNAPSE_CONTAINER_UID={os.getuid()}")
    if not container_gid_seen:
        output_lines.append(f"SYNAPSE_CONTAINER_GID={os.getgid()}")
    for key, filename in SECRET_FILES.items():
        if key in secret_keys_seen:
            continue
        value = "replace-after-wikijs-admin-setup"
        if key == "SYNAPSE_WEBHOOK_AUTH_TOKEN":
            value = secrets.token_urlsafe(48)
        elif key == "WIKIJS_DB_PASSWORD":
            value = secrets.token_urlsafe(24)
        _atomic_write(secret_dir / filename, f"{value}\n", mode=SECRET_FILE_MODE)
        output_lines.append(f"{key}_FILE={secret_dir / filename}")
    _atomic_write(destination, "\n".join(output_lines) + "\n")
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
