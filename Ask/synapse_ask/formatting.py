"""Output formatting and public-safe source rendering."""

from __future__ import annotations

import json
import re
import shutil
import textwrap


SYNAPSE_LOGO = r"""
 ____ __   __ _   _    _    ____  ____  _____
/ ___|\ \ / /| \ | |  / \  |  _ \/ ___|| ____|
\___ \ \ V / |  \| | / _ \ | |_) \___ \|  _|
 ___) | | |  | |\  |/ ___ \|  __/ ___) | |___
|____/  |_|  |_| \_/_/   \_\_|   |____/|_____|
""".strip("\n")

ANSI_RESET = "\033[0m"
ANSI_DIM = "\033[2m"
ANSI_CYAN = "\033[36m"
ANSI_BOLD = "\033[1m"

INSUFFICIENT_CONTEXT_ANSWER = "I do not have enough indexed note context to answer that reliably."
MISSING_WEBHOOK_MESSAGE = "Missing SYNAPSE_ASK_WEBHOOK_URL. Set it for live mode or pass --dry-run for a local preview."

SOURCE_LOCATOR_KEYS = ("source_path", "wiki_path", "note_id", "chunk_id", "path")
URL_SHAPED_RE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.IGNORECASE)

def terminal_width(default: int = 80) -> int:
    # Wide terminals make the ASCII UI sprawl; tiny terminals wrap into mush.
    return max(60, min(shutil.get_terminal_size((default, 24)).columns, 100))


def color(text: str, code: str, enabled: bool) -> str:
    return f"{code}{text}{ANSI_RESET}" if enabled else text


def rule(width: int) -> str:
    return "-" * width


def public_safe_value(value: object) -> str:
    # Empty strings, URLs, and absolute filesystem paths are not useful public
    # citations. A relative local note path, wiki path, note id, or chunk id is fine.
    text = str(value or "").strip()
    if not text or URL_SHAPED_RE.match(text):
        return ""
    if text.startswith("/"):
        return ""
    return text


def public_source_locator(source: dict[str, object]) -> str:
    for key in SOURCE_LOCATOR_KEYS:
        value = public_safe_value(source.get(key))
        if value:
            return value
    return ""


def result_sources(result: dict[str, object]) -> list[object]:
    # The workflow used "citations" early on and "sources" later. Normalize the
    # spelling once so the rest of the code does not care which generation of the
    # webhook response it received.
    sources = result.get("sources")
    if not isinstance(sources, list) or not sources:
        sources = result.get("citations")
    if not isinstance(sources, list):
        return []
    return sources


def source_has_stable_locator(source: object) -> bool:
    if not isinstance(source, dict):
        return False
    return bool(public_source_locator(source))


def has_grounding_sources(result: dict[str, object]) -> bool:
    return any(source_has_stable_locator(source) for source in result_sources(result))


def trailing_citation_numbers(answer: str) -> list[int]:
    # Only trust citations at the end of the answer, e.g. "... SPF. [1, 2]".
    # Bracketed numbers inside the body are not enough to prove grounding.
    match = re.search(r"(?:^|\s)\[([0-9,\s]+)\]\s*[.!?]?\s*$", answer)
    if not match:
        return []
    numbers: list[int] = []
    for part in match.group(1).split(","):
        part = part.strip()
        if part.isdigit():
            numbers.append(int(part))
    return numbers


def has_valid_answer_citation(result: dict[str, object]) -> bool:
    answer = str(result.get("answer") or result.get("response") or "")
    sources = result_sources(result)
    citation_numbers = trailing_citation_numbers(answer)
    if not citation_numbers:
        return False
    stable_indices = {index for index, source in enumerate(sources, start=1) if source_has_stable_locator(source)}
    if not stable_indices:
        return False
    if any(number < 1 or number > len(sources) for number in citation_numbers):
        return False
    return any(number in stable_indices for number in citation_numbers)


def is_error_result(result: dict[str, object]) -> bool:
    mode = str(result.get("mode") or "").strip().casefold()
    return mode == "error" or bool(result.get("error"))


def is_local_status_result(result: dict[str, object]) -> bool:
    mode = str(result.get("mode") or "").strip().casefold()
    answer = str(result.get("answer") or result.get("response") or "")
    return mode == "dry-run" and answer.startswith(("Ask a question", "Dry run only:"))


