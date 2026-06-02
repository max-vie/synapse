import ast
import http.server
import os
import socketserver
import subprocess
import threading
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ci_e2e_compose_runs_mocked_fastapi_qdrant_stack_with_mock_ollama_service():
    compose = yaml.safe_load((ROOT / "docker-compose.ci-e2e.yml").read_text(encoding="utf-8"))

    assert set(compose["services"]) == {"qdrant", "synapse-service", "mock-ollama"}
    mock = compose["services"]["mock-ollama"]
    assert mock["image"] == "${MOCK_OLLAMA_IMAGE:-python:3.13-slim}"
    assert mock["working_dir"] == "/app/scripts/e2e"
    assert mock["command"] == "python mock_ollama.py --host '' --port 11435"
    assert "./scripts/e2e:/app/scripts/e2e:ro" in mock.get("volumes", [])
    assert "11435" in [str(port) for port in mock.get("expose", [])]
    assert "ports" not in mock

    service = compose["services"]["synapse-service"]
    service_env = service["environment"]
    assert service_env["OLLAMA_INTERNAL_BASE_URL"] == "http://mock-ollama:11435"
    assert service_env["OLLAMA_CHAT_BASE_URL"] == "http://mock-ollama:11435"
    assert service_env["QDRANT_BASE_URL"] == "http://qdrant:6333"
    assert service_env["QDRANT_COLLECTION"] == "synapse_ci_e2e"
    assert service_env["QDRANT_VECTOR_SIZE"] == "8"
    assert service_env["SYNAPSE_AUTH_DISABLED"] == "false"
    assert service_env["SYNAPSE_MAX_CONTENT_BYTES"] == "32768"
    assert service_env["SYNAPSE_MAX_CHUNKS_PER_NOTE"] == "8"
    assert service_env["SYNAPSE_MAX_QUESTION_LENGTH"] == "500"
    assert service_env["SYNAPSE_MAX_PARALLEL_EXECUTIONS"] == "2"
    assert service_env["SYNAPSE_EMBED_BATCH_SIZE"] == "8"
    assert "extra_hosts" not in service


def test_e2e_lib_allows_ci_to_override_env_and_compose_files():
    lib = (ROOT / "scripts" / "e2e" / "lib.sh").read_text(encoding="utf-8")

    assert "SYNAPSE_ENV_FILE" in lib
    assert "SYNAPSE_COMPOSE_FILE" in lib
    assert "${SYNAPSE_ENV_FILE:-$ROOT/.env}" in lib
    assert "${SYNAPSE_COMPOSE_FILE:-$ROOT/docker-compose.e2e.yml}" in lib


def test_ci_e2e_script_uses_compose_mock_stack_and_no_host_wildcard_bind():
    script = (ROOT / "scripts" / "e2e" / "ci-e2e.sh").read_text(encoding="utf-8")

    assert "docker-compose.ci-e2e.yml" in script
    assert "mock_ollama.py" not in script
    assert "SYNAPSE_MOCK_OLLAMA_BIND" not in script
    assert "MOCK_OLLAMA_BIND" not in script
    assert "0.${ZERO}.0.0" not in script
    assert "host-gateway" not in script
    assert "import-n8n-workflows.sh" not in script
    assert "local_e2e_proof.py" in script
    assert "--suite ci" in script
    assert "SYNAPSE_COMPOSE_FILE" in script
    assert "SYNAPSE_ENV_FILE" in script
    assert "Synapse API" in script


def test_local_e2e_proof_has_ci_suite_for_index_and_ask_path():
    proof = (ROOT / "scripts" / "e2e" / "local_e2e_proof.py").read_text(encoding="utf-8")

    assert 'choices=("simple", "complex", "ospf", "ci")' in proof or 'choices=("simple", "complex", "ospf", "ci", "real")' in proof
    assert "def run_ci_proof" in proof
    assert "def verify_wiki_index_match" in proof
    assert "verify_wiki_index_match" in proof.split("def run_simple_proof", 1)[1].split("def ", 1)[0]
    assert "/webhook/synapse/index-note" in proof
    assert "/webhook/synapse/ask" in proof
    assert "/webhook/synapse/note" not in proof.split("def run_ci_proof", 1)[1].split("def ", 1)[0]
    assert "SYNAPSE_ENV_FILE" in proof


