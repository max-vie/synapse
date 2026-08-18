import curses
import time
from types import SimpleNamespace

import pytest

from synapse_ask import APP_VERSION, cli as ask_cli  # noqa: E402
from synapse_ask import tui_render as ask_tui_render  # noqa: E402
from synapse_ask import tui_runner as ask_tui_runner  # noqa: E402
from synapse_ask import formatting as ask_formatting  # noqa: E402
from synapse_ask import client as ask_client  # noqa: E402
from synapse_ask import tui_state as ask_tui_state  # noqa: E402


def test_synapse_tui_logo_uses_requested_startup_ascii_art():
    expected = r"""
 ____ __   __ _   _    _    ____  ____  _____
/ ___|\ \ / /| \ | |  / \  |  _ \/ ___|| ____|
\___ \ \ V / |  \| | / _ \ | |_) \___ \|  _|
 ___) | | |  | |\  |/ ___ \|  __/ ___) | |___
|____/  |_|  |_| \_/_/   \_\_|   |____/|_____|
""".strip("\n")

    assert ask_tui_render.SYNAPSE_LOGO == expected
    assert max(len(line) for line in ask_tui_render.SYNAPSE_LOGO.splitlines()) <= 80
    assert not ask_tui_render.SYNAPSE_LOGO.splitlines()[0].startswith(" ____  __")


def test_tui_screen_renders_clean_shell_for_dry_run():
    output = ask_formatting.render_tui_screen(
        question="What is Synapse?",
        result={
            "mode": "dry-run",
            "answer": "Dry run only.",
            "sources": [],
        },
        webhook_url="",
    )

    assert "Synapse Ask" in output
    assert "Mode" in output
    assert "Dry run only." in output
    assert "What is Synapse?" in output
    assert "JSON" not in output


def test_live_payload_includes_optional_rag_filters():
    payload = ask_client.build_live_payload(
        "What is the phrase?",
        source_path="Synapse-Demo/tui-proof.md",
        exact_run_id="tui-proof",
    )

    assert payload == {
        "question": "What is the phrase?",
        "source_path": "Synapse-Demo/tui-proof.md",
        "exact_run_id": "tui-proof",
    }


def test_sources_prefer_public_paths_over_urls():
    lines = ask_formatting.format_sources(
        {
            "sources": [
                {
                    "title": "Proof note",
                    "source_path": "Synapse-Demo/tui-proof.md",
                    "source_url": "http://private.invalid/wiki/tui-proof",
                    "url": "http://private.invalid/wiki/tui-proof",
                }
            ]
        },
        100,
    )

    joined = "\n".join(lines)
    assert "Proof note" in joined
    assert "Synapse-Demo/tui-proof.md" in joined
    assert "private.invalid" not in joined


def test_sources_do_not_render_generic_source_url_when_stable_locator_exists():
    lines = ask_formatting.format_sources(
        {
            "sources": [
                {
                    "source": "http://private.invalid/wiki/tui-proof",
                    "chunk_id": "chunk-1",
                }
            ]
        },
        100,
    )

    joined = "\n".join(lines)
    assert "chunk-1" in joined
    assert "private.invalid" not in joined


def test_sources_do_not_render_url_shaped_locator_fields():
    lines = ask_formatting.format_sources(
        {
            "sources": [
                {
                    "title": "Private wiki URL",
                    "path": "http://private.invalid/wiki/tui-proof",
                    "source_path": "https://private.invalid/source/tui-proof",
                }
            ]
        },
        100,
    )

    joined = "\n".join(lines)
    assert "Private wiki URL" in joined
    assert "private.invalid" not in joined


def test_sources_render_note_id_locator_when_no_public_path():
    lines = ask_formatting.format_sources(
        {"sources": [{"title": "Proof note", "note_id": "note-123"}]},
        100,
    )

    joined = "\n".join(lines)
    assert "Proof note" in joined
    assert "note-123" in joined


def test_display_answer_text_strips_markdown_for_plain_terminal_output():
    text = ask_formatting.display_answer_text(
        {
            "answer": "OSPF uses **Dijkstra's Shortest Path First (SPF) algorithm** [1]. See `ospf.md` and [source](https://private.invalid)."
        }
    )

    assert text == "OSPF uses Dijkstra's Shortest Path First (SPF) algorithm [1]. See ospf.md and source."
    assert ask_formatting.display_answer_text({"error": "Missing SYNAPSE_ASK_WEBHOOK_URL."}) == "Missing SYNAPSE_ASK_WEBHOOK_URL."
    assert "**" not in text
    assert "`" not in text
    assert "private.invalid" not in text


def test_tui_state_starts_with_composer_and_welcome_message():
    state = ask_tui_state.new_tui_state(initial_question="What is Synapse?")

    assert state["input"] == "What is Synapse?"
    assert state["cursor"] == len("What is Synapse?")
    assert state["messages"] == []


def test_tui_key_handler_edits_composer_buffer():
    state = ask_tui_state.new_tui_state()
    assert ask_tui_state.handle_tui_key(ord("S"), state) is None
    assert ask_tui_state.handle_tui_key(ord("y"), state) is None
    assert ask_tui_state.handle_tui_key(ask_tui_state.KEY_BACKSPACE, state) is None

    assert state["input"] == "S"
    assert state["cursor"] == 1


def test_slash_key_opens_options_menu():
    state = ask_tui_state.new_tui_state()

    assert ask_tui_state.handle_tui_key(ord("/"), state) is None

    assert state["input"] == "/"
    assert state["slash_menu"] is True
    assert "/help" in ask_tui_state.slash_option_lines(state)
    assert "/local-notes" in ask_tui_state.slash_option_lines(state)


def test_slash_menu_and_help_describe_indexed_notes_and_answer_history():
    state = ask_tui_state.new_tui_state()
    options = ask_tui_state.slash_option_lines(state)

    assert "/notes — List indexed notes from live Synapse" in options
    assert "/local-notes — Browse local vault Markdown files" in options
    assert "/!1 — Show answer 1 again" in options
    assert "local demo" not in options.lower()

    result = ask_tui_state.apply_tui_command("/help", state)

    assert result == {"action": "continue"}
    help_text = "\n".join(str(message["text"]) for message in state["messages"])
    assert "/notes list live Synapse indexed notes" in help_text
    assert "/!1 show answer 1 again" in help_text
    assert "local demo" not in help_text.lower()