def normalize_rag_result(result: dict[str, object], *, require_sources: bool = False) -> dict[str, object]:
    # This is the safety gate for live mode. Dry-run/status/error messages pass
    # through, but real live answers need both a stable source locator and a
    # valid citation number. Otherwise we replace the answer with a refusal.
    normalized = dict(result)
    sources = result_sources(result)
    normalized["sources"] = sources
    should_require_sources = require_sources and not is_error_result(result) and not is_local_status_result(result)
    if should_require_sources and (
        bool(result.get("insufficient_context"))
        or not has_grounding_sources(result)
        or not has_valid_answer_citation(result)
    ):
        normalized["answer"] = INSUFFICIENT_CONTEXT_ANSWER
        normalized["response"] = INSUFFICIENT_CONTEXT_ANSWER
        normalized["insufficient_context"] = True
        normalized["sources"] = []
        normalized["citations"] = []
    return normalized


def terminal_plain_text(text: str) -> str:
    # Ask runs in a plain terminal, not a Markdown renderer. Strip the common
    # Markdown emphasis/link wrappers so answers read as normal terminal text.
    rendered = str(text)
    rendered = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", rendered)
    rendered = re.sub(r"`([^`]+)`", r"\1", rendered)
    rendered = re.sub(r"\*\*([^*]+)\*\*", r"\1", rendered)
    rendered = re.sub(r"__([^_]+)__", r"\1", rendered)
    rendered = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", rendered)
    rendered = re.sub(r"^#{1,6}\s+", "", rendered, flags=re.MULTILINE)
    return rendered


def display_answer_text(result: dict[str, object], fallback: str = "") -> str:
    # The webhook has returned both "answer" and "response" over time. Prefer
    # the human-facing answer text, then fall back to explicit errors.
    answer = result.get("answer") or result.get("response")
    if answer:
        return terminal_plain_text(str(answer))
    if result.get("error"):
        return terminal_plain_text(str(result["error"]))
    return fallback


def format_sources(result: dict[str, object], width: int) -> list[str]:
    # The workflow has returned both names over time. Accept both so old proof
    # artifacts and newer webhook responses render the same way. Keep this
    # public-safe: do not render URL-shaped source/source_url/url fields or bare ids.
    sources = result_sources(result)
    lines: list[str] = []
    if not isinstance(sources, list) or not sources:
        return ["Sources: none returned"]

    lines.append("Sources:")
    for index, source in enumerate(sources, start=1):
        if isinstance(source, dict):
            detail = public_source_locator(source)
            label = public_safe_value(source.get("title")) or detail or f"source {index}"
            value = f"[{index}] {label}"
            if detail and str(detail) != str(label):
                value += f" — {detail}"
        else:
            label = public_safe_value(source) or f"source {index}"
            value = f"[{index}] {label}"
        lines.extend(textwrap.wrap(value, width=width, subsequent_indent="    "))
    return lines


def render_tui_screen(
    question: str,
    result: dict[str, object],
    webhook_url: str = "",
    use_color: bool = False,
    width: int | None = None,
    dry_run_enabled: bool = False,
) -> str:
    # Plain-text renderer used by tests and by the line-mode fallback. The full
    # curses UI has its own renderer farther down.
    width = width or terminal_width()
    result = normalize_rag_result(result, require_sources=bool(webhook_url and not dry_run_enabled))
    body_width = width - 4
    if dry_run_enabled:
        mode = "dry-run"
    elif webhook_url:
        mode = "live Synapse webhook"
    else:
        mode = str(result.get("mode", "live"))
    answer = display_answer_text(result, "No answer returned.")

    lines = [
        color(SYNAPSE_LOGO, ANSI_CYAN, use_color),
        rule(width),
        f"{color('Synapse Ask', ANSI_BOLD, use_color)}  {color('interactive local RAG shell', ANSI_DIM, use_color)}",
        f"Mode: {mode}",
        rule(width),
        "Question:",
    ]
    lines.extend(textwrap.wrap(question, width=body_width) or [""])
    lines.extend(["", "Answer:"])
    lines.extend(textwrap.wrap(answer, width=body_width) or [""])
    lines.append("")
    lines.extend(format_sources(result, body_width))
    lines.extend(
        [
            rule(width),
            "Commands: /help  /notes  /local-notes  /!1  /clear  /quit",
        ]
    )
    return "\n".join(lines)


def format_one_shot_output(result: dict[str, object], output_format: str, *, require_sources: bool = False) -> str:
    # Script users choose exactly one stable output shape. --json keeps the compatibility
    # wrapper, while --raw-json is for callers that want the webhook object.
    result = normalize_rag_result(result, require_sources=require_sources)
    if output_format == "text":
        return display_answer_text(result)
    if output_format == "json":
        return json.dumps({"json": result}, indent=2, ensure_ascii=False)
    if output_format == "raw-json":
        return json.dumps(result, indent=2, ensure_ascii=False)
    raise ValueError(f"unsupported output format: {output_format}")

