"""Note discovery and vault resolution for Synapse Ask.

Resolves the Obsidian vault path from the ``OBSIDIAN_VAULT_PATH`` environment
variable (typically set via ``.env``) and discovers local Markdown notes inside
it. When no configured vault exists or the path is invalid, falls back to the
bundled demo vault at ``examples/obsidian-vault`` and clearly labels the output
so operators always know which vault they are browsing.
"""

from __future__ import annotations

import os
from pathlib import Path

from .config import ROOT

DEMO_VAULT = ROOT / "examples" / "obsidian-vault"


def resolve_vault(vault_path: str | None = None) -> tuple[Path, str]:
    """Return ``(root, label)`` for the vault to browse.

    Resolution order:

    1. *vault_path* argument (used by tests)
    2. ``OBSIDIAN_VAULT_PATH`` environment variable
    3. Bundled demo vault at ``examples/obsidian-vault``

    The label is ``"Configured vault"`` when the vault comes from an explicit
    configuration (env var or argument) and ``"Demo vault"`` for the default
    demo fallback. If a configured path does not point to an existing directory,
    the function still returns the path so callers can surface a clear error;
    the label will note the problem.
    """
    if vault_path:
        root = Path(vault_path)
        if root.is_dir():
            return root, "Configured vault"
        return root, "Configured vault (path not found)"

    env_path = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if env_path:
        root = Path(env_path)
        if root.is_dir():
            return root, "Configured vault"
        return root, "Configured vault (path not found)"

    return DEMO_VAULT, "Demo vault"


def find_available_notes(
    notes_root: Path | None = None,
    query: str = "",
    limit: int = 12,
) -> list[Path]:
    """Discover local ``.md`` files under *notes_root*.

    If *notes_root* is ``None``, the vault is resolved via
    :func:`resolve_vault`. Results are sorted alphabetically by their
    relative path and capped at *limit* entries.
    """
    if notes_root is None:
        notes_root, _ = resolve_vault()
    if not notes_root.exists():
        return []
    query_lower = query.lower().strip()
    notes = [path for path in notes_root.rglob("*.md") if path.is_file()]
    if query_lower:
        notes = [
            path
            for path in notes
            if query_lower in path.name.lower()
            or query_lower in str(path.relative_to(notes_root)).lower()
        ]
    return sorted(notes, key=lambda path: str(path.relative_to(notes_root)).lower())[
        :limit
    ]


def format_local_notes(notes: list[Path], label: str, root: Path) -> str:
    """Render a readable local note listing with a vault provenance label.

    Paths are shown relative to *root* and never expose absolute filesystem
    details — only the relative path within the vault.
    """
    if not notes:
        return f"{label}: no Markdown notes found."
    lines = [f"{label}:"]
    for note in notes:
        try:
            rel = note.relative_to(root)
        except ValueError:
            rel = note.name
        lines.append(f"  {rel}")
    return "\n".join(lines)
