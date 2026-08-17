"""Validated, secret-safe application configuration."""

from __future__ import annotations

import os
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

_SECRET_MARKERS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "APP_KEY")
_FILE_BACKED_SECRETS = (
    "SYNAPSE_WEBHOOK_AUTH_TOKEN",
    "WIKIJS_API_TOKEN",
    "WIKIJS_DB_PASSWORD",
)


@dataclass(frozen=True, repr=False)
class Settings(Mapping[str, str]):
    """Read-only configuration mapping used across the application interface."""

    values: Mapping[str, str]

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> "Settings":
        resolved = dict(os.environ if values is None else values)
        for key in _FILE_BACKED_SECRETS:
            file_path = str(resolved.get(f"{key}_FILE") or "").strip()
            if not file_path:
                continue
            try:
                file_value = Path(file_path).read_text(encoding="utf-8").strip()
            except OSError:
                file_value = ""
            if file_value:
                resolved[key] = file_value
        return cls(resolved)

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.values)

    def __len__(self) -> int:
        return len(self.values)

    def __repr__(self) -> str:
        safe = {
            key: "[REDACTED]" if any(marker in key for marker in _SECRET_MARKERS) and value else value
            for key, value in self.values.items()
        }
        return f"Settings({safe!r})"

    def integer(self, key: str, default: int, *, minimum: int | None = None) -> int:
        try:
            value = int(float(self.get(key, str(default))))
        except (TypeError, ValueError):
            value = default
        return max(minimum, value) if minimum is not None else value

    def boolean(self, key: str, default: bool = False) -> bool:
        raw = self.get(key)
        if raw is None:
            return default
        return raw.strip().casefold() in {"1", "true", "yes", "on"}

    def validate(self) -> None:
        if not self.boolean("SYNAPSE_AUTH_DISABLED") and not self.get("SYNAPSE_WEBHOOK_AUTH_TOKEN", ""):
            raise ValueError("SYNAPSE_WEBHOOK_AUTH_TOKEN or SYNAPSE_WEBHOOK_AUTH_TOKEN_FILE is required unless SYNAPSE_AUTH_DISABLED=true")
        for key in (
            "QDRANT_BASE_URL",
            "OLLAMA_INTERNAL_BASE_URL",
            "OLLAMA_CHAT_BASE_URL",
            "WIKIJS_BASE_URL",
        ):
            value = self.get(key, "")
            if not value:
                continue
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"{key} must be an HTTP URL")
            if parsed.username or parsed.password:
                raise ValueError(f"{key} must not contain URL credentials")
