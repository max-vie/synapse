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
    assert environment["SYNAPSE_WEBHOOK_AUTH_TOKEN_FILE"] == "/run/secrets/synapse_webhook_auth_token"
    assert environment["WIKIJS_API_TOKEN_FILE"] == "/run/secrets/wikijs_api_token"
    assert environment["SYNAPSE_AUTH_DISABLED"] == "${SYNAPSE_AUTH_DISABLED:-false}"
    assert environment["SYNAPSE_ANSWER_VALIDATION"] == "${SYNAPSE_ANSWER_VALIDATION:-quote_overlap}"
    assert environment["SYNAPSE_MAX_REQUEST_BYTES"] == "${SYNAPSE_MAX_REQUEST_BYTES:-1048576}"
    assert environment["SYNAPSE_MAX_CONTENT_BYTES"] == "${SYNAPSE_MAX_CONTENT_BYTES:-262144}"
    assert environment["SYNAPSE_MAX_PARALLEL_EXECUTIONS"] == "${SYNAPSE_MAX_PARALLEL_EXECUTIONS:-2}"
    assert environment["SYNAPSE_HTTP_TIMEOUT_SECONDS"] == "${SYNAPSE_HTTP_TIMEOUT_SECONDS:-180}"
    assert "working_dir" not in service
    assert "command" not in service
    assert service["user"] == "${SYNAPSE_CONTAINER_UID:-1000}:${SYNAPSE_CONTAINER_GID:-1000}"
    assert all("container_name" not in item for item in compose["services"].values())
    assert "${SYNAPSE_SECRET_DIR:?set SYNAPSE_SECRET_DIR in .env}:/run/secrets:ro,z" in service["volumes"]
    assert "${SYNAPSE_SECRET_DIR:?set SYNAPSE_SECRET_DIR in .env}:/run/secrets:ro,z" in compose["services"]["wikijs-db"]["volumes"]
    assert "${SYNAPSE_SECRET_DIR:?set SYNAPSE_SECRET_DIR in .env}:/run/secrets:ro,z" in compose["services"]["wikijs"]["volumes"]
    assert compose["services"]["wikijs-db"]["environment"]["POSTGRES_PASSWORD_FILE"] == "/run/secrets/wikijs_db_password"
    assert all("@sha256:" in str(compose["services"][name]["image"]) for name in ("qdrant", "ollama", "wikijs", "wikijs-db"))


def test_runtime_image_is_non_root_and_healthchecked():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "USER synapse" in dockerfile
    assert "HEALTHCHECK" in dockerfile
    assert "@sha256:" in dockerfile
    compose = load_yaml("docker-compose.e2e.yml")
    assert "healthcheck" in compose["services"]["qdrant"]
    assert "healthcheck" in compose["services"]["ollama"]


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
    scanner = (ROOT / "scripts/ci/scan-images.sh").read_text(encoding="utf-8")
    assert "docker save" in scanner
    assert "Building local Synapse image" in scanner
    assert "Skipping local-only image" not in scanner


def test_knowledge_system_note_supports_the_reviewer_demo():
    content = (ROOT / "examples/obsidian-vault/Synapse-Demo/knowledge-system-notes.md").read_text(encoding="utf-8")
    assert content.startswith("# My Knowledge System\n")
    assert "What tools make up my knowledge system" in content
    assert all(term in content for term in ("Markdown", "Ollama", "Qdrant", "Wiki.js", "Ask"))


def test_make_help_exposes_the_supported_workflow():
    result = subprocess.run(["make", "help"], cwd=ROOT, text=True, capture_output=True, check=True)
    for command in ("make lab-up", "make configure", "make proof", "make evaluate", "make check", "make remove"):
        assert command in result.stdout
