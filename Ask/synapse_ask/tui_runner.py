"""Runtime loops for curses and line-mode Synapse Ask TUI."""

from __future__ import annotations

import concurrent.futures
import os
import sys
import time
from pathlib import Path

try:
    import curses
except ImportError:  # pragma: no cover - curses is available on the target Linux host.
    curses = None  # type: ignore[assignment]

from .client import ask_question, list_indexed_notes
from .formatting import display_answer_text, is_error_result, normalize_rag_result, render_tui_screen, result_sources
from .notes import find_available_notes, format_local_notes, resolve_vault
from .tui_render import draw_tui, init_tui_colors
from .tui_state import add_tui_message, apply_tui_command, handle_tui_key, new_tui_state, remember_tui_answer, replace_tui_message

# Animation constants — only the runner needs these, not the state module.
THINKING_SPINNER_FRAMES = ("◜", "◝", "◞", "◟")
THINKING_FRAME_DELAY = 0.08
ANSWER_REVEAL_CHARS_PER_FRAME = 3
ANSWER_REVEAL_DELAY = 0.035


def thinking_status(frame_index: int = 0) -> str:
    spinner = THINKING_SPINNER_FRAMES[frame_index % len(THINKING_SPINNER_FRAMES)]
    return f"{spinner} Thinking"

def animate_pending_tui_request(
    state: dict[str, object],
    placeholder: dict[str, object],
    future: concurrent.futures.Future[dict[str, object]],
    on_thinking=None,
) -> None:
    frame_index = 0
    while not future.done():
        status = thinking_status(frame_index)
        replace_tui_message(placeholder, "assistant", status)
        state["status"] = status
        if on_thinking is not None:
            on_thinking()
        frame_index += 1
        time.sleep(THINKING_FRAME_DELAY)


def answer_reveal_frames(answer: str, chunk_size: int | None = None) -> list[str]:
    # Slice the answer into deterministic frames. Tests can assert these frames
    # without waiting on curses timing.
    text = str(answer)
    size = max(1, int(ANSWER_REVEAL_CHARS_PER_FRAME if chunk_size is None else chunk_size))
    if not text:
        return [""]
    return [text[:index] for index in range(size, len(text), size)] + [text]


def format_indexed_notes(notes: list[dict[str, object]]) -> str:
    """Render a short readable `/notes` result."""
    if not notes:
        return "No indexed Markdown notes found."
    lines = ["Indexed Markdown notes:"]
    for note in notes[:12]:
        source_path = str(note.get("source_path") or "").strip()
        title = str(note.get("title") or "").strip()
        suffix = f" — {title}" if title else ""
        lines.append(f"- {source_path}{suffix}" if source_path else f"- {title}")
    return "\n".join(lines)


def add_indexed_notes_message(
    state: dict[str, object],
    webhook_url: str,
    query: str,
    timeout: int,
    auth_token: str,
    dry_run_enabled: bool = False,
    debug: bool = False,
) -> None:
    # /notes queries the live Synapse service for indexed note sources.
    # If no webhook URL is configured and dry-run is not active, show a clear
    # message instead of silently falling back to local vault browsing.
    if webhook_url:
        notes = list_indexed_notes(webhook_url, query=query, timeout=timeout, auth_token=auth_token, debug=debug)
        add_tui_message(state, "system", format_indexed_notes(notes))
        state["status"] = f"Found {len(notes)} indexed note(s)" if notes else "No notes found"
    elif dry_run_enabled:
        # Dry-run mode: show local vault files so operators can preview without
        # a live service. Labeled clearly as vault browsing, not live indexing.
        vault_root, label = resolve_vault()
        local_notes = find_available_notes(vault_root, query=query)
        add_tui_message(state, "system", format_local_notes(local_notes, label, vault_root))
        state["status"] = f"Found {len(local_notes)} local note(s)" if local_notes else "No local notes found"
    else:
        add_tui_message(
            state,
            "system",
            "No live Synapse webhook configured; use --dry-run for local note preview, or /local-notes to browse the vault.",
        )
        state["status"] = "No webhook configured"


