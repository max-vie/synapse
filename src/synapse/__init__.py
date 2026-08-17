"""Synapse local helpers."""

from ._version import __version__
from .runtime import SynapseRuntime
from .settings import Settings
from .metadata import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    SCHEMA_VERSION,
    Chunk,
    NoteMetadata,
    build_metadata,
    chunk_text,
    deterministic_uuid,
    metadata_with_chunks,
    normalize_text,
    sha256_hex,
    slugify,
    source_url,
    title_from_path,
)

__all__ = [
    "__version__",
    "Settings",
    "SynapseRuntime",
    "DEFAULT_CHUNK_OVERLAP",
    "DEFAULT_CHUNK_SIZE",
    "SCHEMA_VERSION",
    "Chunk",
    "NoteMetadata",
    "build_metadata",
    "chunk_text",
    "deterministic_uuid",
    "metadata_with_chunks",
    "normalize_text",
    "sha256_hex",
    "slugify",
    "source_url",
    "title_from_path",
]
