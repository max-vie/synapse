"""Configuration and project-path helpers for Synapse Ask."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _parse_env_value(raw: str) -> str:
    """Parse the value side of a KEY=VALUE .env line.

    Supports:
    - Unquoted: ``FOO=bar`` → bar
    - Double-quoted: ``FOO="bar baz"`` → bar baz  (strips quotes, preserves inner spaces)
    - Single-quoted: ``FOO='bar baz'`` → bar baz
    - Inline comments outside quotes: ``FOO=bar # comment`` → bar
    - Inline comments inside quotes are preserved: ``FOO="bar # baz"`` → bar # baz
    """
    raw = raw.strip()
    if not raw:
        return ""

    if raw.startswith('"'):
        # Double-quoted: find matching close quote; comments after are stripped.
        end = raw.find('"', 1)
        if end == -1:
            # Unterminated quote — treat rest as the value (lenient).
            return raw[1:]
        return raw[1:end]
    if raw.startswith("'"):
        end = raw.find("'", 1)
        if end == -1:
            return raw[1:]
        return raw[1:end]

    # Unquoted: strip inline comment (# not inside quotes).
    comment_idx = raw.find("#")
    if comment_idx != -1:
        raw = raw[:comment_idx]
    return raw.strip()


def load_dotenv(env_path: Path | None = None) -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ if not already set.

    Shell environment variables always take precedence over .env values.
    Supports ``KEY=VALUE``, ``export KEY=VALUE``, double/single-quoted values,
    inline comments outside quotes, blank lines, and ``#`` comment lines.
    """
    if env_path is None:
        env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Strip optional ``export `` prefix.
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = _parse_env_value(value)
        if key and key not in os.environ:
            os.environ[key] = value
    for key in ("SYNAPSE_WEBHOOK_AUTH_TOKEN", "WIKIJS_API_TOKEN", "WIKIJS_DB_PASSWORD"):
        if key in os.environ and os.environ[key]:
            continue
        file_path = os.environ.get(f"{key}_FILE", "")
        if not file_path:
            continue
        path = Path(file_path)
        if not path.is_absolute():
            path = env_path.parent / path
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            os.environ[key] = value


# Backward-compatible internal name used by older tests/imports.
_load_dotenv = load_dotenv