def add_local_notes_message(
    state: dict[str, object],
    query: str,
    vault_path: str | None = None,
) -> None:
    # /local-notes always browses the local vault, regardless of webhook or
    # dry-run state. This is the safe offline-friendly command.
    vault_root, label = resolve_vault(vault_path)
    local_notes = find_available_notes(vault_root, query=query)
    add_tui_message(state, "system", format_local_notes(local_notes, label, vault_root))
    state["status"] = f"Found {len(local_notes)} local note(s)" if local_notes else "No local notes found"


def animate_tui_answer_reveal(
    state: dict[str, object],
    message: dict[str, object],
    answer: str,
    sources: list[object],
    on_answer_reveal=None,
) -> None:
    for frame in answer_reveal_frames(answer):
        replace_tui_message(message, "assistant", frame)
        state["status"] = "Writing answer..."
        if on_answer_reveal is not None:
            on_answer_reveal()
        if ANSWER_REVEAL_DELAY > 0:
            time.sleep(ANSWER_REVEAL_DELAY)
    replace_tui_message(message, "assistant", answer, sources)
    state["status"] = "Ready"
    if on_answer_reveal is not None:
        on_answer_reveal()

def submit_tui_question(
    state: dict[str, object],
    question: str,
    webhook_url: str,
    note_path: Path | None,
    timeout: int,
    auth_token: str,
    source_path: str = "",
    note_id: str = "",
    wiki_path: str = "",
    exact_run_id: str = "",
    dry_run_enabled: bool = False,
    debug: bool = False,
    on_thinking=None,
    on_answer_reveal=None,
) -> None:
    # Add the user's question immediately, then replace the placeholder as the
    # request moves from "thinking" to either an error or the final answer.
    add_tui_message(state, "user", question)
    placeholder = add_tui_message(state, "assistant", thinking_status(0))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            # Run the blocking HTTP/local preview work off the UI thread so the
            # spinner still moves while the request is waiting on Synapse.
            future = executor.submit(
                ask_question,
                question,
                webhook_url,
                note_path,
                timeout,
                auth_token,
                source_path,
                note_id,
                wiki_path,
                exact_run_id,
                dry_run_enabled,
                debug=debug,
            )
            animate_pending_tui_request(state, placeholder, future, on_thinking)
            result = normalize_rag_result(future.result(), require_sources=bool(webhook_url and not dry_run_enabled))
        answer = display_answer_text(result, "No answer returned.")
        sources = result_sources(result)
        if is_error_result(result):
            replace_tui_message(placeholder, "error", answer)
            state["status"] = "Request failed"
        else:
            animate_tui_answer_reveal(state, placeholder, answer, sources, on_answer_reveal)
            remember_tui_answer(state, answer, sources)
    except Exception as exc:  # noqa: BLE001 - TUI should surface readable errors.
        replace_tui_message(placeholder, "error", f"Request failed: {exc}")
        state["status"] = "Request failed"


def run_curses_tui(
    screen: object,
    webhook_url: str,
    note_path: Path | None,
    timeout: int,
    auth_token: str,
    initial_question: str | None = None,
    source_path: str = "",
    note_id: str = "",
    wiki_path: str = "",
    exact_run_id: str = "",
    dry_run_enabled: bool = False,
    debug: bool = False,
    vault_path: str | None = None,
) -> int:
    # The real app loop is deliberately boring: draw current state, read one
    # key, turn that key into an action, then handle only the action here.
    state = new_tui_state(initial_question)
    init_tui_colors()
    try:
        screen.keypad(True)
    except Exception:
        pass
    while bool(state["running"]):
        draw_tui(screen, state, webhook_url, dry_run_enabled)
        try:
            key = screen.getch()
        except KeyboardInterrupt:
            break
        action = handle_tui_key(key, state)
        if action and action.get("action") == "notes":
            try:
                add_indexed_notes_message(state, webhook_url, str(action.get("query") or ""), timeout, auth_token, dry_run_enabled, debug)
            except Exception as exc:  # noqa: BLE001 - TUI should surface readable command errors.
                add_tui_message(state, "error", f"Request failed: {exc}")
                state["status"] = "Request failed"
        if action and action.get("action") == "local-notes":
            try:
                add_local_notes_message(state, str(action.get("query") or ""), vault_path)
            except Exception as exc:  # noqa: BLE001
                add_tui_message(state, "error", f"Local vault error: {exc}")
                state["status"] = "Local vault error"
        if action and action.get("action") == "submit":
            submit_tui_question(
                state,
                str(action["question"]),
                webhook_url,
                note_path,
                timeout,
                auth_token,
                source_path,
                note_id,
                wiki_path,
                exact_run_id,
                dry_run_enabled,
                debug=debug,
                on_thinking=lambda: draw_tui(screen, state, webhook_url, dry_run_enabled),
                on_answer_reveal=lambda: draw_tui(screen, state, webhook_url, dry_run_enabled),
            )
    return 0


