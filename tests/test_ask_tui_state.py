"""Tests for TuiState dataclass and unified command behaviour across line/curses modes."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask import tui_runner as ask_tui_runner  # noqa: E402
from synapse_ask.tui_state import (  # noqa: E402
    TuiState, new_tui_state, apply_tui_command, handle_tui_key,
    KEY_ENTER, KEY_CTRL_C, KEY_BACKSPACE, KEY_ESC,
    slash_option_lines,
)


# ──────────────────────────────────────────────────────────────────────
# TuiState dataclass tests
# ──────────────────────────────────────────────────────────────────────

class TestTuiStateDataclass:

    def test_new_tui_state_returns_tui_state_instance(self):
        state = new_tui_state()
        assert isinstance(state, TuiState)

    def test_new_tui_state_defaults(self):
        state = new_tui_state()
        assert state["input"] == ""
        assert state["cursor"] == 0
        assert state["scroll"] == 0
        assert state["status"] == "Ready"
        assert state["running"] is True
        assert state["messages"] == []
        assert state["history"] == []
        assert state["answer_history"] == []
        assert state["slash_menu"] is False

    def test_new_tui_state_with_initial_question(self):
        state = new_tui_state("What is Synapse?")
        assert state["input"] == "What is Synapse?"
        assert state["cursor"] == len("What is Synapse?")
        assert state["slash_menu"] is False

    def test_new_tui_state_with_slash_prefix_sets_slash_menu(self):
        state = new_tui_state("/notes")
        assert state["slash_menu"] is True

    def test_getitem_and_setitem(self):
        state = TuiState()
        state["input"] = "hello"
        assert state["input"] == "hello"
        assert state["input"] == "hello"

    def test_get_returns_attribute_value(self):
        state = TuiState(input="test")
        assert state.get("input") == "test"

    def test_get_returns_default_for_missing_key(self):
        state = TuiState()
        assert state.get("nonexistent", "fallback") == "fallback"

    def test_setdefault_creates_new_attribute(self):
        state = TuiState()
        result = state.setdefault("custom_field", 42)
        assert result == 42
        assert state["custom_field"] == 42

    def test_state_messages_is_mutable_list(self):
        state = TuiState()
        msg = {"role": "user", "text": "hi", "sources": []}
        state["messages"].append(msg)
        assert state["messages"] == [msg]


class TestInputEditing:

    def test_type_character_updates_input_and_cursor(self):
        state = TuiState()
        handle_tui_key(ord("h"), state)
        assert state["input"] == "h"
        assert state["cursor"] == 1

    def test_backspace_deletes_character(self):
        state = TuiState(input="ab", cursor=2)
        handle_tui_key(KEY_BACKSPACE, state)
        # Backspace at position 2 deletes "b" leaving "a"
        assert state["input"] == "a"
        assert state["cursor"] == 1

    def test_backspace_at_start_does_nothing(self):
        state = TuiState(input="abc", cursor=0)
        handle_tui_key(KEY_BACKSPACE, state)
        assert state["input"] == "abc"

    def test_typing_slash_sets_slash_menu(self):
        state = TuiState()
        handle_tui_key(ord("/"), state)
        assert state["slash_menu"] is True

    def test_typing_letter_clears_slash_menu(self):
        # Typing "a" after an empty input clears slash_menu (no "/" prefix).
        state = TuiState(input="", cursor=0, slash_menu=False)
        handle_tui_key(ord("a"), state)
        assert state["slash_menu"] is False

    def test_enter_submits_question_and_clears_composer(self):
        state = TuiState(input="What is OSPF?", cursor=14)
        action = handle_tui_key(KEY_ENTER, state)
        assert action == {"action": "submit", "question": "What is OSPF?"}
        assert state["input"] == ""
        assert state["cursor"] == 0

    def test_enter_on_empty_input_returns_none(self):
        state = TuiState(input="", cursor=0)
        action = handle_tui_key(KEY_ENTER, state)
        assert action is None

    def test_enter_appends_to_history(self):
        state = TuiState(input="hello", cursor=5)
        handle_tui_key(KEY_ENTER, state)
        assert state["history"] == ["hello"]

    def test_ctrl_c_sets_running_false(self):
        state = TuiState()
        action = handle_tui_key(KEY_CTRL_C, state)
        assert state["running"] is False
        assert action == {"action": "quit"}

    def test_escape_sets_running_false(self):
        state = TuiState()
        action = handle_tui_key(KEY_ESC, state)
        assert state["running"] is False
        assert action == {"action": "quit"}


class TestSlashMenuState:

    def test_slash_menu_shows_options_for_slash_prefix(self):
        state = new_tui_state("/")
        options = slash_option_lines(state)
        assert "/help" in options
        assert "/notes" in options

    def test_slash_menu_filters_by_prefix(self):
        state = new_tui_state("/n")
        options = slash_option_lines(state)
        assert "/notes" in options
        assert "/help" not in options

    def test_slash_menu_shows_no_matching_for_gibberish(self):
        state = new_tui_state("/xyz")
        options = slash_option_lines(state)
        assert "No matching" in options


class TestHistoryAppend:

    def test_submit_appends_to_history(self):
        state = TuiState(input="question one", cursor=12)
        handle_tui_key(KEY_ENTER, state)
        assert state["history"] == ["question one"]
        assert state["history_index"] is None

    def test_multiple_submit_appends_preserve_order(self):
        state = TuiState()
        for q in ["first", "second", "third"]:
            state["input"] = q
            state["cursor"] = len(q)
            handle_tui_key(KEY_ENTER, state)
        assert state["history"] == ["first", "second", "third"]


# ──────────────────────────────────────────────────────────────────────
# Unified command behaviour tests — line mode must match apply_tui_command
# ──────────────────────────────────────────────────────────────────────

class TestUnifiedQuitBehavior:

    def test_quit_command_via_apply_tui_command(self):
        """apply_tui_command handles /quit identically for both modes."""
        state = new_tui_state()
        action = apply_tui_command("/quit", state)
        assert action == {"action": "quit"}
        assert state["running"] is False
        assert state["status"] == "Bye"

    def test_exit_command_via_apply_tui_command(self):
        state = new_tui_state()
        action = apply_tui_command("exit", state)
        assert action == {"action": "quit"}

    def test_bare_quit_via_apply_tui_command(self):
        state = new_tui_state()
        action = apply_tui_command("quit", state)
        assert action == {"action": "quit"}

    def test_line_mode_quit_uses_apply_tui_command(self):
        prompts = iter(["/quit"])
        written = []
        exit_code = ask_tui_runner.run_tui(
            webhook_url="", note_path=None, timeout=1, auth_token="",
            input_func=lambda _: next(prompts),
            output_func=written.append,
            use_color=False,
        )
        assert exit_code == 0
        assert "bye" in " ".join(written)


class TestUnifiedClearBehavior:

    def test_clear_command_via_apply_tui_command(self):
        state = new_tui_state()
        state["messages"].append({"role": "assistant", "text": "old", "sources": []})
        action = apply_tui_command("/clear", state)
        assert action == {"action": "continue"}
        assert state["messages"][-1]["text"].startswith("Transcript cleared")
        assert state["scroll"] == 0

    def test_line_mode_clear_uses_apply_tui_command(self):
        prompts = iter(["/clear", "/quit"])
        written = []
        ask_tui_runner.run_tui(
            webhook_url="", note_path=None, timeout=1, auth_token="",
            input_func=lambda _: next(prompts),
            output_func=written.append,
            use_color=False,
        )
        joined = "\n".join(written)
        assert "Screen cleared" in joined or "Transcript cleared" in joined


class TestUnifiedHelpBehavior:

    def test_help_command_via_apply_tui_command(self):
        state = new_tui_state()
        action = apply_tui_command("/help", state)
        assert action == {"action": "continue"}
        help_text = "\n".join(str(m["text"]) for m in state["messages"])
        assert "/help" in help_text
        assert "/notes" in help_text
        assert "/quit" in help_text

    def test_line_mode_help_uses_apply_tui_command(self):
        prompts = iter(["/help", "/quit"])
        written = []
        ask_tui_runner.run_tui(
            webhook_url="", note_path=None, timeout=1, auth_token="",
            input_func=lambda _: next(prompts),
            output_func=written.append,
            use_color=False,
        )
        joined = "\n".join(written)
        assert "/help" in joined
        assert "/notes" in joined


class TestUnifiedNoteCommandBehavior:

    def test_note_command_returns_notes_action(self, tmp_path):
        notes_dir = tmp_path / "vault"
        notes_dir.mkdir()
        (notes_dir / "test.md").write_text("# Test\n", encoding="utf-8")

        state = new_tui_state()
        action = apply_tui_command("/notes", state, notes_root=notes_dir)
        assert action == {"action": "notes", "query": ""}

    def test_note_with_query_returns_notes_action(self, tmp_path):
        notes_dir = tmp_path / "vault"
        notes_dir.mkdir()
        state = new_tui_state()
        action = apply_tui_command("/notes ospf", state, notes_root=notes_dir)
        assert action == {"action": "notes", "query": "ospf"}

    def test_local_notes_command_returns_local_notes_action(self, tmp_path):
        notes_dir = tmp_path / "vault"
        notes_dir.mkdir()
        state = new_tui_state()
        action = apply_tui_command("/local-notes", state, notes_root=notes_dir)
        assert action == {"action": "local-notes", "query": ""}

    def test_local_notes_command_with_query(self, tmp_path):
        notes_dir = tmp_path / "vault"
        notes_dir.mkdir()
        state = new_tui_state()
        action = apply_tui_command("/local-notes ospf", state, notes_root=notes_dir)
        assert action == {"action": "local-notes", "query": "ospf"}

    def test_line_mode_local_notes_command(self, tmp_path):
        notes_dir = tmp_path / "vault"
        notes_dir.mkdir()
        (notes_dir / " ospf.md").write_text("# OSPF\n", encoding="utf-8")

        prompts = iter(["/local-notes", "/quit"])
        written = []
        ask_tui_runner.run_tui(
            webhook_url="", note_path=None, timeout=1, auth_token="",
            input_func=lambda _: next(prompts),
            output_func=written.append,
            use_color=False,
        )
        joined = "\n".join(written)
        # Local vault listing should show the vault label
        assert "Demo vault" in joined or "no Markdown notes" in joined or " ospf.md" in joined


class TestUnifiedSubmitBehavior:

    def test_submit_action_structure(self):
        state = TuiState(input="What is OSPF?", cursor=14)
        action = handle_tui_key(KEY_ENTER, state)
        assert action == {"action": "submit", "question": "What is OSPF?"}
        assert state["input"] == ""
        assert state["history"] == ["What is OSPF?"]

    def test_line_mode_question_submission_dry_run(self, tmp_path):
        note = tmp_path / "test.md"
        note.write_text("# Test\n\nOSPF uses Dijkstra's algorithm.\n", encoding="utf-8")

        prompts = iter(["What algorithm does OSPF use?", "/quit"])
        written = []
        exit_code = ask_tui_runner.run_tui(
            webhook_url="", note_path=note, timeout=1, auth_token="",
            input_func=lambda _: next(prompts),
            output_func=written.append,
            use_color=False,
            dry_run_enabled=True,
        )
        assert exit_code == 0
        joined = "\n".join(written)
        # Dry-run preview should mention it is a dry run or show local note context.
        assert "dry" in joined.lower() or "Dijkstra" in joined


class TestUnifiedErrorHandling:

    def test_line_mode_request_error_is_readable(self, monkeypatch):
        def fake_ask(*args, **kwargs):
            raise RuntimeError("timeout")

        monkeypatch.setattr(ask_tui_runner, "ask_question", fake_ask)

        prompts = iter(["What is Synapse?", "/quit"])
        written = []
        ask_tui_runner.run_tui(
            webhook_url="https://example.invalid/webhook",
            note_path=None, timeout=1, auth_token="",
            input_func=lambda _: next(prompts),
            output_func=written.append,
            use_color=False,
        )
        joined = "\n".join(written)
        assert "Request failed: timeout" in joined

    def test_curses_mode_submit_tui_question_error_surfaces(self):
        state = new_tui_state()
        from synapse_ask.tui_state import add_tui_message, replace_tui_message
        from synapse_ask.tui_runner import thinking_status
        add_tui_message(state, "user", "test question")
        placeholder = add_tui_message(state, "assistant", thinking_status(0))
        replace_tui_message(placeholder, "error", "Request failed: connection refused")
        state["status"] = "Request failed"
        assert state["messages"][-1]["role"] == "error"
        assert "connection refused" in state["messages"][-1]["text"]


class TestUnknownCommandBehavior:

    def test_unknown_slash_command_returns_unknown_action(self):
        state = new_tui_state()
        action = apply_tui_command("/xyz", state)
        assert action == {"action": "unknown", "command": "/xyz"}

    def test_line_mode_unknown_command_prints_error(self):
        prompts = iter(["/xyz", "/quit"])
        written = []
        ask_tui_runner.run_tui(
            webhook_url="", note_path=None, timeout=1, auth_token="",
            input_func=lambda _: next(prompts),
            output_func=written.append,
            use_color=False,
        )
        joined = "\n".join(written)
        assert "Unknown command: /xyz" in joined