import pytest

from synapse.metadata import build_metadata, chunk_text, deterministic_uuid, normalize_markdown_note_path, normalize_text, slugify, source_url


def test_slugify_is_stable_and_ascii():
    assert slugify("Synapse: Über Notes!") == "synapse-uber-notes"
    assert slugify("---") == "untitled"


def test_build_metadata_is_deterministic():
    content = "# My Note\n\nBody text.\n"
    first = build_metadata("Demo/My Note.md", content)
    second = build_metadata("Demo/My Note.md", content.replace("\r\n", "\n"))
    assert first == second
    assert first.schema_version == "synapse-note-v1"
    assert first.slug == "my-note"
    assert first.wiki_path == "/demo/my-note"


def test_content_hash_changes_but_note_id_does_not():
    one = build_metadata("Demo/My Note.md", "# My Note\nOne")
    two = build_metadata("Demo/My Note.md", "# My Note\nTwo")
    assert one.note_id == two.note_id
    assert one.content_hash != two.content_hash


def test_markdown_note_path_validator_normalizes_safe_relative_paths():
    assert normalize_markdown_note_path("Cafe\u0301 Notes\\Run Book.md") == "Café Notes/Run Book.md"
    metadata = build_metadata("Cafe\u0301 Notes\\Run Book.md", "# Run Book\n")
    assert metadata.vault_relative_path == "Café Notes/Run Book.md"
    assert metadata.wiki_path == "/cafe-notes/run-book"


@pytest.mark.parametrize(
    "path",
    [
        "/absolute.md",
        "C:/absolute.md",
        "Synapse-Demo/../secret.md",
        "Synapse-Demo/./note.md",
        "Synapse-Demo//note.md",
        "Synapse-Demo/note.txt",
        "Synapse-Demo/note.md.bak",
        "Synapse-Demo/CON.md",
        "Synapse-Demo/trailing-dot./note.md",
        "Synapse-Demo/trailing-space /note.md",
        "Synapse-Demo/control\x00.md",
        "Synapse-Demo/bidi\u202e.md",
        "Synapse-Demo/" + "x" * 121 + ".md",
        "x" * 242 + ".md",
    ],
)
def test_markdown_note_path_validator_rejects_hostile_or_collision_prone_paths(path):
    with pytest.raises(ValueError):
        normalize_markdown_note_path(path)


def test_chunk_ids_are_deterministic_and_uuid_shaped():
    content = "# Note\n\n" + "alpha beta gamma. " * 200
    metadata = build_metadata("Note.md", content)
    chunks_a = chunk_text(content, metadata.note_id, chunk_size=300, overlap=50)
    chunks_b = chunk_text(content, metadata.note_id, chunk_size=300, overlap=50)
    assert chunks_a == chunks_b
    assert len(chunks_a) > 1
    assert chunks_a[0].chunk_id.count("-") == 4


def test_normalize_text_removes_trailing_whitespace():
    assert normalize_text("a  \r\nb\t\n") == "a\nb\n"


def test_deterministic_uuid_changes_by_namespace():
    assert deterministic_uuid("note", "same") != deterministic_uuid("chunk", "same")


# ── source_url — no internal URL leak ──────────────────────────────────────


def test_source_url_returns_empty_when_base_url_empty():
    assert source_url("", "/demo/note") == ""


def test_source_url_returns_empty_when_base_url_whitespace():
    assert source_url("  ", "/demo/note") == ""


def test_source_url_builds_url_from_public_base():
    assert source_url("http://localhost:3000", "/demo/note") == "http://localhost:3000/demo/note"


def test_source_url_strips_trailing_slash_from_base():
    assert source_url("http://localhost:3000/", "/demo/note") == "http://localhost:3000/demo/note"
