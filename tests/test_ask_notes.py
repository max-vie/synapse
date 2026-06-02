"""Tests for Ask note discovery and vault resolution."""

import os
import sys
from pathlib import Path

import pytest

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask.notes import resolve_vault, find_available_notes, format_local_notes, DEMO_VAULT
from synapse_ask.config import ROOT


# -- resolve_vault --


def test_resolve_vault_uses_explicit_argument_when_provided(tmp_path):
    vault = tmp_path / "my-vault"
    vault.mkdir()
    (vault / "note.md").write_text("# Note\n", encoding="utf-8")

    root, label = resolve_vault(vault_path=str(vault))

    assert root == vault
    assert label == "Configured vault"


def test_resolve_vault_labels_missing_explicit_path():
    root, label = resolve_vault(vault_path="/no/such/directory")

    assert label == "Configured vault (path not found)"
    assert root == Path("/no/such/directory")


def test_resolve_vault_uses_env_var_when_set(tmp_path, monkeypatch):
    vault = tmp_path / "env-vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))

    root, label = resolve_vault()

    assert root == vault
    assert label == "Configured vault"


def test_resolve_vault_labels_missing_env_var_path(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "/no/such/directory")

    root, label = resolve_vault()

    assert label == "Configured vault (path not found)"


def test_resolve_vault_args_take_precedence_over_env_var(tmp_path, monkeypatch):
    vault = tmp_path / "arg-vault"
    vault.mkdir()
    env_vault = tmp_path / "env-vault"
    env_vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(env_vault))

    root, label = resolve_vault(vault_path=str(vault))

    assert root == vault
    assert label == "Configured vault"


def test_resolve_vault_falls_back_to_demo_vault_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    root, label = resolve_vault()

    assert root == DEMO_VAULT
    assert label == "Demo vault"


def test_resolve_vault_demo_vault_is_under_examples():
    assert DEMO_VAULT == ROOT / "examples" / "obsidian-vault"


def test_resolve_vault_empty_env_var_falls_back_to_demo(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "")

    root, label = resolve_vault()

    assert root == DEMO_VAULT
    assert label == "Demo vault"


def test_resolve_vault_whitespace_env_var_falls_back_to_demo(monkeypatch):
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", "   ")

    root, label = resolve_vault()

    assert root == DEMO_VAULT
    assert label == "Demo vault"


# -- find_available_notes --


def test_find_available_notes_discovers_md_files_in_configured_vault(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "alpha.md").write_text("# Alpha\n", encoding="utf-8")
    (vault / "sub").mkdir()
    (vault / "sub" / "beta.md").write_text("# Beta\n", encoding="utf-8")
    (vault / "ignored.txt").write_text("not a note", encoding="utf-8")

    notes = find_available_notes(vault)

    names = [n.name for n in notes]
    assert "alpha.md" in names
    assert "beta.md" in names
    assert "ignored.txt" not in names


def test_find_available_notes_filters_by_query(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "ospf-notes.md").write_text("# OSPF\n", encoding="utf-8")
    (vault / "bgp-notes.md").write_text("# BGP\n", encoding="utf-8")
    (vault / "random.md").write_text("# Random\n", encoding="utf-8")

    notes = find_available_notes(vault, query="ospf")

    assert len(notes) == 1
    assert notes[0].name == "ospf-notes.md"


def test_find_available_notes_returns_empty_for_missing_directory(tmp_path):
    missing = tmp_path / "does-not-exist"

    notes = find_available_notes(missing)

    assert notes == []


def test_find_available_notes_uses_demo_vault_by_default(monkeypatch):
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)

    # Demo vault exists and has .md files, so we expect results.
    notes = find_available_notes()

    assert len(notes) > 0
    assert all(n.suffix == ".md" for n in notes)


def test_find_available_notes_respects_limit(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    for i in range(20):
        (vault / f"note-{i:02d}.md").write_text(f"# Note {i}\n", encoding="utf-8")

    notes = find_available_notes(vault, limit=5)

    assert len(notes) == 5


# -- format_local_notes --


def test_format_local_notes_labels_configured_vault(tmp_path):
    vault = tmp_path / "configured"
    vault.mkdir()
    note = vault / "study.md"
    note.write_text("# Study\n", encoding="utf-8")

    notes = find_available_notes(vault)
    output = format_local_notes(notes, "Configured vault", vault)

    assert output.startswith("Configured vault:")
    assert "study.md" in output


def test_format_local_notes_labels_demo_vault():
    notes = find_available_notes(DEMO_VAULT, limit=3)

    output = format_local_notes(notes, "Demo vault", DEMO_VAULT)

    assert output.startswith("Demo vault:")
    assert ".md" in output


def test_format_local_notes_shows_relative_paths(tmp_path):
    vault = tmp_path / "vault"
    sub = vault / "sub"
    sub.mkdir(parents=True)
    (sub / "deep.md").write_text("# Deep\n", encoding="utf-8")

    notes = find_available_notes(vault)
    output = format_local_notes(notes, "Configured vault", vault)

    # Should show "sub/deep.md", not an absolute path.
    assert "sub/deep.md" in output
    assert str(vault) not in output


def test_format_local_notes_empty_list():
    output = format_local_notes([], "Configured vault", Path("/tmp"))

    assert output == "Configured vault: no Markdown notes found."


def test_format_local_notes_empty_list_demo_label():
    output = format_local_notes([], "Demo vault", DEMO_VAULT)

    assert output == "Demo vault: no Markdown notes found."


def test_format_local_notes_never_exposes_absolute_paths(tmp_path):
    vault = tmp_path / "secret-vault"
    vault.mkdir()
    (vault / "private.md").write_text("# Private\n", encoding="utf-8")

    notes = find_available_notes(vault)
    output = format_local_notes(notes, "Configured vault", vault)

    assert str(vault) not in output
    assert "private.md" in output