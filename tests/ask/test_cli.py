"""Tests for Synapse Ask CLI argument parsing and dispatch."""

import json
from pathlib import Path

import pytest

from synapse_ask.cli import build_parser, main  # noqa: E402
from synapse_ask import cli as ask_cli  # noqa: E402
from synapse_ask.config import load_dotenv
from synapse_ask.dry_run import dry_run, local_note_metadata_path
from synapse_ask.notes import DEMO_VAULT, find_available_notes, format_local_notes, resolve_vault


# ── Parser structure ──────────────────────────────────────────────────


class TestBuildParser:
    def test_prog_name_is_synapse_ask(self):
        parser = build_parser()
        assert parser.prog == "synapse-ask"

    def test_description_mentions_tui_first(self):
        parser = build_parser()
        assert "TUI first" in parser.description

    def test_epilog_contains_usage_examples(self):
        parser = build_parser()
        assert "--text" in parser.epilog
        assert "--json" in parser.epilog
        assert "--dry-run" in parser.epilog

    def test_question_positional_is_optional(self):
        args = build_parser().parse_args([])
        assert args.question is None

    def test_webhook_url_defaults_to_empty_string(self):
        args = build_parser().parse_args([])
        assert args.webhook_url == ""

    def test_timeout_defaults_to_60(self):
        args = build_parser().parse_args([])
        assert args.timeout == 60

    def test_auth_token_defaults_to_empty_string(self):
        args = build_parser().parse_args([])
        assert args.auth_token == ""

    def test_filter_flags_default_to_empty_strings(self):
        args = build_parser().parse_args([])
        assert args.source_path == ""
        assert args.note_id == ""
        assert args.wiki_path == ""
        assert args.exact_run_id == ""

    def test_boolean_flags_default_to_false(self):
        args = build_parser().parse_args([])
        assert args.tui is False
        assert args.dry_run is False
        assert args.debug is False
        assert args.color is False
        assert args.no_color is False

    def test_output_format_flags_default_to_false(self):
        args = build_parser().parse_args([])
        assert args.text is False
        assert args.json is False
        assert args.raw_json is False
        assert args.output is None

    def test_color_and_no_color_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--color", "--no-color"])

    def test_text_json_raw_json_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--text", "--json"])

    def test_json_and_raw_json_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--json", "--raw-json"])

    def test_output_and_text_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            build_parser().parse_args(["--output", "text", "--text"])


# ── --help ────────────────────────────────────────────────────────────


class TestHelpOutput:
    def test_help_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--help"])
        assert exc.value.code == 0

    def test_help_includes_all_flags(self, capsys):
        with pytest.raises(SystemExit):
            main(["--help"])
        output = capsys.readouterr().out
        for flag in [
            "--webhook-url", "--note", "--timeout", "--auth-token",
            "--source-path", "--note-id", "--wiki-path", "--exact-run-id",
            "--tui", "--dry-run", "--debug", "--version",
            "--color", "--no-color",
            "--text", "--json", "--raw-json", "--output",
        ]:
            assert flag in output, f"help should document {flag}"

    def test_help_mentions_tui_first(self, capsys):
        with pytest.raises(SystemExit):
            main(["--help"])
        output = capsys.readouterr().out
        assert "TUI" in output


# ── --version ───────────────────────────────────────────────────────


class TestVersionOutput:
    def test_version_exits_zero(self, capsys):
        with pytest.raises(SystemExit) as exc:
            main(["--version"])
        assert exc.value.code == 0

    def test_version_includes_app_name(self, capsys):
        with pytest.raises(SystemExit):
            main(["--version"])
        output = capsys.readouterr().out
        assert "Synapse Ask" in output
        import re
        assert re.search(r"\d+\.\d+", output), "version output should contain a version number"


# ── --tui ────────────────────────────────────────────────────────────


class TestTuiFlag:
    def test_tui_flag_forces_tui_mode(self, monkeypatch):
        called = {}

        def fake_run_tui(webhook_url, note_path, timeout, auth_token, **kwargs):
            called["initial_question"] = kwargs.get("initial_question")
            called["dry_run"] = kwargs.get("dry_run_enabled")
            return 0

        monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)
        exit_code = main(["--tui", "hello"])
        assert exit_code == 0
        assert called["initial_question"] == "hello"

    def test_tui_flag_without_question(self, monkeypatch):
        called = {}

        def fake_run_tui(webhook_url, note_path, timeout, auth_token, **kwargs):
            called["initial_question"] = kwargs.get("initial_question")
            return 0

        monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)
        exit_code = main(["--tui"])
        assert exit_code == 0
        assert called["initial_question"] is None


# ── Missing question in one-shot mode ────────────────────────────────


