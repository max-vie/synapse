"""Focused tests for Ask/synapse_ask/config.py .env parsing.

Covers: normal values, export prefix, quoted values, inline comments,
shell-environment precedence, edge cases.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask.config import _parse_env_value, load_dotenv


# ---------------------------------------------------------------------------
# _parse_env_value unit tests
# ---------------------------------------------------------------------------

class TestParseEnvValue:
    """Unit tests for _parse_env_value."""

    def test_plain_value(self):
        assert _parse_env_value("hello") == "hello"

    def test_value_with_spaces(self):
        assert _parse_env_value("  hello world  ") == "hello world"

    def test_double_quoted_value(self):
        assert _parse_env_value('"hello world"') == "hello world"

    def test_double_quoted_preserves_inner_spaces(self):
        assert _parse_env_value('"  spaced  out  "') == "  spaced  out  "

    def test_single_quoted_value(self):
        assert _parse_env_value("'hello world'") == "hello world"

    def test_single_quoted_preserves_inner_spaces(self):
        assert _parse_env_value("'  spaced  out  '") == "  spaced  out  "

    def test_unquoted_inline_comment(self):
        assert _parse_env_value("bar # this is a comment") == "bar"

    def test_unquoted_inline_comment_no_space_before_hash(self):
        assert _parse_env_value("bar#comment") == "bar"

    def test_double_quoted_hash_preserved(self):
        assert _parse_env_value('"bar # not a comment"') == "bar # not a comment"

    def test_single_quoted_hash_preserved(self):
        assert _parse_env_value("'bar # not a comment'") == "bar # not a comment"

    def test_double_quoted_with_trailing_comment(self):
        assert _parse_env_value('"bar baz" # comment') == "bar baz"

    def test_single_quoted_with_trailing_comment(self):
        assert _parse_env_value("'bar baz' # comment") == "bar baz"

    def test_empty_value(self):
        assert _parse_env_value("") == ""

    def test_whitespace_only_value(self):
        assert _parse_env_value("   ") == ""

    def test_equals_in_quoted_value(self):
        assert _parse_env_value('"key=val"') == "key=val"

    def test_unquoted_value_with_equals(self):
        # After partition("="), the value side may contain "="
        assert _parse_env_value("a=b") == "a=b"

    def test_unterminated_double_quote(self):
        assert _parse_env_value('"no close quote') == "no close quote"

    def test_unterminated_single_quote(self):
        assert _parse_env_value("'no close quote") == "no close quote"


# ---------------------------------------------------------------------------
# load_dotenv integration tests (read from temp files)
# ---------------------------------------------------------------------------

class TestLoadDotenv:
    """Integration tests for load_dotenv against temp .env files."""

    def _load(self, content: str, tmp_path: Path) -> None:
        """Write content to a temp .env and load it, clearing chosen keys first."""
        env_file = tmp_path / ".env"
        env_file.write_text(content, encoding="utf-8")
        load_dotenv(env_file)

    def _unset(self, *keys: str) -> None:
        for k in keys:
            os.environ.pop(k, None)

    def test_normal_key_value(self, tmp_path: Path):
        self._unset("MY_KEY")
        self._load("MY_KEY=my_value\n", tmp_path)
        assert os.environ["MY_KEY"] == "my_value"

    def test_export_prefix(self, tmp_path: Path):
        self._unset("EXPORTED")
        self._load("export EXPORTED=yes\n", tmp_path)
        assert os.environ["EXPORTED"] == "yes"

    def test_double_quoted_value(self, tmp_path: Path):
        self._unset("QUOTED")
        self._load('QUOTED="hello world"\n', tmp_path)
        assert os.environ["QUOTED"] == "hello world"

    def test_single_quoted_value(self, tmp_path: Path):
        self._unset("SQUOTED")
        self._unset("SQUOTED")
        self._load("SQUOTED='hello world'\n", tmp_path)
        assert os.environ["SQUOTED"] == "hello world"

    def test_inline_comment_stripped(self, tmp_path: Path):
        self._unset("COMMENTED")
        self._load("COMMENTED=value # inline comment\n", tmp_path)
        assert os.environ["COMMENTED"] == "value"

    def test_quoted_hash_preserved(self, tmp_path: Path):
        self._unset("HASH_IN_VALUE")
        self._load('HASH_IN_VALUE="has # inside"\n', tmp_path)
        assert os.environ["HASH_IN_VALUE"] == "has # inside"

    def test_shell_env_overrides_dotenv(self, tmp_path: Path):
        self._unset("PRECEDENCE")
        os.environ["PRECEDENCE"] = "from_shell"
        self._load("PRECEDENCE=from_file\n", tmp_path)
        assert os.environ["PRECEDENCE"] == "from_shell"
        self._unset("PRECEDENCE")

    def test_dotenv_sets_unset_key(self, tmp_path: Path):
        self._unset("UNSET_KEY")
        self._load("UNSET_KEY=from_file\n", tmp_path)
        assert os.environ["UNSET_KEY"] == "from_file"

    def test_blank_lines_skipped(self, tmp_path: Path):
        self._unset("A", "B")
        self._load("A=1\n\nB=2\n", tmp_path)
        assert os.environ["A"] == "1"
        assert os.environ["B"] == "2"

    def test_comment_lines_skipped(self, tmp_path: Path):
        self._unset("C")
        self._load("# comment\nC=3\n", tmp_path)
        assert os.environ["C"] == "3"

    def test_no_equals_sign_skipped(self, tmp_path: Path):
        self._unset("D")
        self._load("NO_EQUALS_HERE\nD=4\n", tmp_path)
        assert os.environ["D"] == "4"
        assert "NO_EQUALS_HERE" not in os.environ

    def test_empty_value(self, tmp_path: Path):
        self._unset("EMPTY")
        self._load("EMPTY=\n", tmp_path)
        assert os.environ["EMPTY"] == ""

    def test_export_with_quoted_value(self, tmp_path: Path):
        self._unset("EXPORT_QUOTED")
        self._load('export EXPORT_QUOTED="spaced value"\n', tmp_path)
        assert os.environ["EXPORT_QUOTED"] == "spaced value"

    def test_export_with_inline_comment(self, tmp_path: Path):
        self._unset("EXPORT_COMMENTED")
        self._load("export EXPORT_COMMENTED=val # note\n", tmp_path)
        assert os.environ["EXPORT_COMMENTED"] == "val"

    def test_missing_file_no_error(self, tmp_path: Path):
        missing = tmp_path / "nonexistent.env"
        # Should not raise
        load_dotenv(missing)

    def test_trailing_comment_after_quoted_value(self, tmp_path: Path):
        self._unset("TRAILING")
        self._load('TRAILING="inside" # outside\n', tmp_path)
        assert os.environ["TRAILING"] == "inside"

    def test_value_with_equals(self, tmp_path: Path):
        self._unset("CONN")
        self._load("CONN=host=db port=5432\n", tmp_path)
        assert os.environ["CONN"] == "host=db port=5432"

    def test_export_with_single_quotes(self, tmp_path: Path):
        self._unset("EXPORT_SQ")
        self._load("export EXPORT_SQ='single quote value'\n", tmp_path)
        assert os.environ["EXPORT_SQ"] == "single quote value"

    def test_multiple_entries(self, tmp_path: Path):
        self._unset("X1", "X2", "X3")
        self._load("X1=10\nexport X2=20\nX3='thirty'\n", tmp_path)
        assert os.environ["X1"] == "10"
        assert os.environ["X2"] == "20"
        assert os.environ["X3"] == "thirty"