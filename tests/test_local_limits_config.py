from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def local_lab_compose() -> dict:
    return yaml.safe_load((ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8"))


def test_local_compose_has_shorter_timeout_and_resource_limits():
    compose = local_lab_compose()
    assert "n8n" not in compose["services"]
    service_env = compose["services"]["synapse-service"]["environment"]

    assert service_env["SYNAPSE_MAX_CONTENT_BYTES"] == "${SYNAPSE_MAX_CONTENT_BYTES:-262144}"
    assert service_env["SYNAPSE_MAX_CHUNKS_PER_NOTE"] == "${SYNAPSE_MAX_CHUNKS_PER_NOTE:-32}"
    assert service_env["SYNAPSE_MAX_QUESTION_LENGTH"] == "${SYNAPSE_MAX_QUESTION_LENGTH:-1000}"
    assert service_env["SYNAPSE_MAX_PARALLEL_EXECUTIONS"] == "${SYNAPSE_MAX_PARALLEL_EXECUTIONS:-2}"
    assert service_env["SYNAPSE_EMBED_BATCH_SIZE"] == "${SYNAPSE_EMBED_BATCH_SIZE:-16}"
    assert service_env["SYNAPSE_HTTP_TIMEOUT_SECONDS"] == "${SYNAPSE_HTTP_TIMEOUT_SECONDS:-60}"
    assert service_env["SYNAPSE_ANSWER_MODE"] == "${SYNAPSE_ANSWER_MODE:-llm}"


def test_local_compose_uses_project_scoped_service_names_not_fixed_container_names():
    compose = local_lab_compose()

    offenders = {
        service_name: service["container_name"]
        for service_name, service in compose["services"].items()
        if "container_name" in service
    }

    assert offenders == {}


def test_env_example_documents_local_lab_limits():
    text = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "SYNAPSE_MAX_CONTENT_BYTES=262144" in text
    assert "SYNAPSE_MAX_CHUNKS_PER_NOTE=32" in text
    assert "SYNAPSE_MAX_QUESTION_LENGTH=1000" in text
    assert "SYNAPSE_MAX_PARALLEL_EXECUTIONS=2" in text
    assert "SYNAPSE_EMBED_BATCH_SIZE=16" in text
    assert "N8N_EXECUTIONS_TIMEOUT" not in text
