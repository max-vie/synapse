"""Pure state transitions for the Synapse Ask TUI.

The ``TuiState`` dataclass replaces the raw dictionaries that were previously
threaded through every function. It preserves dict-like access (``state["key"]``,
``state.get("key")``, ``state["key"] = value``) so that the existing rendering
code, tests, and curses integration continue to work without changes.

Animation constants and functions (spinner, reveal) live in ``tui_runner`` —
this module contains only state shape and command parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

KEY_ENTER = 10
KEY_BACKSPACE = 127
KEY_CTRL_C = 3
KEY_CTRL_L = 12
KEY_CTRL_Q = 17
KEY_ESC = 27
CURSES_KEY_ENTER = 343
CURSES_KEY_BACKSPACE = 263
CURSES_KEY_LEFT = 260
CURSES_KEY_RIGHT = 261
CURSES_KEY_HOME = 262
CURSES_KEY_END = 360
CURSES_KEY_PPAGE = 339
CURSES_KEY_NPAGE = 338
CURSES_KEY_RESIZE = 410


@dataclass
class TuiState:
    """Typed, mutable TUI session state with dict-like access for backward compat.

    Every attribute has a stable default so ``TuiState()`` is equivalent to the
    old ``new_tui_state()`` call. The ``__getitem__`` / ``__setitem__`` / ``get``
    protocol means existing ``state["input"]`` references keep working.
    """

    messages: list[dict[str, Any]] = field(default_factory=list)
    input: str = ""
    cursor: int = 0
    scroll: int = 0
    status: str = "Ready"
    running: bool = True
    history: list[str] = field(default_factory=list)
    history_index: int | None = None
    answer_history: list[dict[str, Any]] = field(default_factory=list)
    slash_menu: bool = False

    # -- dict-like access for backward compatibility --

    _KEY_MAP: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __setitem__(self, key: str, value: Any) -> None:
        setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return getattr(self, key)
        except AttributeError:
            return default

    def setdefault(self, key: str, default: Any = None) -> Any:
        if not hasattr(self, key) or getattr(self, key) is None:
            setattr(self, key, default)
        return getattr(self, key)


def new_tui_state(initial_question: str | None = None) -> dict[str, object]:
    # Backward-compatible factory. Returns a TuiState (which supports dict
    # access) so existing callers that annotate ``dict[str, object]`` still work.
    question = initial_question or ""
    return TuiState(
        input=question,
        cursor=len(question),
        slash_menu=question.startswith("/"),
    )  # type: ignore[return-value]


def add_tui_message(state: dict[str, object], role: str, text: str, sources: list[object] | None = None) -> dict[str, object]:
    # Messages are plain dicts because curses rendering, line-mode fallback, and
    # tests all read the same small shape: role, text, and optional sources.
    messages = state["messages"]
    assert isinstance(messages, list)
    message = {"role": role, "text": text, "sources": sources or []}
    messages.append(message)
    return message


def replace_tui_message(message: dict[str, object], role: str, text: str, sources: list[object] | None = None) -> None:
    # The spinner and answer reveal update one existing assistant message. That
    # avoids flooding the transcript with every animation frame.
    message["role"] = role
    message["text"] = text
    message["sources"] = sources or []


def remember_tui_answer(state: dict[str, object], text: str, sources: list[object] | None = None) -> int:
    """Store an assistant answer so `/!nn` can replay it later."""
    history = state.setdefault("answer_history", [])
    assert isinstance(history, list)
    entry = {"number": len(history) + 1, "text": text, "sources": sources or []}
    history.append(entry)
    return int(entry["number"])

# Slash commands are intentionally tiny and local. Anything that can trigger a
# live RAG call should go through normal question submission instead.
SLASH_OPTIONS = {
    "/help": "Show commands and keybindings",
    "/notes": "List indexed notes from live Synapse",
    "/local-notes": "Browse local vault Markdown files",
    "/!1": "Show answer 1 again",
    "/clear": "Clear the transcript",
    "/quit": "Exit Synapse Ask",
}


def slash_option_lines(state: dict[str, object]) -> str:
    typed = str(state.get("input", ""))
    query = typed.lower().strip()
    options = [f"{name} — {description}" for name, description in SLASH_OPTIONS.items() if name.startswith(query) or query in name]
    if not options:
        options = ["No matching slash commands"]
    return "\n".join(options)


def apply_tui_command(command: str, state: dict[str, object], notes_root: Path | None = None) -> dict[str, object]:
    """Apply one local slash command and return an action for the UI runner."""
    # Commands update state and return a tiny action object for the event loop.
    # That split keeps the loop small and keeps command tests straightforward.
    normalized_command = command.strip().lower()
    state["slash_menu"] = False
    if normalized_command in {"/q", "/quit", "quit", "exit"}:
        state["running"] = False
        state["status"] = "Bye"
        return {"action": "quit"}
    if normalized_command == "/clear":
        state["messages"] = []
        add_tui_message(state, "system", "Transcript cleared. Ask another question or use /quit.")
        state["status"] = "Cleared"
        state["scroll"] = 0
        return {"action": "continue"}
    if normalized_command == "/notes" or normalized_command.startswith("/notes "):
        return {"action": "notes", "query": command.strip()[len("/notes") : ].strip()}
    if normalized_command == "/local-notes" or normalized_command.startswith("/local-notes "):
        return {"action": "local-notes", "query": command.strip()[len("/local-notes") : ].strip()}
    if normalized_command.startswith("/!") and normalized_command[2:].isdigit():
        number = int(normalized_command[2:])
        answer_history = state.get("answer_history", [])
        if isinstance(answer_history, list) and 1 <= number <= len(answer_history):
            saved_answer = answer_history[number - 1]
            if isinstance(saved_answer, dict):
                sources = (
                    saved_answer.get("sources")
                    if isinstance(saved_answer.get("sources"), list)
                    else []
                )
                add_tui_message(
                    state,
                    "assistant",
                    str(saved_answer.get("text") or ""),
                    sources,
                )
                state["status"] = f"Answer {number} shown"
                return {"action": "continue"}
        add_tui_message(state, "system", "No answer with that number.")
        state["status"] = "Answer not found"
        return {"action": "continue"}
    if normalized_command == "/help":
        add_tui_message(
            state,
            "system",
            "Commands: /help show this message, /notes list live Synapse indexed notes, /local-notes browse local vault, /!1 show answer 1 again, /clear clear transcript, /quit exit. Keys: / opens options, Enter send, Ctrl-Q quit, Ctrl-L clear, PgUp/PgDn scroll.",
        )
        state["status"] = "Help shown"
        return {"action": "continue"}
    return {"action": "unknown", "command": command}


def handle_tui_key(key: int, state: dict[str, object]) -> dict[str, object] | None:
    """Translate one key into an edit, local command, or submit action."""
    # Do the editing math here instead of inside curses drawing code. It is less
    # glamorous, but it is the part most likely to break in headless tests.
    input_buffer = str(state["input"])
    cursor = int(state["cursor"])

    if key in {KEY_CTRL_C, KEY_CTRL_Q, KEY_ESC}:
        state["running"] = False
        return {"action": "quit"}
    if key == KEY_CTRL_L:
        return apply_tui_command("/clear", state)
    if key in {KEY_ENTER, 13, CURSES_KEY_ENTER}:
        # Enter is the one place where input turns into an action. Commands are
        # handled locally; regular text becomes a RAG question for the caller.
        question = input_buffer.strip()
        state["input"] = ""
        state["cursor"] = 0
        if not question:
            state["slash_menu"] = False
            return None
        if question.startswith("/") or question in {"quit", "exit"}:
            return apply_tui_command(question, state)
        question_history = state["history"]
        assert isinstance(question_history, list)
        question_history.append(question)
        state["history_index"] = None
        return {"action": "submit", "question": question}
    if key in {KEY_BACKSPACE, 8, CURSES_KEY_BACKSPACE}:
        # Keep cursor movement and text mutation together. That makes insert,
        # backspace, and arrow-key behavior predictable in both curses and tests.
        if cursor > 0:
            updated = input_buffer[: cursor - 1] + input_buffer[cursor:]
            state["input"] = updated
            state["cursor"] = cursor - 1
            state["slash_menu"] = updated.startswith("/")
        return None
    if key in {CURSES_KEY_LEFT}:
        state["cursor"] = max(0, cursor - 1)
        return None
    if key in {CURSES_KEY_RIGHT}:
        state["cursor"] = min(len(input_buffer), cursor + 1)
        return None
    if key in {CURSES_KEY_HOME}:
        state["cursor"] = 0
        return None
    if key in {CURSES_KEY_END}:
        state["cursor"] = len(input_buffer)
        return None
    if key in {CURSES_KEY_PPAGE}:
        state["scroll"] = int(state["scroll"]) + 5
        return None
    if key in {CURSES_KEY_NPAGE}:
        state["scroll"] = max(0, int(state["scroll"]) - 5)
        return None
    if 32 <= key <= 126:
        char = chr(key)
        updated = input_buffer[:cursor] + char + input_buffer[cursor:]
        state["input"] = updated
        state["cursor"] = cursor + 1
        state["slash_menu"] = updated.startswith("/")
    return None
