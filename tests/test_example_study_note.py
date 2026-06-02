import subprocess
from pathlib import Path

from scripts.e2e import obsidian_vault

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_NOTE = "examples/obsidian-vault/Synapse-Demo/example-study-notes.md"


def tracked_example_notes() -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "--", "examples/obsidian-vault"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return sorted(line for line in completed.stdout.splitlines() if line and (ROOT / line).exists())


def test_tracked_example_vault_has_one_study_note():
    assert tracked_example_notes() == [EXAMPLE_NOTE]


def test_example_study_note_contains_ospf_answer_and_basic_networking_facts():
    content = (ROOT / EXAMPLE_NOTE).read_text(encoding="utf-8")

    assert content.startswith("# Example Study Notes\n")
    assert "OSPF" in content
    assert "Dijkstra's Shortest Path First (SPF) algorithm" in content
    assert "IP address" in content
    assert "DNS" in content
    assert "Qdrant" in content


def test_demo_writer_defaults_to_example_study_notes_with_ospf_fact():
    assert obsidian_vault.DEFAULT_NOTE == "Synapse-Demo/example-study-notes.md"
    assert obsidian_vault.DEMO_CONTENT.startswith("# Example Study Notes\n")
    assert "Dijkstra's Shortest Path First (SPF) algorithm" in obsidian_vault.DEMO_CONTENT