def test_notes_command_requests_live_indexed_notes_not_local_demo_files(tmp_path):
    notes_dir = tmp_path / "vault"
    notes_dir.mkdir()
    (notes_dir / "knowledge-system-notes.md").write_text("# My Knowledge System\n", encoding="utf-8")

    state = ask_tui_state.new_tui_state()
    result = ask_tui_state.apply_tui_command("/notes ospf", state, notes_root=notes_dir)

    assert result == {"action": "notes", "query": "ospf"}
    assert state["messages"] == []


def test_local_notes_command_returns_local_notes_action(tmp_path):
    notes_dir = tmp_path / "vault"
    notes_dir.mkdir()
    (notes_dir / "knowledge-system-notes.md").write_text("# My Knowledge System\n", encoding="utf-8")

    state = ask_tui_state.new_tui_state()
    result = ask_tui_state.apply_tui_command("/local-notes", state, notes_root=notes_dir)

    assert result == {"action": "local-notes", "query": ""}


def test_tui_key_handler_enter_submits_and_clears_composer():
    state = ask_tui_state.new_tui_state(initial_question="What is Synapse?")
    action = ask_tui_state.handle_tui_key(ask_tui_state.KEY_ENTER, state)

    assert action == {"action": "submit", "question": "What is Synapse?"}
    assert state["input"] == ""
    assert state["cursor"] == 0


def test_tui_command_clear_removes_transcript_messages():
    state = ask_tui_state.new_tui_state()
    state["messages"].append({"role": "assistant", "text": "old answer", "sources": []})

    assert ask_tui_state.apply_tui_command("/clear", state) == {"action": "continue"}
    assert state["messages"][-1]["text"].startswith("Transcript cleared")


def test_answer_history_command_restores_numbered_answer_in_transcript():
    state = ask_tui_state.new_tui_state()
    ask_tui_state.remember_tui_answer(state, "OSPF uses Dijkstra. [1]", [{"source_path": "Synapse-Demo/ospf.md"}])
    ask_tui_state.remember_tui_answer(state, "BGP uses path-vector routing. [1]", [{"source_path": "Synapse-Demo/bgp.md"}])

    result = ask_tui_state.apply_tui_command("/!1", state)

    assert result == {"action": "continue"}
    assert state["messages"][-1]["role"] == "assistant"
    assert state["messages"][-1]["text"] == "OSPF uses Dijkstra. [1]"
    assert state["messages"][-1]["sources"] == [{"source_path": "Synapse-Demo/ospf.md"}]


def test_answer_history_command_reports_missing_answer_number():
    state = ask_tui_state.new_tui_state()
    ask_tui_state.remember_tui_answer(state, "OSPF uses Dijkstra. [1]", [{"source_path": "Synapse-Demo/ospf.md"}])

    result = ask_tui_state.apply_tui_command("/!2", state)

    assert result == {"action": "continue"}
    assert state["messages"][-1]["role"] == "system"
    assert state["messages"][-1]["text"] == "No answer with that number."


class FakeScreen:
    def __init__(self, height=34, width=120):
        self.height = height
        self.width = width
        self.calls = []

    def getmaxyx(self):
        return (self.height, self.width)

    def erase(self):
        self.calls.append(("erase",))

    def addstr(self, y, x, text, *attrs):
        self.calls.append(("addstr", y, x, text, attrs))

    def refresh(self):
        self.calls.append(("refresh",))

    def move(self, y, x):
        self.calls.append(("move", y, x))

    @property
    def rendered_text(self):
        return "\n".join(call[3] for call in self.calls if call[0] == "addstr")


def test_tui_draws_logo_right_info_startup_card_status_prompt_and_footer():
    screen = FakeScreen(height=24, width=100)
    state = ask_tui_state.new_tui_state(initial_question="What is Synapse?")

    ask_tui_render.draw_tui(screen, state, webhook_url="")

    rendered = screen.rendered_text
    assert f"Synapse Ask v{APP_VERSION}" in rendered
    assert "Live RAG workflow" in rendered
    assert "Ask a question from your notes" in rendered
    assert "Answers show Markdown sources" in rendered
    assert "Type /help for commands" in rendered
    assert "Latest answer" not in rendered
    assert "Latest proof" not in rendered
    assert "System: Synapse Ask full-screen TUI" not in rendered
    assert "> What is Synapse?" in rendered
    assert "/ opens options  ·  /help commands  ·  /notes live  ·  /local-notes vault" in rendered
    assert ask_tui_render.SYNAPSE_LOGO.splitlines()[0] in rendered
    assert "Welcome back to Synapse" not in rendered
    assert "Local notes · n8n · Qdrant · Ollama" not in rendered
    assert "Mode: DRY RUN" not in rendered
    assert "Conversation" not in rendered


def test_right_panel_uses_requested_copy_before_answer_without_technical_rows():
    screen = FakeScreen(height=24, width=100)
    state = ask_tui_state.new_tui_state(initial_question="What is Synapse?")

    ask_tui_render.draw_tui(screen, state, webhook_url="")

    rendered = screen.rendered_text
    right_panel_text = "\n".join(
        call[3]
        for call in screen.calls
        if call[0] == "addstr" and call[3] in {
            "Live RAG workflow",
            "Ask a question from your notes",
            "Answers show Markdown sources",
            "Type /help for commands",
        }
    )
    assert "Live RAG workflow" in rendered
    assert "Ask a question from your notes" in rendered
    assert "Answers show Markdown sources" in rendered
    assert "Type /help for commands" in rendered
    # Before any real answer, "Latest answer" must NOT appear
    assert "Latest answer" not in rendered
    assert "Latest proof" not in rendered
    assert "mode" not in right_panel_text.lower()
    assert "index" not in right_panel_text.lower()
    assert "guard" not in right_panel_text.lower()
    assert "source_path" not in right_panel_text


