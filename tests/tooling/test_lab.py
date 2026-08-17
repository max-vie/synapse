import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from scripts.lab import collection, envfile
from scripts.lab.runtime import Lab, LabError

ROOT = Path(__file__).resolve().parents[2]


class Response:
    def __init__(self, payload: dict, status: int = 200):
        self.payload = payload
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


def test_env_creation_uses_template_and_private_permissions(tmp_path: Path):
    template = tmp_path / ".env.example"
    destination = tmp_path / ".env"
    template.write_text(
        "SYNAPSE_WEBHOOK_AUTH_TOKEN=***_TOKEN # generated\n"
        "WIKIJS_DB_PASSWORD=*** # generated\n"
        "WIKIJS_API_TOKEN=replace-after-wikijs-admin-setup\n",
        encoding="utf-8",
    )

    assert envfile.create_from_template(template, destination) is True
    values = envfile.load(destination)
    assert len(values["SYNAPSE_WEBHOOK_AUTH_TOKEN"]) > 40
    assert len(values["WIKIJS_DB_PASSWORD"]) > 20
    assert values["WIKIJS_API_TOKEN"].startswith("replace-")
    assert destination.stat().st_mode & 0o777 == 0o600


def test_env_creation_does_not_overwrite_without_force(tmp_path: Path):
    template = tmp_path / ".env.example"
    destination = tmp_path / ".env"
    template.write_text("VALUE=new\n", encoding="utf-8")
    destination.write_text("VALUE=existing\n", encoding="utf-8")

    assert envfile.create_from_template(template, destination) is False
    assert destination.read_text(encoding="utf-8") == "VALUE=existing\n"


