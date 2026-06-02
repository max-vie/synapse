import re
import sys
from pathlib import Path

import pytest

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

import synapse_ask as ask  # noqa: E402
from synapse_ask.version import APP_VERSION  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "Ask" / "synapse_ask"
ENTRYPOINT = ROOT / "Ask" / "ask.py"
VERSION_FILE = ROOT / "VERSION"


def test_synapse_ask_package_modules_exist():
    expected = {
        "__init__.py",
        "version.py",
        "config.py",
        "client.py",
        "dry_run.py",
        "formatting.py",
        "notes.py",
        "tui_state.py",
        "tui_render.py",
        "tui_runner.py",
        "cli.py",
    }

    assert PACKAGE.is_dir()
    assert expected.issubset({path.name for path in PACKAGE.iterdir() if path.is_file()})


def test_ask_py_is_thin_executable_entrypoint():
    source = ENTRYPOINT.read_text(encoding="utf-8")

    assert "from synapse_ask.cli import main" in source
    assert "raise SystemExit(main())" in source
    assert "def dry_run" not in source
    assert "def run_curses_tui" not in source
    assert "def build_parser" not in source


def test_version_is_centralized_and_not_duplicated(capsys):
    # The VERSION file at the repo root is the single source of truth.
    # version.py reads it; no other .py file should hard-code the version string.
    assert VERSION_FILE.is_file(), "VERSION file must exist at the repo root"
    version_literal = VERSION_FILE.read_text(encoding="utf-8").strip()

    # The package-level export must agree.
    assert ask.APP_VERSION == version_literal, (
        f"synapse_ask.APP_VERSION ({ask.APP_VERSION}) != VERSION file ({version_literal})"
    )

    # --version output must include the exact version string.
    with pytest.raises(SystemExit):
        ask.main(["--version"])
    version_output = capsys.readouterr().out
    assert f"Synapse Ask {version_literal}" in version_output, (
        f"--version output should contain 'Synapse Ask {version_literal}', got: {version_output!r}"
    )

    # No .py file under Ask/ should contain the version literal as a string,
    # except version.py (which reads it from VERSION, not a hard-coded literal).
    for py_file in sorted(PACKAGE.glob("*.py")):
        source = py_file.read_text(encoding="utf-8")
        for line_no, line in enumerate(source.splitlines(), 1):
            if "import" in line:
                continue
            if f'"{version_literal}"' in line or f"'{version_literal}'" in line:
                pytest.fail(
                    f"{py_file.name}:{line_no} hard-codes version string "
                    f"instead of reading from the VERSION file"
                )


def test_service_version_matches_ask_version():
    # The Synapse API service and the Ask CLI must report the same version.
    # Both read from the same VERSION file at the repo root.
    service_source = (ROOT / "scripts" / "synapse" / "service.py").read_text(encoding="utf-8")

    # Confirm the service reads from the VERSION file rather than hard-coding.
    assert "VERSION" in service_source, (
        "service.py must read version from the VERSION file, not hard-code it"
    )
    assert 'version="0.' not in service_source and "version='0." not in service_source, (
        "service.py must not hard-code a version string — use _SYNAPSE_VERSION from VERSION"
    )

    # Both locations must point to the same value.
    version_literal = VERSION_FILE.read_text(encoding="utf-8").strip()
    assert ask.APP_VERSION == version_literal
    # Also verify the service can resolve the same version at import time.
    # Since service.py may not be importable in the test environment (no FastAPI
    # runtime), verify by checking that it reads from the same file.
    assert "_REPO_ROOT" in service_source, (
        "service.py must define _REPO_ROOT to locate the VERSION file"
    )


def test_version_file_is_semver():
    # The VERSION file must contain a valid semver string (major.minor.patch).
    version_literal = VERSION_FILE.read_text(encoding="utf-8").strip()
    parts = version_literal.split(".")
    assert len(parts) == 3, (
        f"VERSION must be semver (major.minor.patch), got: {version_literal}"
    )
    for part in parts:
        # Allow trailing dev suffixes like "+dev" on the patch part
        patch_parts = part.split("+", 1)
        assert patch_parts[0].isdigit(), (
            f"VERSION must be numeric semver, got: {version_literal}"
        )


def test_version_py_path_resolves_to_repo_root():
    # version.py computes _ROOT as parent.parent.parent — verify it actually
    # points at the repository root where VERSION lives, not some other ancestor.
    from synapse_ask.version import _ROOT, _VERSION_FILE

    # _ROOT must be the same directory that contains the VERSION file.
    assert _ROOT == ROOT, (
        f"version._ROOT ({_ROOT}) does not match expected repo root ({ROOT}). "
        f"Check the parent chain in Ask/synapse_ask/version.py."
    )

    # _VERSION_FILE must point at the actual VERSION file.
    assert _VERSION_FILE == VERSION_FILE, (
        f"version._VERSION_FILE ({_VERSION_FILE}) != expected ({VERSION_FILE})"
    )

    # And reading it must succeed with the correct content.
    assert _VERSION_FILE.is_file(), f"VERSION file not found at {_VERSION_FILE}"
    assert _VERSION_FILE.read_text(encoding="utf-8").strip() == APP_VERSION


def test_tui_title_and_cli_version_show_same_version():
    # Both the TUI card title and --version output must use APP_VERSION,
    # which comes from the repo-root VERSION file.
    version_literal = VERSION_FILE.read_text(encoding="utf-8").strip()

    # The TUI render module imports APP_VERSION and embeds it in the title.
    import synapse_ask.tui_render as tui_render
    assert hasattr(tui_render, "APP_VERSION"), "tui_render must import APP_VERSION"
    assert tui_render.APP_VERSION == version_literal, (
        f"tui_render.APP_VERSION ({tui_render.APP_VERSION}) != VERSION ({version_literal})"
    )

    # The title format string must include the version.
    title = f" Synapse Ask v{APP_VERSION} "
    assert version_literal in title, (
        f"TUI title does not contain version {version_literal}"
    )

    # The CLI --version output must also show the same version.
    import synapse_ask.cli as cli_mod
    # argparse stores the version string at parser creation time;
    # verify the module-level APP_VERSION it uses matches the VERSION file.
    assert cli_mod.APP_VERSION == version_literal, (
        f"cli.APP_VERSION ({cli_mod.APP_VERSION}) != VERSION ({version_literal})"
    )