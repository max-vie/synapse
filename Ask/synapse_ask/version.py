"""Synapse Ask version.

The version string is the single source of truth for the entire project.
It is read from the ``VERSION`` file at the repository root so that the
Synapse API service and the Ask CLI/TUI always report the same version.

To bump the version, edit ``VERSION`` at the repo root — do not edit this
file.
"""

from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # repo root
_VERSION_FILE = _ROOT / "VERSION"


def _read_version() -> str:
    """Read the version from the repo-root VERSION file.

    Falls back to a development marker if the file is missing (e.g. when
    installed as a standalone package without the repo checkout).
    """
    try:
        return _VERSION_FILE.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return "0.0.0+dev"


APP_VERSION = _read_version()