def test_right_panel_uses_orange_headlines_and_gray_body_text(monkeypatch):
    monkeypatch.setattr(ask_tui_render, "tui_attr", lambda pair, *flags: 100 + pair)
    screen = FakeScreen(height=24, width=100)
    state = ask_tui_state.new_tui_state()
    # Provide a real answer so "Latest answer" appears in the right panel
    ask_tui_state.add_tui_message(state, "user", "What is OSPF?")
    ask_tui_state.add_tui_message(state, "assistant", "OSPF uses Dijkstra's algorithm.")

    ask_tui_render.draw_tui(screen, state, webhook_url="")

    calls = [call for call in screen.calls if call[0] == "addstr"]
    live_attrs = next(call[4] for call in calls if call[3] == "Live RAG workflow")
    latest_attrs = next(call[4] for call in calls if call[3] == "Latest answer")
    body_attrs = next(call[4] for call in calls if call[3] == "Ask a question from your notes")
    assert live_attrs == latest_attrs
    assert live_attrs != body_attrs


def test_tui_startup_card_centers_logo_left_of_middle_divider_and_info_right():
    screen = FakeScreen(height=24, width=120)
    state = ask_tui_state.new_tui_state(initial_question="What is Synapse?")

    ask_tui_render.draw_tui(screen, state, webhook_url="")

    rendered_calls = [call for call in screen.calls if call[0] == "addstr"]
    rendered_text = "\n".join(call[3] for call in rendered_calls)
    card_call = next(call for call in rendered_calls if f"Synapse Ask v{APP_VERSION}" in call[3])
    card_top, card_left, card_width = card_call[1], card_call[2], len(card_call[3])
    divider_x = card_left + card_width // 2
    logo_first = ask_tui_render.SYNAPSE_LOGO.splitlines()[0]
    logo_call = next(call for call in rendered_calls if call[3] == logo_first)
    logo_width = max(len(line) for line in ask_tui_render.SYNAPSE_LOGO.splitlines())
    left_inner_width = divider_x - (card_left + 1)
    expected_logo_x = card_left + 1 + (left_inner_width - logo_width) // 2

    assert "Live RAG workflow" in rendered_text
    # Before any real answer, "Latest answer" must NOT appear
    assert "Latest answer" not in rendered_text
    assert logo_call[1] == card_top + 2
    assert logo_call[2] == expected_logo_x
    assert any(call[2] == divider_x and call[3] == "│" for call in rendered_calls if card_top < call[1] < card_top + 10)
    assert all(call[2] > divider_x for call in rendered_calls if call[3] in {"Live RAG workflow"})
    assert "Welcome back to Synapse" not in rendered_text
    assert "Local notes · n8n · Qdrant · Ollama" not in rendered_text
    assert "Mode: DRY RUN" not in rendered_text


def test_right_panel_after_answer_preserves_full_latest_answer_without_truncation():
    screen = FakeScreen(height=24, width=100)
    state = ask_tui_state.new_tui_state()
    full_answer = "OSPF uses Dijkstra's Shortest Path First algorithm. [1]"
    ask_tui_state.add_tui_message(state, "user", "what algorithm does ospf use?")
    ask_tui_state.add_tui_message(state, "assistant", full_answer, [{"source_path": "Synapse-Demo/ospf.md"}])

    ask_tui_render.draw_tui(screen, state, webhook_url="https://private.invalid/webhook")

    rendered = screen.rendered_text
    assert "Latest answer" in rendered
    assert "OSPF uses Dijkstra's Shortest Path" in rendered
    assert "First algorithm. [1]" in rendered
    assert "Latest proof" not in rendered
    assert f"Synapse: {full_answer}" in rendered


def test_tui_startup_layout_is_centered_in_wide_terminal():
    screen = FakeScreen(height=24, width=120)
    state = ask_tui_state.new_tui_state(initial_question="What is Synapse?")

    ask_tui_render.draw_tui(screen, state, webhook_url="")

    card_calls = [call for call in screen.calls if call[0] == "addstr" and f"Synapse Ask v{APP_VERSION}" in call[3]]
    assert card_calls
    card_left = card_calls[0][2]
    card_width = len(card_calls[0][3])
    prompt_calls = [call for call in screen.calls if call[0] == "addstr" and call[3].startswith("> What is Synapse?")]
    footer_calls = [call for call in screen.calls if call[0] == "addstr" and call[3].startswith("/ opens options")]

    assert card_left > 0
    assert card_width < screen.width - 1
    assert prompt_calls[0][2] == card_left
    assert footer_calls[0][2] == card_left


def test_tui_composer_uses_one_horizontal_rule_not_two():
    screen = FakeScreen(height=24, width=120)
    state = ask_tui_state.new_tui_state(initial_question="What is Synapse?")

    ask_tui_render.draw_tui(screen, state, webhook_url="")

    main_left, main_width = ask_tui_render.tui_main_region(screen.width)
    composer_rules = [call for call in screen.calls if call[0] == "addstr" and call[2] == main_left and call[3] == "─" * main_width]
    assert len(composer_rules) == 1


def test_tui_composer_keeps_one_horizontal_rule_after_chat_activity():
    screen = FakeScreen(height=24, width=120)
    state = ask_tui_state.new_tui_state()
    ask_tui_state.add_tui_message(state, "user", "what algorithm is used in ospf?")
    ask_tui_state.add_tui_message(state, "assistant", "OSPF uses Dijkstra's SPF algorithm. [1]")

    ask_tui_render.draw_tui(screen, state, webhook_url="https://private.invalid/webhook")

    main_left, main_width = ask_tui_render.tui_main_region(screen.width)
    composer_rules = [call for call in screen.calls if call[0] == "addstr" and call[2] == main_left and call[3] == "─" * main_width]
    assert len(composer_rules) == 1