def run_line_tui(
    webhook_url: str,
    note_path: Path | None,
    timeout: int,
    auth_token: str,
    input_func=input,
    output_func=print,
    use_color: bool | None = None,
    initial_question: str | None = None,
    source_path: str = "",
    note_id: str = "",
    wiki_path: str = "",
    exact_run_id: str = "",
    dry_run_enabled: bool = False,
    debug: bool = False,
    vault_path: str | None = None,
) -> int:
    # This is both a fallback for machines without curses and the test seam for
    # the interactive path. It is not fancy, but it lets CI exercise the same
    # command/question flow without needing a real terminal.
    color_enabled = sys.stdout.isatty() if use_color is None else use_color
    state = new_tui_state(initial_question)
    startup_mode = "dry-run" if dry_run_enabled else "live"
    startup_hint = (
        "Dry-run preview is enabled. Live RAG calls are skipped."
        if dry_run_enabled
        else "Ask a question about your notes. Configure SYNAPSE_ASK_WEBHOOK_URL for live answers."
    )
    output_func(
        render_tui_screen(
            initial_question or "What can I ask?",
            {"mode": startup_mode, "answer": startup_hint, "sources": []},
            webhook_url,
            color_enabled,
            dry_run_enabled=dry_run_enabled,
        )
    )

    if initial_question:
        try:
            result = ask_question(initial_question, webhook_url, note_path, timeout, auth_token, source_path, note_id, wiki_path, exact_run_id, dry_run_enabled, debug=debug)
            result = normalize_rag_result(result, require_sources=bool(webhook_url and not dry_run_enabled))
        except Exception as exc:  # noqa: BLE001 - CLI should surface readable errors.
            result = {"mode": "error", "answer": f"Request failed: {exc}", "sources": []}
        output_func(render_tui_screen(initial_question, result, webhook_url, color_enabled, dry_run_enabled=dry_run_enabled))
        if not is_error_result(result):
            remember_tui_answer(state, display_answer_text(result, "No answer returned."), result_sources(result))

    while True:
        try:
            question = input_func("synapse> ").strip()
        except (EOFError, KeyboardInterrupt):
            output_func("\nbye")
            return 0

        if not question:
            continue

        # All slash commands and bare quit/exit go through the same
        # apply_tui_command parser that curses mode uses, so both modes
        # have identical command behaviour.
        if question.startswith("/") or question in {"quit", "exit"}:
            before = len(state.get("messages", []))
            action = apply_tui_command(question, state)
            if action.get("action") == "quit":
                output_func("bye")
                return 0
            if action.get("action") == "continue" and question.strip().lower() == "/clear":
                if color_enabled:
                    output_func("\033c")
                output_func(
                    render_tui_screen(
                        "What can I ask?",
                        {"mode": startup_mode, "answer": "Screen cleared. Ask another question or use /quit.", "sources": []},
                        webhook_url,
                        color_enabled,
                        dry_run_enabled=dry_run_enabled,
                    )
                )
                continue
            if action.get("action") == "notes":
                try:
                    add_indexed_notes_message(state, webhook_url, str(action.get("query") or ""), timeout, auth_token, dry_run_enabled, debug)
                except Exception as exc:  # noqa: BLE001 - command should be readable in line mode.
                    add_tui_message(state, "error", f"Request failed: {exc}")
            if action.get("action") == "local-notes":
                try:
                    add_local_notes_message(state, str(action.get("query") or ""), vault_path)
                except Exception as exc:  # noqa: BLE001
                    add_tui_message(state, "error", f"Local vault error: {exc}")
            messages = state.get("messages")
            if action.get("action") == "unknown":
                output_func(f"Unknown command: {question}")
            elif isinstance(messages, list) and len(messages) > before:
                output_func("\n".join(str(message.get("text", "")) for message in messages[before:] if isinstance(message, dict)))
            continue

        try:
            result = ask_question(question, webhook_url, note_path, timeout, auth_token, source_path, note_id, wiki_path, exact_run_id, dry_run_enabled, debug=debug)
            result = normalize_rag_result(result, require_sources=bool(webhook_url and not dry_run_enabled))
        except Exception as exc:  # noqa: BLE001 - CLI should surface readable errors.
            result = {"mode": "error", "answer": f"Request failed: {exc}", "sources": []}
        output_func(render_tui_screen(question, result, webhook_url, color_enabled, dry_run_enabled=dry_run_enabled))
        if not is_error_result(result):
            remember_tui_answer(state, display_answer_text(result, "No answer returned."), result_sources(result))


