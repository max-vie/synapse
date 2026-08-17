"""Curses rendering for the Synapse Ask full-screen TUI."""

from __future__ import annotations

import re
import textwrap

try:
    import curses
except ImportError:  # pragma: no cover - curses is available on the target Linux host.
    curses = None  # type: ignore[assignment]

from .formatting import SYNAPSE_LOGO, format_sources, terminal_plain_text
from .tui_state import slash_option_lines
from .version import APP_VERSION

TUI_ACCENT_PAIR = 1
TUI_DIM_PAIR = 2
TUI_HIGHLIGHT_PAIR = 3

def safe_addstr(screen: object, y: int, x: int, text: str, *attrs: object) -> None:
    # Curses throws if a write lands exactly on a terminal edge. Dropping that
    # one draw call is better than killing the whole TUI.
    try:
        screen.addstr(y, x, text, *attrs)
    except Exception:
        pass


def init_tui_colors() -> None:
    if curses is None:
        return
    try:
        curses.start_color()
        curses.use_default_colors()
        # Orange looks good in 256-color terminals; yellow is the safe fallback.
        accent_color = 208 if getattr(curses, "COLORS", 0) >= 256 else curses.COLOR_YELLOW
        curses.init_pair(TUI_ACCENT_PAIR, accent_color, -1)
        curses.init_pair(TUI_DIM_PAIR, curses.COLOR_WHITE, -1)
        curses.init_pair(TUI_HIGHLIGHT_PAIR, curses.COLOR_CYAN, -1)
    except Exception:
        pass


def tui_attr(pair: int, *flags: int) -> int:
    if curses is None:
        return 0
    try:
        value = curses.color_pair(pair)
        for flag in flags:
            value |= flag
        return value
    except Exception:
        return 0


def wrap_for_screen(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for raw_line in str(text).splitlines() or [""]:
        lines.extend(textwrap.wrap(raw_line, width=max(10, width)) or [""])
    return lines


def transcript_lines(state: dict[str, object], width: int) -> list[str]:
    # Flatten the chat history into screen rows once, then the draw step can
    # just slice it for the current viewport.
    lines: list[str] = []
    messages = state["messages"]
    assert isinstance(messages, list)
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "system"))
        if role == "user":
            continue
        prefix = {"user": "You", "assistant": "Synapse", "error": "Error", "system": "System"}.get(role, role.title())
        message_text = str(message.get("text", ""))
        if role == "assistant":
            message_text = terminal_plain_text(message_text)
        wrapped = wrap_for_screen(message_text, width - 4)
        lines.append(f"{prefix}: {wrapped[0] if wrapped else ''}")
        lines.extend(f"  {line}" for line in wrapped[1:])
        sources = message.get("sources") or []
        if isinstance(sources, list) and sources:
            source_result = {"sources": sources}
            lines.extend(f"  {line}" for line in format_sources(source_result, width - 4))
        lines.append("")
    return lines or ["System: Ready"]


def _is_thinking_placeholder(text: str) -> bool:
    # Spinner messages like "◜ Thinking" are animation placeholders, not real
    # answers.  They should not appear in the "Latest answer" preview panel.
    stripped = text.strip()
    return stripped.endswith(" Thinking") and len(stripped) > len(" Thinking")


def latest_answer_preview_lines(state: dict[str, object], width: int) -> list[str]:
    # The right panel shows only the most recent real assistant answer,
    # compactly.  Spinner placeholders like "◜ Thinking" are skipped so the
    # panel never shows an ephemeral animation frame as if it were content.
    messages = state["messages"]
    assert isinstance(messages, list)
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        text = terminal_plain_text(str(message.get("text", ""))).strip()
        if not text or _is_thinking_placeholder(text):
            continue
        return wrap_for_screen(text, width)[:2]
    return []


def draw_box(screen: object, top: int, left: int, height: int, width: int, title: str = "") -> None:
    if height < 2 or width < 4:
        return
    title_text = f" {title} " if title else ""
    top_line = "╭" + title_text + "─" * max(0, width - len(title_text) - 2) + "╮"
    bottom_line = "╰" + "─" * max(0, width - 2) + "╯"
    safe_addstr(screen, top, left, top_line[:width])
    for row in range(top + 1, top + height - 1):
        safe_addstr(screen, row, left, "│")
        safe_addstr(screen, row, left + width - 1, "│")
    safe_addstr(screen, top + height - 1, left, bottom_line[:width])


def startup_recent_activity(state: dict[str, object]) -> str:
    # Keep the welcome card calm. It should summarize the last useful event, not
    # echo internal startup text or dump a whole answer into the right column.
    ready = "Ready: /notes live indexed notes, /local-notes local vault; ask cited questions."
    messages = state.get("messages", [])
    if not isinstance(messages, list) or not messages:
        return ready
    last = messages[-1]
    if not isinstance(last, dict):
        return ready
    role = str(last.get("role", "system"))
    text = str(last.get("text", "")).strip()
    if role == "system" and text.startswith("Synapse Ask full-screen TUI."):
        return ready
    prefix = {"user": "You", "assistant": "Synapse", "error": "Error", "system": "System"}.get(role, role.title())
    first_sentence = re.split(r"(?<=[.!?])\s+", terminal_plain_text(text) or ready, maxsplit=1)[0]
    return f"{prefix}: {first_sentence}"


def has_chat_activity(state: dict[str, object]) -> bool:
    messages = state.get("messages", [])
    if not isinstance(messages, list):
        return False
    return any(isinstance(message, dict) and message.get("role") in {"user", "assistant", "error"} for message in messages)