def test_env_updates_preserve_unrelated_values(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("# comment\nA=1\nB=2\n", encoding="utf-8")
    envfile.write_values(path, {"B": "changed", "C": "3"})
    assert path.read_text(encoding="utf-8") == "# comment\nA=1\nB=changed\nC=3\n"


def test_configure_rejects_placeholder_token(tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("WIKIJS_API_TOKEN=replace-after-wikijs-admin-setup\n", encoding="utf-8")
    with pytest.raises(LabError, match="placeholder"):
        Lab(root=tmp_path, env_path=env_path).configure()


def test_configure_requires_reachable_successful_graphql(monkeypatch, tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("WIKIJS_API_TOKEN=usable-token\nWIKIJS_PORT=3000\n", encoding="utf-8")
    monkeypatch.setattr("scripts.lab.runtime.urllib.request.urlopen", lambda request, timeout: Response({"data": {"pages": {"list": []}}}))
    Lab(root=tmp_path, env_path=env_path).configure()


def test_configure_rejects_graphql_errors(monkeypatch, tmp_path: Path):
    env_path = tmp_path / ".env"
    env_path.write_text("WIKIJS_API_TOKEN=usable-token\n", encoding="utf-8")
    monkeypatch.setattr("scripts.lab.runtime.urllib.request.urlopen", lambda request, timeout: Response({"errors": [{"message": "API disabled"}]}))
    with pytest.raises(LabError, match="GraphQL"):
        Lab(root=tmp_path, env_path=env_path).configure()


def test_up_owns_the_order_of_lifecycle_steps(monkeypatch, tmp_path: Path):
    lab = Lab(root=tmp_path, env_path=tmp_path / ".env")
    events: list[str] = []
    monkeypatch.setattr(lab, "initialize", lambda: events.append("initialize"))
    monkeypatch.setattr(lab, "environment", lambda: {"QDRANT_PORT": "1", "WIKIJS_PORT": "2", "OLLAMA_PORT": "3"})
    monkeypatch.setattr(lab, "compose", lambda *args, **kwargs: events.append("infra"))
    monkeypatch.setattr(lab, "wait_http", lambda name, *_args, **_kwargs: events.append(name))
    monkeypatch.setattr(lab, "pull_models", lambda _values: events.append("models"))
    monkeypatch.setattr(lab, "ensure_collection", lambda _values: events.append("collection"))
    monkeypatch.setattr(lab, "start_service", lambda: events.append("service"))

    lab.up()
    assert events == ["initialize", "infra", "Qdrant", "Wiki.js", "Ollama", "models", "collection", "service"]


def test_remove_requires_confirmation_when_noninteractive(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("scripts.lab.runtime.sys.stdin", SimpleNamespace(isatty=lambda: False))
    with pytest.raises(LabError, match="--yes"):
        Lab(root=tmp_path, env_path=tmp_path / ".env").remove()


def test_qdrant_collection_name_tracks_model_and_dimension():
    assert collection.derived_collection_name("synapse_notes", "nomic-embed-text", 768) == "synapse_notes__nomic_embed_text__768"
    assert collection.derived_collection_name("synapse_notes", "hf.co/acme/embed:latest", 3) == "synapse_notes__hf_co_acme_embed_latest__3"


def test_qdrant_collection_probe_creates_expected_schema(tmp_path: Path):
    calls = []

    def request(url, payload=None, method=None):
        calls.append((url, payload, method))
        if url.endswith("/api/embed"):
            return {"embeddings": [[0.0, 1.0, 2.0]]}
        if payload is None:
            raise RuntimeError("HTTP 404")
        return {}

    env_path = tmp_path / ".env"
    env_path.write_text(
        "OLLAMA_HOST_BASE_URL=http://ollama\nQDRANT_HOST_BASE_URL=http://qdrant\n"
        "OLLAMA_EMBED_MODEL=nomic-embed-text\nQDRANT_COLLECTION_BASE=synapse_notes\n",
        encoding="utf-8",
    )
    values = envfile.load(env_path)
    result = collection.ensure_collection(values, env_file=env_path, request_json=request)
    assert result["collection"] == "synapse_notes__nomic_embed_text__3"
    assert calls[-2][1]["vectors"] == {"size": 3, "distance": "Cosine"}
    assert envfile.load(env_path)["QDRANT_COLLECTION"] == result["collection"]


def test_ci_compose_uses_relocated_mock_and_installed_application():
    compose = yaml.safe_load((ROOT / "docker-compose.ci-e2e.yml").read_text(encoding="utf-8"))
    mock = compose["services"]["mock-ollama"]
    service = compose["services"]["synapse-service"]
    assert mock["working_dir"] == "/app/scripts/proof"
    assert "./scripts/proof:/app/scripts/proof:ro,Z" in mock["volumes"]
    assert service["working_dir"] == "/app"
    assert not service.get("volumes")


def test_mocked_proof_uses_an_isolated_project_and_rebuilds(monkeypatch, tmp_path: Path):
    (tmp_path / ".env.example").write_text(
        "COMPOSE_PROJECT_NAME=synapse-e2e\nSYNAPSE_WEBHOOK_AUTH_TOKEN=***_TOKEN\nWIKIJS_DB_PASSWORD=***\n",
        encoding="utf-8",
    )
    (tmp_path / "docker-compose.ci-e2e.yml").write_text("services: {}\n", encoding="utf-8")
    calls = []

    class FakeLab(Lab):
        def compose(self, *args, **kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        def wait_http(self, *_args, **_kwargs):
            return None

        def ensure_collection(self, *_args, **_kwargs):
            return {}

    monkeypatch.setattr("scripts.lab.runtime.Lab", FakeLab)
    monkeypatch.setattr("scripts.proof.runner.main", lambda _args: 0)
    Lab(root=tmp_path).mocked_proof()
    generated = envfile.load(tmp_path / ".local-artifacts" / "ci-e2e" / ".env")
    assert generated["COMPOSE_PROJECT_NAME"] == "synapse-ci-e2e"
    assert any("--build" in call for call in calls)


def test_make_targets_use_the_single_lab_interface():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    for command in ("up", "configure", "proof", "mocked-proof", "real-proof", "status", "logs", "down", "remove"):
        assert f"scripts.lab {command}" in makefile