def test_tui_draws_answer_transcript_after_chat_activity():
    screen = FakeScreen()
    state = ask_tui_state.new_tui_state()
    state["status"] = "◜ Thinking"
    ask_tui_state.add_tui_message(state, "user", "what algorithm is used in ospf?")
    ask_tui_state.add_tui_message(
        state,
        "assistant",
        "OSPF uses **Dijkstra's Shortest Path First (SPF) algorithm** [1].",
        [{"title": "OSPF proof", "source_path": "Synapse-Demo/ospf-rag-proof-test.md", "source_url": "http://private.invalid/wiki/ospf"}],
    )

    ask_tui_render.draw_tui(screen, state, webhook_url="https://private.invalid/webhook")

    rendered = screen.rendered_text
    assert f"Synapse Ask v{APP_VERSION}" in rendered
    assert "Mode: LIVE" not in rendered
    assert "Status:" not in rendered
    assert "You: what algorithm is used in ospf?" not in rendered
    assert "Synapse: OSPF uses Dijkstra" in rendered
    assert "**" not in rendered
    assert "System: Synapse Ask full-screen TUI" not in rendered
    assert "Shortest Path First" in rendered
    assert "Synapse-Demo/ospf-rag-proof-test.md" in rendered
    assert "private.invalid" not in rendered
    assert ">" in rendered
    assert "/help" in rendered
    assert "/local-notes" in rendered


def test_answer_reveal_frames_progressively_build_final_answer():
    frames = ask_tui_runner.answer_reveal_frames("OSPF uses Dijkstra's SPF algorithm. [1]", chunk_size=6)

    assert len(frames) > 3
    assert frames[0] == "OSPF u"
    assert frames[-1] == "OSPF uses Dijkstra's SPF algorithm. [1]"
    assert all(len(before) < len(after) for before, after in zip(frames, frames[1:]))


def test_thinking_status_uses_four_point_spinning_circle_animation():
    frames = [ask_tui_runner.thinking_status(index) for index in range(5)]

    assert ask_tui_runner.THINKING_FRAME_DELAY == 0.08
    assert frames == [
        "◜ Thinking",
        "◝ Thinking",
        "◞ Thinking",
        "◟ Thinking",
        "◜ Thinking",
    ]


def test_submit_tui_question_animates_visible_thinking_while_live_request_is_pending(monkeypatch):
    state = ask_tui_state.new_tui_state()
    events = []

    def fake_ask_question(*args, **kwargs):
        events.append(("ask-start", state["status"], [message["text"] for message in state["messages"]], False))
        time.sleep(0.03)
        events.append(("ask-end", state["status"], [message["text"] for message in state["messages"]], False))
        events.append(("ask", state["status"], [message["text"] for message in state["messages"]]))
        return {
            "answer": "OSPF uses Dijkstra's SPF algorithm. [1]",
            "sources": [{"source_path": "Synapse-Demo/ospf-rag-proof-test.md"}],
        }

    monkeypatch.setattr(ask_tui_runner, "ask_question", fake_ask_question)
    monkeypatch.setattr(ask_tui_runner, "THINKING_FRAME_DELAY", 0.005)
    monkeypatch.setattr(ask_tui_runner, "ANSWER_REVEAL_DELAY", 0)

    ask_tui_runner.submit_tui_question(
        state,
        "what algorithm is used in ospf?",
        "https://private.invalid/webhook",
        None,
        60,
        "",
        on_thinking=lambda: events.append(
            (
                "redraw",
                state["status"],
                [message["text"] for message in state["messages"]],
                any(event[0] == "ask-start" for event in events),
            )
        ),
    )

    redraws = [event for event in events if event[0] == "redraw"]
    redraws_after_request_started = [event for event in redraws if event[3]]
    spinner_statuses = {ask_tui_runner.thinking_status(index) for index in range(len(ask_tui_runner.THINKING_SPINNER_FRAMES))}
    assert redraws_after_request_started
    assert any(text in spinner_statuses for event in redraws_after_request_started for text in event[2])
    assert any(status in spinner_statuses for _, status, _, _ in redraws_after_request_started)
    assert events[-1][0] == "ask"
    assert state["status"] == "Ready"
    assert [message["role"] for message in state["messages"]] == ["user", "assistant"]
    assert state["messages"][-1]["text"] == "OSPF uses Dijkstra's SPF algorithm. [1]"
    assert all(str(message["text"]) not in spinner_statuses for message in state["messages"])


def test_submit_tui_question_reveals_answer_progressively_after_live_request_returns(monkeypatch):
    state = ask_tui_state.new_tui_state()
    reveal_frames = []

    monkeypatch.setattr(
        ask_tui_runner,
        "ask_question",
        lambda *args, **kwargs: {
            "answer": "OSPF uses **Dijkstra's SPF algorithm**. [1]",
            "sources": [{"source_path": "Synapse-Demo/ospf-rag-proof-test.md"}],
        },
    )
    monkeypatch.setattr(ask_tui_runner, "ANSWER_REVEAL_DELAY", 0)
    monkeypatch.setattr(ask_tui_runner, "ANSWER_REVEAL_CHARS_PER_FRAME", 5)

    ask_tui_runner.submit_tui_question(
        state,
        "what algorithm is used in ospf?",
        "https://private.invalid/webhook",
        None,
        60,
        "",
        on_answer_reveal=lambda: reveal_frames.append(state["messages"][-1]["text"]),
    )

    assert len(reveal_frames) > 3
    assert reveal_frames[0] == "OSPF "
    assert reveal_frames[-1] == "OSPF uses Dijkstra's SPF algorithm. [1]"
    assert all("**" not in frame for frame in reveal_frames)
    assert any(frame != reveal_frames[-1] and "Dijkstra" in frame for frame in reveal_frames)
    assert state["messages"][-1]["text"] == "OSPF uses Dijkstra's SPF algorithm. [1]"
    assert state["messages"][-1]["sources"] == [{"source_path": "Synapse-Demo/ospf-rag-proof-test.md"}]
    assert state["status"] == "Ready"