def test_real_local_stack_suite_uses_five_notes_and_ten_questions():
    import importlib.util

    module_path = ROOT / "scripts" / "e2e" / "local_e2e_proof.py"
    spec = importlib.util.spec_from_file_location("local_e2e_proof", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    suite = module.build_real_local_stack_suite("real-local-stack-proof-test", "abc123")
    assert suite["suite_id"] == "synapse-real-local-stack-v1"
    assert len(suite["notes"]) >= 5
    assert len(suite["checks"]) >= 10
    assert all((check.get("expectation") or {}).get("expected_sources") for check in suite["checks"])
    for check in suite["checks"]:
        expectation = check.get("expectation") or {}
        unasked_nonce_facts = [
            fact
            for fact in expectation.get("required_facts") or []
            if "abc123" in str(fact) and "marker" not in check["question"].casefold()
        ]
        assert unasked_nonce_facts == []


def test_proof_detects_wiki_index_content_hash_mismatch():
    import importlib.util

    module_path = ROOT / "scripts" / "e2e" / "local_e2e_proof.py"
    spec = importlib.util.spec_from_file_location("local_e2e_proof_mismatch", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def fake_request_json(url, payload=None, headers=None, method="POST"):
        assert payload is not None
        if url.endswith("/graphql") and "query { pages" in payload["query"]:
            return {"data": {"pages": {"list": [{"id": 7, "path": "synapse-demo/note", "title": "Note"}]}}}
        if url.endswith("/graphql") and "query Page" in payload["query"]:
            return {"data": {"pages": {"single": {"content": "synapse_content_hash: wiki-hash\nmarker"}}}}
        raise AssertionError(f"unexpected request {url} {payload}")

    setattr(module, "request_json", fake_request_json)
    points = [{"payload": {"content_hash": "qdrant-hash", "current_content_hash": "qdrant-hash", "text": "marker"}}]

    try:
        module.verify_wiki_index_match(
            "http://wikijs:3000",
            {"Authorization": "Bearer token"},
            "synapse-demo/note",
            "note-id",
            points,
        )
    except SystemExit as error:
        assert "wiki/index mismatch" in str(error)
        assert "note-id" in str(error)
    else:
        raise AssertionError("expected mismatch failure")


def test_mock_ollama_exposes_embed_and_chat_endpoints():
    source = (ROOT / "scripts" / "e2e" / "mock_ollama.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "synapse-ci-proof" in source
    assert "/api/embed" in source
    assert "/api/chat" in source
    assert "/api/tags" in source
    assert "embeddings" in source
    assert any(isinstance(node, ast.FunctionDef) and node.name == "deterministic_vector" for node in ast.walk(tree))


def test_real_local_stack_proof_checks_env_and_suite():
    script = (ROOT / "scripts" / "e2e" / "real-local-stack-proof.sh").read_text(encoding="utf-8")
    assert "setup.sh" not in script
    assert "WIKIJS_API_TOKEN" in script
    assert "--suite real" in script


def test_workflow_and_makefile_naming_avoids_n8n_references():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    real_workflow = (ROOT / ".github" / "workflows" / "real-local-stack-proof.yml").read_text(encoding="utf-8")

    assert "mocked-fastapi-qdrant-e2e:" in makefile
    assert "mocked-n8n-qdrant-e2e" not in makefile
    assert "real-local-stack-proof:" in makefile
    assert "scripts/e2e/ci-e2e.sh" in makefile
    assert "scripts/e2e/real-local-stack-proof.sh" in makefile
    assert "make mocked-fastapi-qdrant-e2e" in workflow
    assert "Mocked FastAPI/Qdrant e2e" in workflow
    assert "n8n" not in workflow.casefold()
    assert "real-local-stack-proof" in real_workflow
    assert "workflow_dispatch" in real_workflow
    assert "runs-on: [self-hosted, synapse-real-stack]" in real_workflow
    assert "clean: false" not in real_workflow
    assert "clean:" not in real_workflow  # default is clean:true, no need to spell it out
    assert "SYNAPSE_ENV_FILE" in real_workflow
    assert "GitHub-hosted" in real_workflow
    assert "schedule:" not in real_workflow


def test_makefile_exposes_lab_up_configure_proof_flow_without_advertising_setup_as_complete_lab():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "lab-up:" in makefile
    assert "configure:" in makefile
    assert "proof: configure" in makefile
    assert "scripts/e2e/configure.sh" in makefile
    assert "make lab-up" in makefile
    assert "make configure" in makefile
    assert "make proof" in makefile
    assert "make setup       Start the local Synapse lab" not in makefile


def test_docs_use_lab_up_configure_proof_instead_of_claiming_make_setup_is_complete_setup():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    setup_doc = (ROOT / "docs" / "SETUP.md").read_text(encoding="utf-8")

    assert "make lab-up" in readme
    assert "make configure" in readme
    assert "make proof" in readme
    assert "make setup" not in readme
    assert "make lab-up" in setup_doc
    assert "make configure" in setup_doc
    assert "make proof" in setup_doc
    assert "Use `make lab-up`, `make configure`, and `make proof`" in setup_doc
    assert "Use `make setup` and `make proof`" not in setup_doc


def test_configure_script_rejects_missing_or_placeholder_wikijs_token(tmp_path):
    script = ROOT / "scripts" / "e2e" / "configure.sh"

    missing_env = os.environ.copy()
    missing_env["SYNAPSE_ENV_FILE"] = str(tmp_path / "missing.env")
    missing = subprocess.run([str(script)], cwd=ROOT, env=missing_env, text=True, capture_output=True)
    assert missing.returncode != 0
    assert "make lab-up" in missing.stderr

    env_file = tmp_path / "placeholder.env"
    env_key = "WIKIJS_API_" + "TOKEN"
    env_file.write_text(f"{env_key}=replace-after-wikijs-admin-setup\n", encoding="utf-8")
    placeholder_env = os.environ.copy()
    placeholder_env["SYNAPSE_ENV_FILE"] = str(env_file)
    placeholder = subprocess.run([str(script)], cwd=ROOT, env=placeholder_env, text=True, capture_output=True)
    assert placeholder.returncode != 0
    assert "WIKIJS_API_TOKEN is still a placeholder" in placeholder.stderr
    assert "http://localhost:3000" in placeholder.stderr


def test_configure_script_accepts_non_placeholder_wikijs_token(tmp_path):
    script = ROOT / "scripts" / "e2e" / "configure.sh"
    env_file = tmp_path / "configured.env"
    env_key = "WIKIJS_API_" + "TOKEN"
    env_file.write_text(f"{env_key}=local-reviewer-value\n", encoding="utf-8")
    env = os.environ.copy()
    env["SYNAPSE_ENV_FILE"] = str(env_file)

    result = subprocess.run([str(script)], cwd=ROOT, env=env, text=True, capture_output=True)

    assert result.returncode == 0
    # Accept either "is configured" (live API) or "is set in .env" (skipped API check)
    assert "WIKIJS_API_TOKEN" in result.stdout and (
        "is configured" in result.stdout or "is set in .env" in result.stdout
    )
    assert "make proof" in result.stdout


def test_configure_script_rejects_disabled_wikijs_api(tmp_path):
    script = ROOT / "scripts" / "e2e" / "configure.sh"

    class DisabledApiHandler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib handler method name.
            body = b'{"data":{},"errors":[{"message":"API is disabled. You must enable it from the Administration Area first.","path":[]}]}'
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *_args):  # noqa: A002 - stdlib handler signature.
            return

    with socketserver.TCPServer(("127.0.0.1", 0), DisabledApiHandler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        env_file = tmp_path / "configured.env"
        env_key = "WIKIJS_API_" + "TOKEN"
        env_file.write_text(
            f"{env_key}=local-reviewer-value\nWIKIJS_PORT={server.server_address[1]}\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["SYNAPSE_ENV_FILE"] = str(env_file)

        result = subprocess.run([str(script)], cwd=ROOT, env=env, text=True, capture_output=True)

        server.shutdown()

    assert result.returncode != 0
    assert "Wiki.js API is disabled" in result.stderr


def test_changing_embed_model_produces_different_qdrant_collection_name():
    """Regression test: changing OLLAMA_EMBED_MODEL must derive a different collection name."""
    import importlib.util

    module_path = ROOT / "scripts" / "e2e" / "create_qdrant_collection.py"
    spec = importlib.util.spec_from_file_location("create_qdrant_collection", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Same embed model → same collection name
    env_a = {"OLLAMA_EMBED_MODEL": "nomic-embed-text", "QDRANT_COLLECTION_BASE": "synapse_notes"}
    name_a = module.derived_collection_name(
        module.collection_base(env_a), env_a["OLLAMA_EMBED_MODEL"], 768
    )

    # Different embed model → different collection name
    env_b = {"OLLAMA_EMBED_MODEL": "mxbai-embed-large", "QDRANT_COLLECTION_BASE": "synapse_notes"}
    name_b = module.derived_collection_name(
        module.collection_base(env_b), env_b["OLLAMA_EMBED_MODEL"], 1024
    )

    assert name_a != name_b, f"Changing OLLAMA_EMBED_MODEL must change collection name: got {name_a} vs {name_b}"
    assert "nomic_embed_text" in name_a
    assert "mxbai_embed_large" in name_b
    assert "__768" in name_a
    assert "__1024" in name_b


def test_lab_up_starts_synapse_after_collection_creation():
    """Regression test: lab-up must start synapse-service AFTER create-qdrant-collection."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    # create-qdrant-collection.sh must appear before start-synapse.sh in lab-up
    lines = makefile.splitlines()
    lab_up_start = None
    collection_line = None
    synapse_line = None

    for i, line in enumerate(lines):
        if "lab-up:" in line and not line.strip().startswith("#"):
            lab_up_start = i
        if lab_up_start and "create-qdrant-collection.sh" in line:
            collection_line = i
        if lab_up_start and "start-synapse.sh" in line:
            synapse_line = i

    assert collection_line is not None, "lab-up must call create-qdrant-collection.sh"
    assert synapse_line is not None, "lab-up must call start-synapse.sh"
    assert collection_line < synapse_line, (
        f"create-qdrant-collection.sh (line {collection_line}) must run before "
        f"start-synapse.sh (line {synapse_line}) so synapse reads the correct QDRANT_COLLECTION"
    )


def test_compose_profiles_separate_infra_from_synapse():
    """Regression test: compose profiles must allow infra-only start without synapse-service."""
    compose = yaml.safe_load((ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8"))

    infra_services = {"qdrant", "ollama", "wikijs", "wikijs-db"}
    for svc in infra_services:
        profiles = compose["services"][svc].get("profiles", [])
        assert "infra" in profiles, f"{svc} must have 'infra' profile"
        assert "full" in profiles, f"{svc} must have 'full' profile"

    synapse_profiles = compose["services"]["synapse-service"].get("profiles", [])
    assert "full" in synapse_profiles, "synapse-service must have 'full' profile"
    assert "infra" not in synapse_profiles, "synapse-service must NOT have 'infra' profile (started separately)"


def test_real_stack_proof_env_lives_outside_checkout():
    """Regression test: the real-stack workflow must not rely on clean:false
    to preserve a .env inside the checkout. SYNAPSE_ENV_FILE must point to a
    private .env outside the worktree so actions/checkout can safely clean it."""
    real_workflow = (ROOT / ".github" / "workflows" / "real-local-stack-proof.yml").read_text(encoding="utf-8")

    # clean:false would preserve stale files from prior runs
    assert "clean: false" not in real_workflow

    # The workflow must use SYNAPSE_ENV_FILE to find .env outside checkout
    assert "SYNAPSE_ENV_FILE" in real_workflow

    # Verify step must check the external file, not ./env
    assert "test -f .env" not in real_workflow
    assert '"$SYNAPSE_ENV_FILE"' in real_workflow
