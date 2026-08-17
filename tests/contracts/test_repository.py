"""Executable repository contracts that complement application tests."""

from importlib.metadata import version
from pathlib import Path
import subprocess

import yaml

from scripts.checks import images
from synapse import __version__

ROOT = Path(__file__).resolve().parents[2]


def load_yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def test_package_and_source_versions_match():
    expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert __version__ == expected
    assert version("synapse-local-lab") == expected


def test_local_compose_contract_is_authenticated_private_and_bounded():
    compose = load_yaml("docker-compose.e2e.yml")
    service = compose["services"]["synapse-service"]
    environment = service["environment"]
    assert all(str(mapping).startswith("127.0.0.1:") for item in compose["services"].values() for mapping in item.get("ports", []))
    assert str(environment["SYNAPSE_WEBHOOK_AUTH_TOKEN"]).startswith("${SYNAPSE_WEBHOOK_AUTH_TOKEN:?")
    assert environment["SYNAPSE_AUTH_DISABLED"] == "${SYNAPSE_AUTH_DISABLED:-false}"
    assert environment["SYNAPSE_MAX_CONTENT_BYTES"] == "${SYNAPSE_MAX_CONTENT_BYTES:-262144}"
    assert environment["SYNAPSE_MAX_PARALLEL_EXECUTIONS"] == "${SYNAPSE_MAX_PARALLEL_EXECUTIONS:-2}"
    assert all("container_name" not in item for item in compose["services"].values())


def test_reviewed_image_pins_are_current_in_offline_check():
    report = images.build_report(ROOT / "docker-compose.e2e.yml", offline_fixture=True)
    assert report["outdated"] == []
    assert {item["name"] for item in report["images"]} == {"qdrant", "ollama", "synapse-service", "wikijs", "wikijs-postgres"}


def test_ci_keeps_monthly_security_scan_and_mocked_proof():
    workflow = load_yaml(".github/workflows/ci.yml")
    assert {item["cron"] for item in workflow["on"]["schedule"]} == {"0 9 1 * *"}
    assert {"dependency-security", "mocked-fastapi-qdrant-e2e"}.issubset(workflow["jobs"])
    security_steps = str(workflow["jobs"]["dependency-security"]["steps"])
    assert "scripts/ci/scan-images.sh" in security_steps
    assert "upload-artifact" in security_steps


def test_example_note_supports_the_reviewer_demo():
    content = (ROOT / "examples/obsidian-vault/Synapse-Demo/example-study-notes.md").read_text(encoding="utf-8")
    assert content.startswith("# Example Study Notes\n")
    assert "Dijkstra's Shortest Path First (SPF) algorithm" in content
    assert all(term in content for term in ("IP address", "DNS", "Qdrant"))


def test_make_help_exposes_the_supported_workflow():
    result = subprocess.run(["make", "help"], cwd=ROOT, text=True, capture_output=True, check=True)
    for command in ("make lab-up", "make configure", "make proof", "make check", "make remove"):
        assert command in result.stdout