def test_draw_tui_renders_thinking_placeholder_as_synapse_reply():
    screen = FakeScreen()
    state = ask_tui_state.new_tui_state()
    ask_tui_state.add_tui_message(state, "user", "what algorithm is used in ospf?")
    ask_tui_state.add_tui_message(state, "assistant", "◜ Thinking")
    state["status"] = "◜ Thinking"

    ask_tui_render.draw_tui(screen, state, webhook_url="https://private.invalid/webhook")

    rendered = screen.rendered_text
    assert "You: what algorithm is used in ospf?" not in rendered
    assert "Synapse: ◜ Thinking" in rendered
    assert "Status:" not in rendered


class TestRightPanelState:
    """Right-panel tip card shows 'Latest answer' only after a real answer."""

    def test_before_answer_no_latest_answer_heading(self):
        # Fresh state — no messages at all.  The right panel must show the four
        # static tips and nothing else.
        screen = FakeScreen(height=24, width=100)
        state = ask_tui_state.new_tui_state()

        ask_tui_render.draw_tui(screen, state, webhook_url="")

        rendered = screen.rendered_text
        assert "Live RAG workflow" in rendered
        assert "Ask a question from your notes" in rendered
        assert "Answers show Markdown sources" in rendered
        assert "Type /help for commands" in rendered
        assert "Latest answer" not in rendered

    def test_during_thinking_no_latest_answer_heading(self):
        # While the spinner is active (e.g. "◜ Thinking"), the right panel
        # must NOT show a "Latest answer" heading.  The spinner does appear
        # in the transcript as "Synapse: ◜ Thinking" — that is expected.
        screen = FakeScreen(height=24, width=100)
        state = ask_tui_state.new_tui_state()
        ask_tui_state.add_tui_message(state, "user", "what is ospf?")
        ask_tui_state.add_tui_message(state, "assistant", "◜ Thinking")

        ask_tui_render.draw_tui(screen, state, webhook_url="https://example.invalid/webhook")

        rendered = screen.rendered_text
        assert "Latest answer" not in rendered
        # The spinner appears in the transcript area, not in the tip card
        assert "Synapse: ◜ Thinking" in rendered

    def test_all_spinner_frames_are_skipped_in_preview(self):
        # Every spinner character must be excluded from latest answer preview.
        for spinner in ("◜", "◝", "◞", "◟"):
            text = f"{spinner} Thinking"
            assert ask_tui_render._is_thinking_placeholder(text)

    def test_after_real_answer_shows_latest_answer_heading(self):
        # Once an actual answer lands, "Latest answer" appears as the orange
        # heading above the compact preview of that answer.
        screen = FakeScreen(height=24, width=100)
        state = ask_tui_state.new_tui_state()
        ask_tui_state.add_tui_message(state, "user", "what algorithm does ospf use?")
        ask_tui_state.add_tui_message(state, "assistant", "OSPF uses Dijkstra's SPF algorithm.")

        ask_tui_render.draw_tui(screen, state, webhook_url="https://example.invalid/webhook")

        rendered = screen.rendered_text
        assert "Latest answer" in rendered
        assert "OSPF uses Dijkstra's SPF" in rendered

    def test_after_real_answer_spinner_is_not_in_preview(self):
        # If the last assistant message is a spinner but a previous one was a
        # real answer, the preview should show the real answer, not the spinner.
        state = ask_tui_state.new_tui_state()
        ask_tui_state.add_tui_message(state, "user", "what is ospf?")
        ask_tui_state.add_tui_message(state, "assistant", "OSPF is a link-state routing protocol.")
        ask_tui_state.add_tui_message(state, "assistant", "◝ Thinking")

        lines = ask_tui_render.latest_answer_preview_lines(state, 80)
        assert lines
        assert "OSPF is a link-state" in lines[0]
        assert "Thinking" not in " ".join(lines)

    def test_latest_answer_preview_returns_empty_when_no_messages(self):
        state = ask_tui_state.new_tui_state()
        assert ask_tui_render.latest_answer_preview_lines(state, 80) == []

    def test_latest_answer_preview_returns_empty_when_only_spinner(self):
        state = ask_tui_state.new_tui_state()
        ask_tui_state.add_tui_message(state, "assistant", "◟ Thinking")
        assert ask_tui_render.latest_answer_preview_lines(state, 80) == []

    def test_latest_answer_preview_returns_real_answer_ignoring_prior_spinner(self):
        state = ask_tui_state.new_tui_state()
        ask_tui_state.add_tui_message(state, "assistant", "◜ Thinking")
        ask_tui_state.add_tui_message(state, "assistant", "BGP uses path vectors.")
        lines = ask_tui_render.latest_answer_preview_lines(state, 80)
        assert lines
        assert "BGP uses path vectors." in lines[0]


def test_submit_tui_question_refuses_live_answer_without_sources(monkeypatch):
    state = ask_tui_state.new_tui_state()

    def fake_ask_question(*args, **kwargs):
        return {
            "answer": "OSPF uses Dijkstra's Shortest Path First algorithm.",
            "sources": [],
        }

    monkeypatch.setattr(ask_tui_runner, "ask_question", fake_ask_question)
    monkeypatch.setattr(ask_tui_runner, "ANSWER_REVEAL_DELAY", 0)

    ask_tui_runner.submit_tui_question(
        state,
        "what algorithm is used in ospf?",
        "https://private.invalid/webhook",
        None,
        60,
        "",
    )

    assistant_messages = [message for message in state["messages"] if message["role"] == "assistant"]
    assert assistant_messages[-1]["text"] == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER
    assert "Dijkstra" not in assistant_messages[-1]["text"]
    assert assistant_messages[-1]["sources"] == []


def test_render_live_screen_does_not_show_uncited_answer():
    output = ask_formatting.render_tui_screen(
        question="what algorithm is used in ospf?",
        result={
            "answer": "OSPF uses Dijkstra's Shortest Path First algorithm.",
            "sources": [],
        },
        webhook_url="https://private.invalid/webhook",
    )

    assert ask_formatting.INSUFFICIENT_CONTEXT_ANSWER in output
    assert "Dijkstra" not in output


