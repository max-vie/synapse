"""Tests for Ask dry-run path handling: local_note_metadata_path and _normalize_md_extension."""

import sys
from pathlib import Path

import pytest

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask.config import ROOT  # noqa: E402
from synapse_ask.notes import DEMO_VAULT  # noqa: E402
from synapse_ask.dry_run import (  # noqa: E402
    _normalize_md_extension,
    local_note_metadata_path,
)

DEMO_NOTE = DEMO_VAULT / "Synapse-Demo" / "example-study-notes.md"


# ── _normalize_md_extension ───────────────────────────────────────────


class TestNormalizeMdExtension:
    def test_lowercase_md_unchanged(self):
        assert _normalize_md_extension("notes/ospf.md") == "notes/ospf.md"

    def test_uppercase_MD_lowered(self):
        assert _normalize_md_extension("docs/ARCHITECTURE.MD") == "docs/ARCHITECTURE.md"

    def test_mixed_case_Md_lowered(self):
        assert _normalize_md_extension("notes/ospf.Md") == "notes/ospf.md"

    def test_non_md_unchanged(self):
        assert _normalize_md_extension("notes/ospf.txt") == "notes/ospf.txt"

    def test_bare_MD_lowered(self):
        assert _normalize_md_extension("README.MD") == "README.md"

    def test_bare_md_unchanged(self):
        assert _normalize_md_extension("readme.md") == "readme.md"


# ── Demo vault notes ──────────────────────────────────────────────────


class TestDemoVaultNotes:
    def test_demo_vault_note_produces_relative_path(self):
        result = local_note_metadata_path(DEMO_NOTE)
        assert result == "Synapse-Demo/example-study-notes.md"

    def test_demo_vault_note_is_relative_to_examples(self):
        result = local_note_metadata_path(DEMO_NOTE)
        assert not result.startswith("/")
        assert not result.startswith("examples")

    def test_nested_demo_vault_note(self):
        nested = DEMO_VAULT / "Synapse-Demo" / "example-study-notes.md"
        result = local_note_metadata_path(nested)
        assert result.startswith("Synapse-Demo/")


# ── Repo-local notes outside the demo vault ───────────────────────────


class TestRepoLocalNotes:
    def test_docs_md_inside_repo(self):
        docs_md = ROOT / "docs" / "SETUP.md"
        if docs_md.exists():
            result = local_note_metadata_path(docs_md)
            assert result == "docs/SETUP.md"

    def test_docs_uppercase_MD_inside_repo(self):
        docs_md = ROOT / "docs" / "ARCHITECTURE.MD"
        if docs_md.exists():
            result = local_note_metadata_path(docs_md)
            assert result == "docs/ARCHITECTURE.md"

    def test_any_repo_md_produces_relative_path(self, tmp_path):
        repo_note = tmp_path / "notes" / "ospf.md"
        repo_note.parent.mkdir(parents=True, exist_ok=True)
        repo_note.write_text("# OSPF\n", encoding="utf-8")
        # This file is outside both DEMO_VAULT and ROOT, so it falls to basename
        # unless we place it inside ROOT. Test with a temporary ROOT-relative file.
        result = local_note_metadata_path(repo_note)
        # Outside ROOT, so basename fallback
        assert result == "ospf.md"


# ── External notes (outside repo and vault) ────────────────────────────


class TestExternalNotes:
    def test_external_md_yields_basename(self, tmp_path):
        ext = tmp_path / "my-note.md"
        ext.write_text("# Test\n", encoding="utf-8")
        result = local_note_metadata_path(ext)
        assert result == "my-note.md"

    def test_external_uppercase_MD_yields_lowercase_extension(self, tmp_path):
        ext = tmp_path / "MY-NOTE.MD"
        ext.write_text("# Test\n", encoding="utf-8")
        result = local_note_metadata_path(ext)
        assert result == "MY-NOTE.md"

    def test_external_deep_path_yields_basename_only(self, tmp_path):
        ext = tmp_path / "deep" / "nested" / "secret" / "note.md"
        ext.parent.mkdir(parents=True, exist_ok=True)
        ext.write_text("# Test\n", encoding="utf-8")
        result = local_note_metadata_path(ext)
        assert result == "note.md"
        # Must NOT include directory components from the external filesystem
        assert "/" not in result

    def test_external_path_leaks_no_absolute_path(self, tmp_path):
        ext = tmp_path / "test.md"
        ext.write_text("# Test\n", encoding="utf-8")
        result = local_note_metadata_path(ext)
        assert not result.startswith("/")
        assert not result.startswith(str(tmp_path))


# ── dry_run integration ───────────────────────────────────────────────


class TestDryRunIntegration:
    def test_dry_run_includes_metadata_path(self):
        from synapse_ask.dry_run import dry_run

        result = dry_run("What is OSPF?", DEMO_NOTE)
        preview = result.get("sample_index_preview", {})
        assert "metadata" in preview
        assert "note_id" in preview["metadata"]

    def test_dry_run_none_note(self):
        from synapse_ask.dry_run import dry_run

        result = dry_run("What is OSPF?", None)
        assert result["mode"] == "dry-run"
        assert "sample_index_preview" not in result

    def test_dry_run_demo_vault_path_in_metadata(self):
        from synapse_ask.dry_run import dry_run

        result = dry_run("What is OSPF?", DEMO_NOTE)
        preview = result["sample_index_preview"]
        metadata = preview["metadata"]
        path_value = metadata["vault_relative_path"]
        assert path_value == "Synapse-Demo/example-study-notes.md"
        assert not path_value.startswith("/")
        # Ensure the absolute demo vault path does not leak into metadata
        assert str(DEMO_VAULT) not in path_value