def run_tui(
    webhook_url: str,
    note_path: Path | None,
    timeout: int,
    auth_token: str,
    input_func=None,
    output_func=None,
    use_color: bool | None = None,
    initial_question: str | None = None,
    source_path: str = "",
    note_id: str = "",
    wiki_path: str = "",
    exact_run_id: str = "",
    dry_run_enabled: bool = False,
    debug: bool = False,
    vault_path: str | None = None,
) -> int:
    # Tests pass fake input/output functions, real users get curses when it is
    # available, and CI still has a line-mode escape hatch for known init
    # failures. Unexpected TUI errors propagate unless the user explicitly opts
    # into line-mode fallback via SYNAPSE_ASK_FALLBACK_ON_TUI_ERROR=true.
    line_tui_kwargs = dict(
        webhook_url=webhook_url,
        note_path=note_path,
        timeout=timeout,
        auth_token=auth_token,
        use_color=use_color,
        initial_question=initial_question,
        source_path=source_path,
        note_id=note_id,
        wiki_path=wiki_path,
        exact_run_id=exact_run_id,
        dry_run_enabled=dry_run_enabled,
        debug=debug,
        vault_path=vault_path,
    )
    if input_func is not None or output_func is not None:
        return run_line_tui(
            input_func=input_func or input,
            output_func=output_func or print,
            **line_tui_kwargs,
        )
    if curses is None:
        return run_line_tui(**line_tui_kwargs)
    try:
        return curses.wrapper(
            lambda screen: run_curses_tui(
                screen,
                webhook_url,
                note_path,
                timeout,
                auth_token,
                initial_question,
                source_path,
                note_id,
                wiki_path,
                exact_run_id,
                dry_run_enabled,
                debug=debug,
            )
        )
    except curses.error:
        # Known terminal init failure (setupterm, no tty, etc.) — fall back.
        return run_line_tui(**line_tui_kwargs)
    except Exception as exc:
        # Unexpected TUI errors should not be silently swallowed. Wrap with a
        # clear message so the operator knows what happened and how to recover.
        if os.environ.get("SYNAPSE_ASK_FALLBACK_ON_TUI_ERROR", "").lower() in ("true", "1", "yes"):
            return run_line_tui(**line_tui_kwargs)
        raise SystemExit(
            f"Synapse Ask TUI failed: {exc}\n"
            f"Set SYNAPSE_ASK_FALLBACK_ON_TUI_ERROR=true to fall back to line mode."
        ) from exc