def test_one_shot_text_live_output_refuses_uncited_answer():
    result = {"answer": "OSPF uses Dijkstra's SPF algorithm.", "sources": []}

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_refuses_citation_strings_without_real_sources():
    result = {"answer": "OSPF uses Dijkstra's SPF algorithm. [1]", "citations": ["[1]"]}

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_refuses_source_dict_without_stable_locator():
    result = {"answer": "OSPF uses Dijkstra's SPF algorithm. [1]", "sources": [{"title": "Only a title"}]}

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_refuses_source_type_without_stable_locator():
    result = {"answer": "OSPF uses Dijkstra's SPF algorithm. [1]", "sources": [{"source": "obsidian"}]}

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_accepts_source_path_locator():
    result = {
        "answer": "OSPF uses Dijkstra's SPF algorithm. [1]",
        "sources": [{"title": "OSPF proof", "source_path": "Synapse-Demo/ospf.md"}],
    }

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == "OSPF uses Dijkstra's SPF algorithm. [1]"


def test_one_shot_live_output_refuses_answer_with_source_but_no_citation():
    result = {
        "answer": "OSPF uses Dijkstra's SPF algorithm.",
        "sources": [{"title": "OSPF proof", "source_path": "Synapse-Demo/ospf.md"}],
    }

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_refuses_answer_with_out_of_range_citation():
    result = {
        "answer": "OSPF uses Dijkstra's SPF algorithm. [99]",
        "sources": [{"title": "OSPF proof", "source_path": "Synapse-Demo/ospf.md"}],
    }

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_refuses_bare_id_source_locator():
    result = {
        "answer": "OSPF uses Dijkstra's SPF algorithm. [1]",
        "sources": [{"id": "1"}],
    }

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_refuses_url_shaped_source_locator():
    result = {
        "answer": "OSPF uses Dijkstra's SPF algorithm. [1]",
        "sources": [{"title": "Private wiki URL", "path": "http://private.invalid/wiki/ospf"}],
    }

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_live_output_does_not_trust_response_dry_run_mode_to_bypass_sources():
    result = {"mode": "dry-run", "answer": "OSPF uses Dijkstra's SPF algorithm.", "sources": []}

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_live_error_payload_without_mode_is_not_rewritten_as_rag_refusal():
    result = ask_formatting.normalize_rag_result({"error": "upstream timeout", "sources": []}, require_sources=True)

    assert result["error"] == "upstream timeout"
    assert result.get("answer") != ask_formatting.INSUFFICIENT_CONTEXT_ANSWER


def test_one_shot_text_live_error_payload_surfaces_error_field():
    result = {"error": "upstream timeout", "sources": []}

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == "upstream timeout"


def test_submit_tui_question_surfaces_200_error_payload(monkeypatch):
    state = ask_tui_state.new_tui_state()

    monkeypatch.setattr(ask_tui_runner, "ask_question", lambda *args, **kwargs: {"error": "upstream timeout", "sources": []})

    ask_tui_runner.submit_tui_question(
        state,
        "what algorithm is used in ospf?",
        "https://private.invalid/webhook",
        None,
        60,
        "",
    )

    assert state["messages"][-1]["role"] == "error"
    assert state["messages"][-1]["text"] == "upstream timeout"
    assert state["status"] == "Request failed"


def test_live_error_mode_with_whitespace_is_not_rewritten_as_rag_refusal():
    result = {"mode": "error ", "answer": "Request failed: timeout", "sources": []}

    assert ask_formatting.format_one_shot_output(result, "text", require_sources=True) == "Request failed: timeout"


def test_live_shell_status_messages_are_not_rewritten_as_rag_answers():
    output = ask_formatting.render_tui_screen(
        question="What can I ask?",
        result={"mode": "dry-run", "answer": "Ask a question about your notes.", "sources": []},
        webhook_url="https://private.invalid/webhook",
    )

    assert "Ask a question about your notes." in output
    assert ask_formatting.INSUFFICIENT_CONTEXT_ANSWER not in output


def test_live_request_errors_are_not_rewritten_as_rag_refusals():
    output = ask_formatting.render_tui_screen(
        question="what algorithm is used in ospf?",
        result={"mode": "error", "answer": "Request failed: timeout", "sources": []},
        webhook_url="https://private.invalid/webhook",
    )

    assert "Request failed: timeout" in output
    assert ask_formatting.INSUFFICIENT_CONTEXT_ANSWER not in output


def test_tui_loop_accepts_question_and_quit_without_network():
    prompts = iter(["What is Synapse?", "/quit"])
    written = []

    exit_code = ask_tui_runner.run_tui(
        webhook_url="",
        note_path=None,
        timeout=1,
        auth_token="",
        input_func=lambda _prompt: next(prompts),
        output_func=written.append,
    )

    joined = "\n".join(written)
    assert exit_code == 0
    assert "Synapse Ask" in joined
    assert "What is Synapse?" in joined
    assert "Missing SYNAPSE_ASK_WEBHOOK_URL" in joined
    assert "Dry run only" not in joined


def test_tui_clear_redraws_the_shell():
    prompts = iter(["/clear", "/quit"])
    written = []

    exit_code = ask_tui_runner.run_tui(
        webhook_url="",
        note_path=None,
        timeout=1,
        auth_token="",
        input_func=lambda _prompt: next(prompts),
        output_func=written.append,
        use_color=False,
    )

    assert exit_code == 0
    assert sum("Synapse Ask" in chunk for chunk in written) >= 2
    assert "Screen cleared" in "\n".join(written)


def test_line_tui_notes_command_lists_indexed_notes_without_submitting_rag(monkeypatch):
    prompts = iter(["/notes", "/quit"])
    written = []

    monkeypatch.setattr(ask_tui_runner, "ask_question", lambda *args, **kwargs: pytest.fail("/notes should not call live RAG"))
    monkeypatch.setattr(
        ask_tui_runner,
        "list_indexed_notes",
        lambda *args, **kwargs: [
            {"source_path": "Synapse-Demo/ospf.md", "title": "OSPF Routing"},
        ],
    )

    exit_code = ask_tui_runner.run_tui(
        webhook_url="https://private.invalid/webhook/synapse/ask",
        note_path=None,
        timeout=1,
        auth_token="token",
        input_func=lambda _prompt: next(prompts),
        output_func=written.append,
        use_color=False,
    )

    joined = "\n".join(written)
    assert exit_code == 0
    assert "Indexed Markdown notes" in joined
    assert "Synapse-Demo/ospf.md" in joined
    assert "OSPF Routing" in joined
    assert "Local demo" not in joined