class TestMissingQuestion:
    def test_text_without_question_exits_with_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["--text"])
        assert exc.value.code == 2

    def test_json_without_question_exits_with_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["--json"])
        assert exc.value.code == 2

    def test_raw_json_without_question_exits_with_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["--raw-json"])
        assert exc.value.code == 2

    def test_output_without_question_exits_with_error(self):
        with pytest.raises(SystemExit) as exc:
            main(["--output", "text"])
        assert exc.value.code == 2


# ── --text ────────────────────────────────────────────────────────────


class TestTextOutput:
    def test_text_dry_run_output(self, tmp_path, capsys):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nSynapse is a lab.\n", encoding="utf-8")
        exit_code = main(["--text", "--dry-run", "--note", str(note), "What is Synapse?"])
        assert exit_code == 0
        output = capsys.readouterr().out
        assert "Synapse" in output

    def test_text_output_live_without_webhook_fails(self, capsys):
        exit_code = main(["--text", "What is Synapse?"])
        assert exit_code == 1
        output = capsys.readouterr().out
        assert "Missing SYNAPSE_ASK_WEBHOOK_URL" in output


# ── --json ────────────────────────────────────────────────────────────


class TestJsonOutput:
    def test_json_dry_run_output(self, tmp_path, capsys):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nSynapse is a lab.\n", encoding="utf-8")
        exit_code = main(["--json", "--dry-run", "--note", str(note), "What is Synapse?"])
        assert exit_code == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert "json" in parsed
        assert "dry-run" in parsed["json"]["mode"]

    def test_json_without_dry_run_and_webhook_fails(self, capsys):
        exit_code = main(["--json", "What is Synapse?"])
        assert exit_code == 1
        output = capsys.readouterr().out
        assert "Missing SYNAPSE_ASK_WEBHOOK_URL" in output


# ── --raw-json ────────────────────────────────────────────────────────


class TestRawJsonOutput:
    def test_raw_json_dry_run_preserves_response_shape(self, tmp_path, capsys):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nContent.\n", encoding="utf-8")
        exit_code = main(["--raw-json", "--dry-run", "--note", str(note), "Q"])
        assert exit_code == 0
        output = capsys.readouterr().out
        parsed = json.loads(output)
        assert "json" not in parsed  # raw-json does NOT wrap in {"json": ...}
        assert parsed["mode"] == "dry-run"


# ── --output ────────────────────────────────────────────────────────────


class TestOutputOption:
    def test_output_text_selects_text_format(self, tmp_path, capsys):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nSynapse is a lab.\n", encoding="utf-8")
        exit_code = main(["--output", "text", "--dry-run", "--note", str(note), "Q"])
        assert exit_code == 0
        assert "Synapse" in capsys.readouterr().out

    def test_output_json_selects_json_format(self, tmp_path, capsys):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nContent.\n", encoding="utf-8")
        exit_code = main(["--output", "json", "--dry-run", "--note", str(note), "Q"])
        assert exit_code == 0
        parsed = json.loads(capsys.readouterr().out)
        assert "json" in parsed

    def test_output_raw_json_selects_raw_json_format(self, tmp_path, capsys):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nContent.\n", encoding="utf-8")
        exit_code = main(["--output", "raw-json", "--dry-run", "--note", str(note), "Q"])
        assert exit_code == 0
        parsed = json.loads(capsys.readouterr().out)
        assert "mode" in parsed
        assert "json" not in parsed


# ── --dry-run ──────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_flag_enables_local_preview(self, tmp_path, capsys):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nLocal content.\n", encoding="utf-8")

        exit_code = main(["--dry-run", "--json", "--note", str(note), "What is this?"])
        assert exit_code == 0
        output = capsys.readouterr().out
        assert '"dry-run"' in output

    def test_dry_run_preserves_local_note_metadata(self, tmp_path, capsys):
        note = tmp_path / "proof.md"
        note.write_text("# Proof\n\nSynapse indexes markdown notes.\n", encoding="utf-8")

        exit_code = main(["--dry-run", "--raw-json", "--note", str(note), "What is Synapse?"])
        assert exit_code == 0
        output = capsys.readouterr().out
        assert "sample_index_preview" in output


# ── Filter flags ──────────────────────────────────────────────────────


class TestFilterFlags:
    def test_source_path_is_parsed(self):
        args = build_parser().parse_args(["--source-path", "ospf/notes.md"])
        assert args.source_path == "ospf/notes.md"

    def test_note_id_is_parsed(self):
        args = build_parser().parse_args(["--note-id", "abc123"])
        assert args.note_id == "abc123"

    def test_wiki_path_is_parsed(self):
        args = build_parser().parse_args(["--wiki-path", "wiki/Main"])
        assert args.wiki_path == "wiki/Main"

    def test_exact_run_id_is_parsed(self):
        args = build_parser().parse_args(["--exact-run-id", "run-42"])
        assert args.exact_run_id == "run-42"


# ── --color / --no-color ──────────────────────────────────────────────


