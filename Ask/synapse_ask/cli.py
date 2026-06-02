"""Command-line interface for Synapse Ask."""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from pathlib import Path

from .client import ask_question
from .config import load_dotenv
from .formatting import format_one_shot_output, normalize_rag_result
from .tui_runner import run_tui
from .version import APP_VERSION


class AskHelpFormatter(argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter):
    pass


def build_parser() -> argparse.ArgumentParser:
    # - no flags: open the TUI
    # - bare question: prefill the TUI
    # - --text/--json/--raw-json/--output: one-shot script mode
    # - --dry-run: explicit local preview, never the hidden default
    parser = argparse.ArgumentParser(
        prog="synapse-ask",
        description="Synapse Ask — TUI first local RAG query tool.",
        epilog=textwrap.dedent(
            """
            Usage examples:
              python3 Ask/ask.py
              python3 Ask/ask.py --no-color
              python3 Ask/ask.py --text "What is Synapse?"
              python3 Ask/ask.py --json "What is Synapse?"
              python3 Ask/ask.py --dry-run --raw-json "What algorithm does OSPF use?" --note "examples/obsidian-vault/Synapse-Demo/example-study-notes.md"

            Modes:
              No arguments opens the interactive TUI.
              One-shot script output requires a question plus --text, --json, --raw-json, or --output.
              --json returns a nested compatibility object: {"json": {...}}.
            """
        ).strip(),
        formatter_class=AskHelpFormatter,
    )
    parser.add_argument("question", nargs="?", help="question to prefill in the TUI, or question for explicit one-shot script mode")
    parser.add_argument("--webhook-url", default=os.getenv("SYNAPSE_ASK_WEBHOOK_URL", ""), help="Synapse ask webhook URL")
    parser.add_argument("--note", type=Path, help="optional local note to preview deterministic metadata/chunks")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout in seconds for live webhook calls")
    parser.add_argument("--auth-token", default=os.getenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", ""), help="optional Synapse webhook auth token")
    parser.add_argument("--source-path", default="", help="optional live RAG source_path filter")
    parser.add_argument("--note-id", default="", help="optional live RAG note_id filter")
    parser.add_argument("--wiki-path", default="", help="optional live RAG wiki_path filter")
    parser.add_argument("--exact-run-id", default="", help="optional live RAG run-id filter")
    parser.add_argument("--tui", action="store_true", help="force the full-screen interactive Synapse Ask terminal interface")
    parser.add_argument("--dry-run", action="store_true", help="use the local no-network preview instead of the live Synapse webhook")
    parser.add_argument("--debug", action="store_true", help="show full HTTP error details including upstream response bodies")
    parser.add_argument("--version", action="version", version=f"Synapse Ask {APP_VERSION}")
    color_group = parser.add_mutually_exclusive_group()
    color_group.add_argument("--color", action="store_true", help="force ANSI color in TUI mode")
    color_group.add_argument("--no-color", action="store_true", help="disable ANSI color in TUI mode")
    output_group = parser.add_mutually_exclusive_group()
    output_group.add_argument("--text", action="store_true", help="one-shot mode: print only the answer text")
    output_group.add_argument("--json", action="store_true", help="one-shot mode: print a nested compatibility {'json': ...} object")
    output_group.add_argument("--raw-json", action="store_true", help="one-shot mode: print the raw response object")
    output_group.add_argument("--output", choices=("text", "json", "raw-json"), help="one-shot output format")
    return parser


def main(argv: list[str] | None = None) -> int:
    # Auto-load .env so SYNAPSE_ASK_WEBHOOK_URL and SYNAPSE_WEBHOOK_AUTH_TOKEN
    # defaults work without manual export. Skip under pytest to keep tests clean.
    if "PYTEST_CURRENT_TEST" not in os.environ:
        load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    # Default to the TUI even when a question is provided. Scripts must opt into
    # machine output so a pasted command does not surprise someone with JSON.
    # Dry-run is also opt-in now; missing webhook config should be obvious.
    script_mode_requested = bool(args.text or args.json or args.raw_json or args.output)
    color_preference = True if args.color else False if args.no_color else None
    if args.tui or not script_mode_requested:
        return run_tui(
            args.webhook_url,
            args.note,
            args.timeout,
            args.auth_token,
            use_color=color_preference,
            initial_question=args.question,
            source_path=args.source_path,
            note_id=args.note_id,
            wiki_path=args.wiki_path,
            exact_run_id=args.exact_run_id,
            dry_run_enabled=args.dry_run,
            debug=args.debug,
        )

    if not args.question:
        parser.error("one-shot script output requires a question; use the TUI without --text/--json/--raw-json/--output")

    question = args.question
    if args.output:
        output_format = args.output
    elif args.json:
        output_format = "json"
    elif args.raw_json:
        output_format = "raw-json"
    else:
        output_format = "text"
    try:
        # One-shot mode shares ask_question with the TUI so live/default/dry-run
        # behavior cannot drift between automation and the interactive app.
        output = ask_question(
            question,
            args.webhook_url,
            args.note,
            args.timeout,
            args.auth_token,
            args.source_path,
            args.note_id,
            args.wiki_path,
            args.exact_run_id,
            args.dry_run,
            debug=args.debug,
        )
        exit_code = 0
    except Exception as exc:
        output = {"mode": "error", "answer": f"Request failed: {exc}", "sources": []}
        exit_code = 1
    print(format_one_shot_output(output, output_format, require_sources=bool(args.webhook_url and not args.dry_run)))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