def test_line_tui_notes_without_webhook_shows_clear_message():
    # /notes without webhook URL and without dry-run should show a clear
    # message directing the user to --dry-run or /local-notes.
    prompts = iter(["/notes", "/quit"])
    written = []

    ask_tui_runner.run_tui(
        webhook_url="",
        note_path=None,
        timeout=1,
        auth_token="",
        input_func=lambda _prompt: next(prompts),
        output_func=written.append,
        use_color=False,
    )

    joined = "\n".join(written)
    assert "No live Synapse webhook configured" in joined
    assert "--dry-run" in joined or "/local-notes" in joined


def test_line_tui_notes_with_dry_run_shows_local_vault():
    # /notes in dry-run mode (no webhook) should show local vault files.
    prompts = iter(["/notes", "/quit"])
    written = []

    ask_tui_runner.run_tui(
        webhook_url="",
        note_path=None,
        timeout=1,
        auth_token="",
        input_func=lambda _prompt: next(prompts),
        output_func=written.append,
        use_color=False,
        dry_run_enabled=True,
    )

    joined = "\n".join(written)
    # Either shows local vault files or reports none found — but never
    # the "No webhook configured" error message.
    assert "No live Synapse webhook configured" not in joined
    assert "Demo vault" in joined or "Configured vault" in joined or "no Markdown notes" in joined


def test_line_tui_local_notes_always_browses_vault():
    # /local-notes should always browse the local vault, even without a webhook.
    prompts = iter(["/local-notes", "/quit"])
    written = []

    ask_tui_runner.run_tui(
        webhook_url="",
        note_path=None,
        timeout=1,
        auth_token="",
        input_func=lambda _prompt: next(prompts),
        output_func=written.append,
        use_color=False,
    )

    joined = "\n".join(written)
    # Should show vault label or "no notes" message, never the webhook error.
    assert "No live Synapse webhook configured" not in joined
    assert "Demo vault" in joined or "Configured vault" in joined or "no Markdown notes" in joined


def test_line_tui_answer_history_command_restores_answer(monkeypatch):
    prompts = iter(["what algorithm does ospf use?", "/!1", "/quit"])
    written = []

    monkeypatch.setattr(
        ask_tui_runner,
        "ask_question",
        lambda *args, **kwargs: {"answer": "OSPF uses Dijkstra. [1]", "sources": [{"source_path": "Synapse-Demo/ospf.md"}]},
    )

    exit_code = ask_tui_runner.run_tui(
        webhook_url="https://private.invalid/webhook/synapse/ask",
        note_path=None,
        timeout=1,
        auth_token="token",
        input_func=lambda _prompt: next(prompts),
        output_func=written.append,
        use_color=False,
    )

    joined = "\n".join(written)
    assert exit_code == 0
    assert joined.count("OSPF uses Dijkstra. [1]") >= 2
    assert "No answer with that number" not in joined


def test_note_command_requires_exact_command_or_space_separator(tmp_path):
    notes_dir = tmp_path / "vault"
    notes_dir.mkdir()
    (notes_dir / "Proof.md").write_text("# Proof\n", encoding="utf-8")
    state = ask_tui_state.new_tui_state()

    result = ask_tui_state.apply_tui_command("/notebook", state, notes_root=notes_dir)

    assert result == {"action": "unknown", "command": "/notebook"}
    joined = "\n".join(message["text"] for message in state["messages"])
    assert "Available notes" not in joined


def test_run_tui_falls_back_to_line_mode_when_curses_wrapper_cannot_initialize(monkeypatch):
    # Known terminal init failures (curses.error, e.g. setupterm) should fall back
    # to line mode so the app still works in piped/CI environments.
    called = {}

    def fake_wrapper(callback):
        raise curses.error("setupterm: could not find terminal")

    def fake_line_tui(*args, **kwargs):
        called["line"] = (args, kwargs)
        return 0

    monkeypatch.setattr(ask_tui_runner, "curses", SimpleNamespace(wrapper=fake_wrapper, error=curses.error))
    monkeypatch.setattr(ask_tui_runner, "run_line_tui", fake_line_tui)

    assert ask_tui_runner.run_tui("", None, 1, "", use_color=False) == 0
    assert "line" in called


def test_run_tui_falls_back_to_line_mode_when_curses_module_is_missing(monkeypatch):
    # Missing curses module is a known environment limitation.
    called = {}

    def fake_line_tui(*args, **kwargs):
        called["line"] = True
        return 0

    monkeypatch.setattr(ask_tui_runner, "curses", None)
    monkeypatch.setattr(ask_tui_runner, "run_line_tui", fake_line_tui)

    assert ask_tui_runner.run_tui("", None, 1, "", use_color=False) == 0
    assert "line" in called


def test_run_tui_does_not_silently_swallow_unexpected_exceptions(monkeypatch):
    # Unexpected TUI exceptions must surface as a clear SystemExit with the
    # original error and recovery instructions — not a raw ValueError traceback.
    def fake_wrapper(callback):
        raise ValueError("unexpected bug in TUI rendering")

    monkeypatch.setattr(ask_tui_runner, "curses", SimpleNamespace(wrapper=fake_wrapper, error=curses.error))
    monkeypatch.delenv("SYNAPSE_ASK_FALLBACK_ON_TUI_ERROR", raising=False)

    with pytest.raises(SystemExit, match="Synapse Ask TUI failed: unexpected bug in TUI rendering") as exc_info:
        ask_tui_runner.run_tui("", None, 1, "", use_color=False)
    assert "SYNAPSE_ASK_FALLBACK_ON_TUI_ERROR" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_run_tui_falls_back_on_unexpected_exception_when_env_opt_in_set(monkeypatch):
    # SYNAPSE_ASK_FALLBACK_ON_TUI_ERROR=true forces fallback even for unexpected
    # errors, useful for remote/CI with unusual terminals where the user prefers
    # line mode over a crash.
    called = {}

    def fake_wrapper(callback):
        raise ValueError("unexpected bug in TUI rendering")

    def fake_line_tui(*args, **kwargs):
        called["line"] = True
        return 0

    monkeypatch.setattr(ask_tui_runner, "curses", SimpleNamespace(wrapper=fake_wrapper, error=curses.error))
    monkeypatch.setattr(ask_tui_runner, "run_line_tui", fake_line_tui)
    monkeypatch.setenv("SYNAPSE_ASK_FALLBACK_ON_TUI_ERROR", "true")

    assert ask_tui_runner.run_tui("", None, 1, "", use_color=False) == 0
    assert "line" in called


