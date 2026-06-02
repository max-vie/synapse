"""Explicit no-network dry-run support for Synapse Ask."""

from __future__ import annotations

from pathlib import Path

from .config import ROOT
from .notes import DEMO_VAULT

from synapse.metadata import build_metadata, chunk_text, normalize_markdown_note_path


def _normalize_md_extension(path_str: str) -> str:
    # The metadata validator requires .md (lowercase).  Repo-local files like
    # ARCHITECTURE.MD or external notes with .MD must be normalized before
    # passing to normalize_markdown_note_path.
    if path_str.lower().endswith(".md") and not path_str.endswith(".md"):
        return path_str[:-3] + ".md"
    return path_str


def local_note_metadata_path(note_path: Path) -> str:
    # Produce a public-safe path that is useful to the reader:
    #   1. Inside the demo vault → path relative to examples/obsidian-vault
    #      (e.g. "Synapse-Demo/example-study-notes.md")
    #   2. Inside the repo → path relative to the project root
    #      (e.g. "docs/architecture.md")
    #   3. Outside both → basename only, no absolute path leakage
    #      (e.g. "my-note.md")
    resolved = note_path.resolve()
    try:
        rel = str(resolved.relative_to(DEMO_VAULT))
        return normalize_markdown_note_path(_normalize_md_extension(rel))
    except ValueError:
        pass
    try:
        rel = str(resolved.relative_to(ROOT))
        return normalize_markdown_note_path(_normalize_md_extension(rel))
    except ValueError:
        pass
    # Basename fallback: normalize the extension to .md so the validator accepts it.
    name = _normalize_md_extension(note_path.name)
    return normalize_markdown_note_path(name)


def dry_run(question: str, note_path: Path | None) -> dict[str, object]:
    result: dict[str, object] = {
        "mode": "dry-run",
        "question": question,
        "answer": "Dry run only: configure SYNAPSE_ASK_WEBHOOK_URL to query the live Synapse RAG service.",
        "sources": [],
    }
    if note_path:
        content = note_path.read_text(encoding="utf-8")
        metadata = build_metadata(local_note_metadata_path(note_path), content)
        chunks = chunk_text(content, metadata.note_id)
        result["sample_index_preview"] = {
            "metadata": metadata.to_dict(),
            "chunk_count": len(chunks),
            "first_chunk_id": chunks[0].chunk_id if chunks else None,
        }
    return result