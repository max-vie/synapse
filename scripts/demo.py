#!/usr/bin/env python3
"""No-credentials reviewer demo for Synapse.

This demo is intentionally local-only:
- no Docker
- no .env
- no API tokens
- no network calls
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from synapse.metadata import build_metadata, chunk_text  # noqa: E402


def run(args: list[str], *, env: dict[str, str] | None = None, capture: bool = False) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    return subprocess.run(
        args,
        cwd=ROOT,
        env=merged_env,
        text=True,
        capture_output=capture,
        check=True,
    )


def verify_metadata_subset():
    metadata = build_metadata("Demo/My Note.md", "# My Note\n")
    if metadata.schema_version != "synapse-note-v1":
        raise RuntimeError(f"unexpected metadata schema: {metadata.schema_version}")
    chunks = chunk_text("# Demo\n\n" + "alpha beta gamma. " * 80, metadata.note_id)
    if not chunks:
        raise RuntimeError("expected deterministic chunking to produce at least one chunk")
    return metadata, chunks


def dry_run_ask() -> dict[str, Any]:
    note = ROOT / "examples/obsidian-vault/Synapse-Demo/example-study-notes.md"
    result = run(
        [
            sys.executable,
            "Ask/ask.py",
            "--dry-run",
            "--json",
            "--note",
            str(note.relative_to(ROOT)),
            "What algorithm does OSPF use?",
        ],
        env={"SYNAPSE_ASK_WEBHOOK_URL": "", "SYNAPSE_WEBHOOK_AUTH_TOKEN": "", "SYNAPSE_AUTH_DISABLED": "true"},
        capture=True,
    )
    return json.loads(result.stdout)["json"]


def main() -> int:
    print("== Synapse no-credentials reviewer demo ==", flush=True)
    print("Scope: no Docker, no .env, no tokens, no network calls", flush=True)

    metadata, chunks = verify_metadata_subset()
    ask_output = dry_run_ask()
    preview = ask_output["sample_index_preview"]

    print("OK: deterministic metadata and Ask dry-run subset passed.")
    print("\nSynapse demo proof:")
    print("- tests: deterministic stdlib subset passed")
    print(f"- ask_mode: {ask_output['mode']}")
    print(f"- demo_note_title: {preview['metadata']['title']}")
    print(f"- demo_note_id: {preview['metadata']['note_id']}")
    print(f"- demo_content_hash_prefix: {preview['metadata']['content_hash'][:12]}")
    print(f"- demo_chunk_count: {preview['chunk_count']}")
    print(f"- deterministic_metadata_id: {metadata.note_id}")
    print(f"- deterministic_chunk_count: {len(chunks)}")
    print("- external_services: none")
    print("\nNext live proof, when the lab is configured: make proof")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