def test_main_without_options_starts_tui(monkeypatch):
    called = {}

    def fake_run_tui(webhook_url, note_path, timeout, auth_token, use_color=None, initial_question=None, **kwargs):
        called["args"] = (webhook_url, note_path, timeout, auth_token, use_color, initial_question)
        return 0

    monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)

    assert ask_cli.main([]) == 0
    assert called["args"] == ("", None, 60, "", None, None)


def test_bare_question_opens_tui_with_prefilled_composer(monkeypatch):
    called = {}

    def fake_run_tui(webhook_url, note_path, timeout, auth_token, use_color=None, initial_question=None, **kwargs):
        called["initial_question"] = initial_question
        return 0

    monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)

    assert ask_cli.main(["What is Synapse?"]) == 0
    assert called["initial_question"] == "What is Synapse?"


def test_script_output_flag_requires_question():
    with pytest.raises(SystemExit) as exc:
        ask_cli.main(["--json"])

    assert exc.value.code == 2


def test_one_shot_without_webhook_fails_closed_in_live_mode(capsys):
    code = ask_cli.main(["--json", "What is Synapse?"])

    assert code == 1
    output = capsys.readouterr().out
    assert "Missing SYNAPSE_ASK_WEBHOOK_URL" in output
    assert "--dry-run" in output
    assert '"mode": "error"' in output
    assert '"mode": "dry-run"' not in output


def test_explicit_dry_run_flag_preserves_local_preview(tmp_path, capsys):
    note = tmp_path / "Proof.md"
    note.write_text("# Proof\n\nSynapse indexes markdown notes.\n", encoding="utf-8")

    code = ask_cli.main(["--dry-run", "--json", "--note", str(note), "What is Synapse?"])

    assert code == 0
    output = capsys.readouterr().out
    assert '"mode": "dry-run"' in output
    assert "sample_index_preview" in output


def test_one_shot_live_request_error_is_formatted_not_traceback(monkeypatch, capsys):
    def fake_ask_question(*args, **kwargs):
        raise RuntimeError("timeout")

    monkeypatch.setattr(ask_cli, "ask_question", fake_ask_question)

    code = ask_cli.main(["--json", "--webhook-url", "https://private.invalid/webhook", "what algorithm is used in ospf?"])

    assert code == 1
    output = capsys.readouterr().out
    assert "Request failed: timeout" in output
    assert "Traceback" not in output


def test_no_color_option_is_passed_to_tui(monkeypatch):
    called = {}

    def fake_run_tui(webhook_url, note_path, timeout, auth_token, use_color=None, initial_question=None, **kwargs):
        called["use_color"] = use_color
        return 0

    monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)

    assert ask_cli.main(["--no-color"]) == 0
    assert called["use_color"] is False


def test_color_option_is_passed_to_tui(monkeypatch):
    called = {}

    def fake_run_tui(webhook_url, note_path, timeout, auth_token, use_color=None, initial_question=None, **kwargs):
        called["use_color"] = use_color
        return 0

    monkeypatch.setattr(ask_cli, "run_tui", fake_run_tui)

    assert ask_cli.main(["--color"]) == 0
    assert called["use_color"] is True


def test_help_documents_tui_first_and_script_options(capsys):
    with pytest.raises(SystemExit) as exc:
        ask_cli.main(["--help"])

    assert exc.value.code == 0
    output = capsys.readouterr().out
    assert "TUI first" in output
    assert "Usage examples" in output
    assert "--text" in output
    assert "--json" in output
    assert "--raw-json" in output
    assert "--dry-run" in output
    assert "--version" in output
    assert "--no-color" in output


def test_version_option_prints_version(capsys):
    with pytest.raises(SystemExit) as exc:
        ask_cli.main(["--version"])

    assert exc.value.code == 0
    assert "Synapse Ask" in capsys.readouterr().out


def test_one_shot_text_output_is_answer_only():
    result = {"mode": "dry-run", "question": "What is Synapse?", "answer": "Synapse is a lab.", "sources": []}

    assert ask_formatting.format_one_shot_output(result, "text") == "Synapse is a lab."


def test_one_shot_json_output_wraps_compatibility_json_node():
    result = {"mode": "dry-run", "question": "What is Synapse?", "answer": "Synapse is a lab.", "sources": []}

    output = ask_formatting.format_one_shot_output(result, "json")

    assert output.startswith("{\n")
    assert '"json"' in output
    assert '"answer": "Synapse is a lab."' in output


def test_output_option_selects_json_format(monkeypatch, capsys):
    monkeypatch.setattr(
        ask_cli,
        "ask_question",
        lambda question, webhook_url, note_path, timeout, auth_token, *filters, **kwargs: {
            "mode": "dry-run",
            "question": question,
            "answer": "selected output",
            "sources": [],
        },
    )

    assert ask_cli.main(["--output", "json", "What is Synapse?"]) == 0
    assert '"json"' in capsys.readouterr().out


def test_one_shot_raw_json_output_preserves_legacy_shape():
    result = {"mode": "dry-run", "question": "What is Synapse?", "answer": "Synapse is a lab.", "sources": []}

    output = ask_formatting.format_one_shot_output(result, "raw-json")

    assert '"json"' not in output
    assert '"mode": "dry-run"' in output
