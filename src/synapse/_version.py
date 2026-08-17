"""Project version sourced from the repository VERSION file or package metadata."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _read_version() -> str:
    try:
        return version("synapse-local-lab")
    except PackageNotFoundError:
        version_file = Path(__file__).resolve().parents[2] / "VERSION"
        try:
            return version_file.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            return "0.0.0+dev"


__version__ = _read_version()