def tui_main_region(width: int) -> tuple[int, int]:
    # The app should look centered on wide terminals but still fit inside small
    # SSH panes. Cap the main region instead of letting long lines sprawl.
    main_width = min(max(70, width - 4), 108)
    left = max(0, (width - main_width) // 2)
    return left, main_width


def draw_startup_card(screen: object, top: int, width: int, mode: str, state: dict[str, object], accent: int, dim: int) -> tuple[int, int, int]:
    # The top card is the "first impression" screen: logo on the left, practical
    # tips and recent activity on the right. The returned geometry tells the
    # rest of the renderer where the prompt/transcript can start.
    card_left, card_width = tui_main_region(width)
    card_height = 11
    title = f" Synapse Ask v{APP_VERSION} "
    top_line = "┌" + title + "─" * max(0, card_width - len(title) - 2) + "┐"
    bottom_line = "└" + "─" * max(0, card_width - 2) + "┘"

    split_x = card_left + card_width // 2

    safe_addstr(screen, top, card_left, top_line[:card_width], accent)
    for row in range(top + 1, top + card_height - 1):
        safe_addstr(screen, row, card_left, "│", accent)
        safe_addstr(screen, row, split_x, "│", accent)
        safe_addstr(screen, row, card_left + card_width - 1, "│", accent)
    safe_addstr(screen, top + card_height - 1, card_left, bottom_line[:card_width], accent)

    logo_lines = SYNAPSE_LOGO.splitlines()[:5]
    logo_width = max(len(line) for line in logo_lines)
    left_inner_width = max(1, split_x - (card_left + 1))
    left_x = card_left + 1 + max(0, (left_inner_width - logo_width) // 2)
    for offset, logo_line in enumerate(logo_lines):
        safe_addstr(screen, top + 2 + offset, left_x, logo_line, accent)

    right_x = split_x + 3
    right_width = max(10, card_left + card_width - right_x - 2)
    preview_lines = latest_answer_preview_lines(state, right_width)
    tips: list[tuple[str, int]] = [
        ("Live RAG workflow", accent),
        ("Ask a question from your notes", dim),
        ("Answers show Markdown sources", dim),
        ("Type /help for commands", dim),
    ]
    if preview_lines:
        tips.append(("", dim))
        tips.append(("Latest answer", accent))
        tips.extend((line, dim) for line in preview_lines)
    for offset, (line, attr) in enumerate(tips[: card_height - 2]):
        safe_addstr(screen, top + 1 + offset, right_x, line[:right_width], attr)
    return top + card_height, card_left, card_width


def draw_tui(screen: object, state: dict[str, object], webhook_url: str = "", dry_run_enabled: bool = False) -> None:
    height, width = screen.getmaxyx()
    width = max(70, width)
    height = max(18, height)
    mode = "DRY RUN" if dry_run_enabled else "LIVE"
    screen.erase()

    accent = tui_attr(TUI_ACCENT_PAIR, curses.A_BOLD if curses is not None else 0)
    dim = tui_attr(TUI_DIM_PAIR)
    highlight = tui_attr(TUI_HIGHLIGHT_PAIR, curses.A_BOLD if curses is not None else 0)

    card_bottom, main_left, main_width = draw_startup_card(screen, 1 if height > 21 else 0, width, mode, state, accent, dim)
    chat_active = has_chat_activity(state)

    # Before the first question, keep the screen simple: welcome card + prompt.
    # After chat starts, the same area becomes a scrollable transcript.
    if chat_active:
        footer_y = height - 1
        input_y = height - 3
        transcript_top = card_bottom + 1
        transcript_height = max(2, input_y - transcript_top - 1)
        transcript_width = main_width
        content_width = max(10, transcript_width - 4)
        lines = transcript_lines(state, content_width)
        visible_height = max(1, transcript_height)
        max_scroll = max(0, len(lines) - visible_height)
        raw_scroll = state.get("scroll", 0)
        scroll_value = int(raw_scroll) if isinstance(raw_scroll, (int, str)) else 0
        scroll = min(max(0, scroll_value), max_scroll)
        state["scroll"] = scroll
        start = max(0, len(lines) - visible_height - scroll)
        visible = lines[start : start + visible_height]
        for offset, line in enumerate(visible):
            safe_addstr(screen, transcript_top + offset, main_left + 2, line[:content_width])
        if max_scroll:
            scroll_hint = f"↑ PgUp/PgDn scroll {scroll}/{max_scroll}"
            safe_addstr(screen, max(card_bottom + 1, input_y - 2), main_left + max(2, transcript_width - len(scroll_hint) - 2), scroll_hint[: max(1, transcript_width - 4)], dim)
    else:
        input_y = min(height - 4, card_bottom + 3)
        footer_y = min(height - 1, input_y + 3)

    prompt_rule_y = max(card_bottom, input_y - 2)
    safe_addstr(screen, prompt_rule_y, main_left, "─" * max(1, main_width), dim)
    prompt = "> "
    user_input = str(state["input"])
    safe_addstr(screen, input_y, main_left, (prompt + user_input)[: max(1, main_width)], highlight)

    footer = "/ opens options  ·  /help commands  ·  /notes live  ·  /local-notes vault"
    if bool(state.get("slash_menu")):
        # Typing "/" swaps the normal footer for a lightweight command palette.
        # It is just text, so it works in screenshots and headless tests too.
        options = "  ".join(slash_option_lines(state).splitlines()[:3])
        footer = options or footer
    safe_addstr(screen, footer_y, main_left, footer[: max(1, main_width)], dim)

    cursor = min(int(str(state["cursor"])), max(0, main_width - 4))
    try:
        getattr(screen, "move")(input_y, main_left + len(prompt) + cursor)
    except Exception:
        pass
    screen.refresh()

