"""Deterministic metadata helpers for the Synapse notes pipeline.

The functions in this module are intentionally pure and dependency-free so they
can be tested locally without running Ollama, Wiki.js, or Qdrant.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, asdict
from pathlib import PurePosixPath
from typing import Iterable

SCHEMA_VERSION = "synapse-note-v1"
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 160
MAX_MARKDOWN_NOTE_PATH_LENGTH = 240
MAX_MARKDOWN_NOTE_SEGMENT_LENGTH = 120
_RESERVED_WINDOWS_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
_RESERVED_PATH_CHARS = set('<>:"|?*')


@dataclass(frozen=True)
class NoteMetadata:
    schema_version: str
    source: str
    vault_relative_path: str
    title: str
    slug: str
    note_id: str
    content_hash: str
    wiki_path: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    chunk_index: int
    text: str
    content_hash: str
    start_char: int
    end_char: int

    def to_dict(self) -> dict[str, str | int]:
        return asdict(self)


def normalize_text(text: str) -> str:
    """Normalize line endings and trim trailing whitespace deterministically."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip() + "\n" if text.strip() else ""


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def deterministic_uuid(namespace: str, value: str) -> str:
    """Return a deterministic UUID-looking string from sha256(namespace:value).

    Qdrant point IDs support UUID strings. This avoids random IDs and prevents
    duplicate points when the same note/chunk is indexed repeatedly.
    """
    digest = sha256_hex(f"{namespace}:{value}")
    # Force RFC 4122 version/variant bits in a deterministic UUID-shaped value.
    return (
        f"{digest[0:8]}-{digest[8:12]}-5{digest[13:16]}-"
        f"{format((int(digest[16], 16) & 0x3) | 0x8, 'x')}{digest[17:20]}-"
        f"{digest[20:32]}"
    )


def slugify(value: str, fallback: str = "untitled") -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()
    slug = re.sub(r"-{2,}", "-", slug)
    return slug or fallback


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(char) in {"Cc", "Cf"} for char in value)


def normalize_markdown_note_path(vault_relative_path: str) -> str:
    """Return a safe NFC-normalized relative Markdown note path.

    The path becomes part of note IDs, Wiki.js paths, and source locators, so the
    ingest boundary rejects traversal, ambiguous, and collision-prone names before
    any publishing or indexing work starts.
    """
    # Normalize separators and Unicode before validating so equivalent paths
    # cannot receive different identities or source locators.
    path = unicodedata.normalize("NFC", str(vault_relative_path or "").replace("\\", "/"))
    if not path:
        raise ValueError("note path is required")
    if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
        raise ValueError("note path must be relative")
    if path != path.strip():
        raise ValueError("note path must not contain leading or trailing whitespace")
    if _has_control_characters(path):
        raise ValueError("note path must not contain control characters")
    if len(path) > MAX_MARKDOWN_NOTE_PATH_LENGTH:
        raise ValueError(f"note path too long: max {MAX_MARKDOWN_NOTE_PATH_LENGTH} characters")
    if not path.endswith(".md"):
        raise ValueError("note path must end with .md")

    parts = path.split("/")
    if any(part == "" for part in parts):
        raise ValueError("note path must not contain empty segments")
    for part in parts:
        # These checks protect both the filesystem-facing source path and the
        # Wiki.js/Qdrant identifiers derived from it.
        if part in {".", ".."} or part.startswith("."):
            raise ValueError("note path must not contain dot segments")
        if part != part.strip() or part.endswith("."):
            raise ValueError("note path segments must not have trailing spaces or dots")
        if len(part) > MAX_MARKDOWN_NOTE_SEGMENT_LENGTH:
            raise ValueError(f"note path segment too long: max {MAX_MARKDOWN_NOTE_SEGMENT_LENGTH} characters")
        if any(char in _RESERVED_PATH_CHARS for char in part):
            raise ValueError("note path contains reserved characters")
        reserved_stem = part.split(".", 1)[0].upper()
        if reserved_stem in _RESERVED_WINDOWS_NAMES:
            raise ValueError("note path contains a reserved name")
    return path


def title_from_path(vault_relative_path: str, content: str = "") -> str:
    safe_path = normalize_markdown_note_path(vault_relative_path)
    first_heading = re.search(r"^#\s+(.+?)\s*$", content, flags=re.MULTILINE)
    if first_heading:
        return first_heading.group(1).strip()
    name = PurePosixPath(safe_path).stem
    return name.strip() or "Untitled"


def build_metadata(vault_relative_path: str, content: str, source: str = "obsidian") -> NoteMetadata:
    path = normalize_markdown_note_path(vault_relative_path)
    normalized_content = normalize_text(content)
    title = title_from_path(path, normalized_content)
    slug = slugify(title)
    note_id = deterministic_uuid("note", f"{SCHEMA_VERSION}:{source}:{path.lower()}")
    content_hash = sha256_hex(normalized_content)
    # The title is editable display data. The vault path owns publication
    # identity so renaming a heading updates one page instead of creating two.
    wiki_path = "/" + "/".join(slugify(part) for part in PurePosixPath(path).with_suffix("").parts)
    return NoteMetadata(
        schema_version=SCHEMA_VERSION,
        source=source,
        vault_relative_path=path,
        title=title,
        slug=slug,
        note_id=note_id,
        content_hash=content_hash,
        wiki_path=wiki_path,
    )


def chunk_text(
    content: str,
    note_id: str,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split text into deterministic, overlapping chunks with stable IDs."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be >= 0 and smaller than chunk_size")

    text = normalize_text(content)
    if not text:
        return []

    chunks: list[Chunk] = []
    start = 0
    index = 0
    text_len = len(text)
    while start < text_len:
        hard_end = min(start + chunk_size, text_len)
        end = hard_end
        if hard_end < text_len:
            # Prefer paragraph, sentence, then whitespace boundaries.
            boundary_candidates = [
                text.rfind("\n\n", start, hard_end),
                text.rfind(". ", start, hard_end),
                text.rfind(" ", start, hard_end),
            ]
            boundary = max(boundary_candidates)
            min_reasonable = start + max(200, chunk_size // 2)
            if boundary >= min_reasonable:
                end = boundary + (2 if text[boundary : boundary + 2] == "\n\n" else 1)
        chunk = text[start:end].strip()
        if chunk:
            chunk_hash = sha256_hex(chunk)
            chunk_id = deterministic_uuid("chunk", f"{note_id}:{index}:{chunk_hash}")
            chunks.append(Chunk(chunk_id, index, chunk, chunk_hash, start, end))
            index += 1
        if end >= text_len:
            break
        start = max(0, end - overlap)
    return chunks


def source_url(base_url: str, path: str) -> str:
    if not base_url.strip():
        return ""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def metadata_with_chunks(vault_relative_path: str, content: str) -> dict[str, object]:
    metadata = build_metadata(vault_relative_path, content)
    return {
        "metadata": metadata.to_dict(),
        "chunks": [chunk.to_dict() for chunk in chunk_text(content, metadata.note_id)],
    }


__all__: Iterable[str] = [
    "SCHEMA_VERSION",
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_CHUNK_OVERLAP",
    "NoteMetadata",
    "Chunk",
    "normalize_text",
    "sha256_hex",
    "deterministic_uuid",
    "slugify",
    "normalize_markdown_note_path",
    "title_from_path",
    "build_metadata",
    "chunk_text",
    "source_url",
    "metadata_with_chunks",
]