class TestColorFlags:
    def test_no_color_passed_to_tui(self, monkeypatch):
        called = {}

        def fake_run_tui(webhook_url, note_path, timeout, auth_token, **kwargs):
            called["use_color"] = kwargs.get("use_color")
            return 0

        monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)
        main(["--no-color"])
        assert called["use_color"] is False

    def test_color_passed_to_tui(self, monkeypatch):
        called = {}

        def fake_run_tui(webhook_url, note_path, timeout, auth_token, **kwargs):
            called["use_color"] = kwargs.get("use_color")
            return 0

        monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)
        main(["--color"])
        assert called["use_color"] is True

    def test_default_color_is_none(self, monkeypatch):
        called = {}

        def fake_run_tui(webhook_url, note_path, timeout, auth_token, **kwargs):
            called["use_color"] = kwargs.get("use_color")
            return 0

        monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)
        main([])
        assert called["use_color"] is None


# ── Bare question / TUI default ───────────────────────────────────────


class TestTuiDefault:
    def test_no_arguments_opens_tui(self, monkeypatch):
        called = {}

        def fake_run_tui(webhook_url, note_path, timeout, auth_token, **kwargs):
            called["initial_question"] = kwargs.get("initial_question")
            return 0

        monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)
        exit_code = main([])
        assert exit_code == 0
        assert called["initial_question"] is None

    def test_bare_question_opens_tui_with_prefilled_composer(self, monkeypatch):
        called = {}

        def fake_run_tui(webhook_url, note_path, timeout, auth_token, **kwargs):
            called["initial_question"] = kwargs.get("initial_question")
            return 0

        monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)
        exit_code = main(["What is Synapse?"])
        assert exit_code == 0
        assert called["initial_question"] == "What is Synapse?"


# ── One-shot error formatting ──────────────────────────────────────────


class TestOneShotErrorFormatting:
    def test_live_request_error_is_formatted_not_traceback(self, monkeypatch, capsys):
        def fake_ask(*args, **kwargs):
            raise RuntimeError("connection timeout")

        monkeypatch.setattr(ask_cli, "ask_question", fake_ask)
        exit_code = main(["--json", "--webhook-url", "https://private.invalid/webhook", "test"])
        assert exit_code == 1
        output = capsys.readouterr().out
        assert "Request failed: connection timeout" in output
        assert "Traceback" not in output

    def test_one_shot_without_webhook_fails_closed(self, capsys):
        exit_code = main(["--json", "What is Synapse?"])
        assert exit_code == 1
        output = capsys.readouterr().out
        assert "Missing SYNAPSE_ASK_WEBHOOK_URL" in output


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("plain=value", "value"),
        ('quoted="value with spaces"', "value with spaces"),
        ("single='value # kept'", "value # kept"),
        ("commented=value # removed", "value"),
        ("equals=a=b=c", "a=b=c"),
        ("empty=", ""),
    ],
)
def test_dotenv_value_shapes(line, expected, tmp_path, monkeypatch):
    key, _value = line.split("=", 1)
    monkeypatch.delenv(key, raising=False)
    path = tmp_path / ".env"
    path.write_text(line + "\n", encoding="utf-8")
    load_dotenv(path)
    assert __import__("os").environ[key] == expected


def test_dotenv_preserves_existing_shell_value(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("SYNAPSE_ASK_TEST_VALUE=file\n", encoding="utf-8")
    monkeypatch.setenv("SYNAPSE_ASK_TEST_VALUE", "shell")
    load_dotenv(path)
    assert __import__("os").environ["SYNAPSE_ASK_TEST_VALUE"] == "shell"


def test_note_path_is_public_safe_for_demo_repo_and_external_files(tmp_path):
    demo = DEMO_VAULT / "Synapse-Demo" / "example-study-notes.md"
    external = tmp_path / "private-note.MD"
    external.write_text("# Private\n", encoding="utf-8")
    assert local_note_metadata_path(demo) == "Synapse-Demo/example-study-notes.md"
    assert local_note_metadata_path(external) == "private-note.md"
    assert str(tmp_path) not in local_note_metadata_path(external)


def test_dry_run_returns_deterministic_preview(tmp_path):
    note = tmp_path / "note.md"
    note.write_text("# Note\n\nOSPF uses Dijkstra.\n", encoding="utf-8")
    result = dry_run("What does OSPF use?", note)
    assert result["mode"] == "dry-run"
    assert result["sample_index_preview"]["metadata"]["title"] == "Note"
    assert result["sample_index_preview"]["chunk_count"] == 1


def test_vault_resolution_and_note_listing_are_bounded(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "ospf.md").write_text("# OSPF\n", encoding="utf-8")
    (vault / "bgp.md").write_text("# BGP\n", encoding="utf-8")
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    root, label = resolve_vault()
    notes = find_available_notes(root, query="ospf", limit=10)
    rendered = format_local_notes(notes, label, root)
    assert root == vault
    assert [note.name for note in notes] == ["ospf.md"]
    assert "ospf.md" in rendered
    assert str(tmp_path) not in rendered
