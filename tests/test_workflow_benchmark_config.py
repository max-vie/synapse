import importlib.util
import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.benchmark import workflow_top_models


def load_local_e2e_proof_module():
    path = ROOT / "scripts" / "e2e" / "local_e2e_proof.py"
    spec = importlib.util.spec_from_file_location("local_e2e_proof", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_qdrant_setup_module():
    path = ROOT / "scripts" / "e2e" / "create_qdrant_collection.py"
    spec = importlib.util.spec_from_file_location("create_qdrant_collection", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_compose_uses_container_internal_ollama_url_for_synapse_service():
    compose = yaml.safe_load((ROOT / "docker-compose.e2e.yml").read_text(encoding="utf-8"))
    service_env = compose["services"]["synapse-service"]["environment"]
    assert "n8n" not in compose["services"]
    assert service_env["OLLAMA_INTERNAL_BASE_URL"] == "${OLLAMA_INTERNAL_BASE_URL:-http://ollama:11434}"
    assert service_env["OLLAMA_FORMAT_NUM_PREDICT"] == "${OLLAMA_FORMAT_NUM_PREDICT:-768}"
    assert service_env["OLLAMA_ANSWER_NUM_PREDICT"] == "${OLLAMA_ANSWER_NUM_PREDICT:-256}"
    assert "OLLAMA_HOST_BASE_URL" not in service_env
    assert "OLLAMA_BASE_URL" not in service_env


def test_e2e_setup_script_generates_local_ollama_defaults():
    script = (ROOT / "scripts" / "e2e" / "setup.sh").read_text(encoding="utf-8")
    assert "OLLAMA_INTERNAL_BASE_URL=http://ollama:11434" in script
    assert "OLLAMA_HOST_BASE_URL=http://127.0.0.1:11434" in script
    assert "OLLAMA_BASE_URL=http://ollama:11434" not in script
    assert "OLLAMA_FORMAT_MODEL=tinyllama:latest" in script
    assert "OLLAMA_ANSWER_MODEL=tinyllama:latest" in script
    assert "OLLAMA_EMBED_MODEL=nomic-embed-text" in script
    assert "QDRANT_COLLECTION_BASE=synapse_notes" in script
    assert "QDRANT_COLLECTION=synapse_notes__nomic_embed_text__768" in script
    assert "QDRANT_VECTOR_SIZE=768" not in script
    assert "SYNAPSE_MANAGE_QDRANT_COLLECTION=true" in script
    assert "SYNAPSE_ASK_WEBHOOK_URL=http://localhost:15515/webhook/synapse/ask" in script


def test_env_example_matches_generated_ollama_model_defaults():
    setup_script = (ROOT / "scripts" / "e2e" / "setup.sh").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    for key in (
        "OLLAMA_INTERNAL_BASE_URL",
        "OLLAMA_HOST_BASE_URL",
        "OLLAMA_FORMAT_MODEL",
        "OLLAMA_ANSWER_MODEL",
        "OLLAMA_EMBED_MODEL",
        "QDRANT_COLLECTION_BASE",
        "QDRANT_COLLECTION",
        "SYNAPSE_MANAGE_QDRANT_COLLECTION",
    ):
        generated_value = re.search(rf"^{key}=([^\n]+)$", setup_script, flags=re.MULTILINE)
        example_value = re.search(rf"^{key}=([^\n]+)$", env_example, flags=re.MULTILINE)

        assert generated_value, f"missing generated {key}"
        assert example_value, f"missing .env.example {key}"
        assert example_value.group(1) == generated_value.group(1)

    assert "QDRANT_VECTOR_SIZE=768" not in env_example
    assert "deterministic-extractor" not in env_example
    assert "OLLAMA_BASE_URL=http://ollama:11434" not in env_example


def test_local_e2e_proof_uses_host_ollama_url_not_container_internal_url():
    proof = load_local_e2e_proof_module()
    assert (
        proof.ollama_health_url(
            {
                "OLLAMA_HOST_BASE_URL": "http://127.0.0.1:11434",
                "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
                "OLLAMA_PORT": "9999",
            }
        )
        == "http://127.0.0.1:11434"
    )
    assert proof.ollama_health_url({"OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434", "OLLAMA_PORT": "9999"}) == "http://127.0.0.1:9999"
    assert proof.ollama_health_url({"OLLAMA_PORT": "9999"}) == "http://127.0.0.1:9999"


def test_local_e2e_request_timeout_is_configurable_for_slow_live_models(monkeypatch):
    proof = load_local_e2e_proof_module()
    monkeypatch.setenv("SYNAPSE_E2E_REQUEST_TIMEOUT", "301")
    assert proof.request_timeout_seconds() == 301


def test_health_snapshot_uses_service_specific_readiness(monkeypatch):
    proof = load_local_e2e_proof_module()
    request_calls = []
    probe_calls = []

    def fake_request_json(url, payload=None, headers=None, timeout=None, method=None):
        request_calls.append((url, payload, headers, method))
        if url == "http://qdrant/collections":
            return {"result": {"collections": []}}
        if url == "http://ollama/api/tags":
            return {"models": []}
        if url == "http://wiki/graphql":
            assert headers == {"Authorization": "Bearer replace-wiki-token"}
            return {"data": {"pages": {"list": []}}}
        raise AssertionError(f"unexpected readiness request: {url}")

    def fake_http_probe(url, payload=None, headers=None, timeout=None, method=None):
        probe_calls.append((url, payload, headers, method))
        assert url != "http://synapse/"
        if url == "http://synapse/healthz":
            return "200", "ok"
        assert url == "http://synapse/webhook/synapse/ask"
        assert headers == {"X-Synapse-Token": "example-webhook-token"}
        assert method == "POST"
        return "500", "workflow route exists even when an empty readiness payload errors"

    monkeypatch.setattr(proof, "request_json", fake_request_json)
    monkeypatch.setattr(proof, "http_probe", fake_http_probe)

    health = proof.health_snapshot(
        {"synapse": "http://synapse", "wikijs": "http://wiki", "qdrant": "http://qdrant", "ollama": "http://ollama"},
        webhook_headers={"X-Synapse-Token": "example-webhook-token"},
        gql_headers={"Authorization": "Bearer replace-wiki-token"},
        attempts=1,
    )

    assert {service: result["ready"] for service, result in health.items()} == {
        "synapse": True,
        "wikijs": True,
        "qdrant": True,
        "ollama": True,
    }
    assert probe_calls == [
        ("http://synapse/healthz", None, None, None),
        ("http://synapse/webhook/synapse/ask", {"question": ""}, {"X-Synapse-Token": "example-webhook-token"}, "POST"),
    ]
    assert ("http://wiki/graphql", {"query": "query { pages { list { id path title } } }"}, {"Authorization": "Bearer replace-wiki-token"}, None) in request_calls
    assert ("http://qdrant/collections", None, None, None) in request_calls
    assert ("http://ollama/api/tags", None, None, None) in request_calls


def test_require_health_reports_service_specific_readiness_detail():
    proof = load_local_e2e_proof_module()

    try:
        proof.require_health(
            {
                "synapse": {"ready": True, "endpoint": "http://synapse/webhook/synapse/ask", "status": "400", "detail": "route exists"},
                "wikijs": {"ready": False, "endpoint": "http://wiki/graphql", "status": "401", "detail": "unauthorized"},
            }
        )
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("expected failed readiness check to stop the proof")

    assert "readiness check failed" in message
    assert "wikijs" in message
    assert "http://wiki/graphql" in message
    assert "401" in message
    assert "unauthorized" in message


def test_pull_models_skips_local_chat_model_pulls_when_chat_base_is_remote():
    script = (ROOT / "scripts" / "e2e" / "pull-models.sh").read_text(encoding="utf-8")
    assert "OLLAMA_INTERNAL_BASE_URL" in script
    assert "OLLAMA_CHAT_BASE_URL" in script
    assert "Skipping local chat model pulls" in script


def test_set_env_models_preserves_remote_internal_ollama_base_url(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OLLAMA_INTERNAL_BASE_URL=http://remote-ollama:11434\n"
        "OLLAMA_FORMAT_MODEL=tinyllama:latest\n"
        "OLLAMA_ANSWER_MODEL=tinyllama:latest\n",
        encoding="utf-8",
    )

    workflow_top_models.set_env_models(env_file, "gemma3:27b")

    text = env_file.read_text(encoding="utf-8")
    assert "OLLAMA_INTERNAL_BASE_URL=http://remote-ollama:11434" in text
    assert "OLLAMA_FORMAT_MODEL=gemma3:27b" in text
    assert "OLLAMA_ANSWER_MODEL=gemma3:27b" in text


def test_workflow_runner_skip_pull_does_not_pull_local_compose_model(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env_text = "OLLAMA_INTERNAL_BASE_URL=http://remote-ollama:11434\nOLLAMA_FORMAT_MODEL=tinyllama:latest\nOLLAMA_ANSWER_MODEL=tinyllama:latest\n"
    env_file.write_text(original_env_text, encoding="utf-8")
    calls = []

    def fake_compose(command, *, timeout):
        calls.append(command)
        return {"ok": True, "stdout": "", "stderr": "", "duration_s": 0.01}

    monkeypatch.setattr(workflow_top_models, "ENV_FILE", env_file)
    monkeypatch.setattr(workflow_top_models, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(workflow_top_models, "compose", fake_compose)
    monkeypatch.setattr(workflow_top_models, "run_shell", lambda command, *, timeout: {"ok": True, "stdout": "proof ok", "stderr": "", "duration_s": 0.01})
    monkeypatch.setattr(
        workflow_top_models,
        "parse_evidence",
        lambda model, env, duration_s, ok, output, error: {"model": model, "workflow": {"passed": ok, "score": 100 if ok else 0}},
    )
    args = argparse.Namespace(skip_pull=True, delete_after=False, pull_timeout=1, workflow_timeout=1)

    workflow_top_models.run_workflow_for_model("gemma3:27b", args, original_env_text, set())

    assert not any("ollama pull" in call for call in calls)
    assert any("up -d --force-recreate synapse-service" in call for call in calls)


def test_ospf_live_suite_spec_answers_user_question_with_safe_source():
    proof = load_local_e2e_proof_module()

    suite = proof.build_ospf_suite("e2e-ospf-20260101T000000Z")
    note = suite["notes"][0]
    checks = {check["id"]: check for check in suite["checks"]}
    absent_check = checks["ospf_absent_refuses"]
    backed_check = checks["ospf_note_backed_answer"]
    combined = json.dumps(suite, sort_keys=True)

    assert suite["suite_id"] == "synapse-live-ospf-v1"
    assert note["path"] == "Synapse-Demo/generated-proof-notes/networking-notes-20260101T000000Z.md"
    assert note["content"].startswith("# Networking Notes\n")
    assert "Dijkstra" in note["content"]
    assert "Shortest Path First" in note["content"]
    assert "SPF" in note["content"]
    assert "If asked" not in note["content"]
    assert absent_check["phase"] == "before_note"
    assert absent_check["question"] == "what algorithm is used in ospf?"
    assert absent_check["source_path"] == note["path"]
    assert absent_check["expectation"]["type"] == "unsupported"
    assert "Dijkstra" in absent_check["expectation"]["forbidden_facts"]
    assert backed_check["phase"] == "after_note"
    assert backed_check["question"] == "what algorithm is used in ospf?"
    assert backed_check["source_path"] == note["path"]
    assert "Dijkstra" in backed_check["expectation"]["required_facts"]
    assert "Shortest Path First" in backed_check["expectation"]["required_facts"]
    assert not re.search(r"192\.168\.\d+\.\d+", combined)
    assert "http://" not in combined
    assert "https://" not in combined


def test_live_proof_notes_use_single_ignored_generated_vault_directory():
    proof = load_local_e2e_proof_module()
    ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")

    assert proof.PROOF_NOTE_DIR == "Synapse-Demo/generated-proof-notes"
    assert "examples/obsidian-vault/Synapse-Demo/generated-proof-notes/" in ignore_text

    ospf_paths = [note["path"] for note in proof.build_ospf_suite("e2e-ospf-20260101T000000Z")["notes"]]
    complex_paths = [note["path"] for note in proof.build_complex_suite("e2e-complex-20260101T000000Z", "abc123")["notes"]]
    simple_path = proof.proof_note_path("e2e-20260101T000000Z.md")

    for note_path in [*ospf_paths, *complex_paths, simple_path]:
        assert note_path.startswith(f"{proof.PROOF_NOTE_DIR}/")


def test_ospf_proof_asks_before_posting_note_then_requires_backed_answer(monkeypatch, tmp_path):
    proof = load_local_e2e_proof_module()
    events = []
    raw_evidence = {}

    monkeypatch.setattr(proof, "EVIDENCE_DIR", tmp_path)
    monkeypatch.setattr(proof, "service_urls", lambda env: {"synapse": "http://synapse", "wikijs": "http://wiki", "qdrant": "http://qdrant", "ollama": "http://ollama"})
    monkeypatch.setattr(proof, "health_snapshot", lambda *args, **kwargs: {"synapse": {"ready": True}, "wikijs": {"ready": True}, "qdrant": {"ready": True}, "ollama": {"ready": True}})
    monkeypatch.setattr(proof, "require_health", lambda health: None)
    monkeypatch.setattr(proof, "ensure_qdrant_collection", lambda *args, **kwargs: None)
    monkeypatch.setattr(proof, "auth_headers", lambda env: {})
    monkeypatch.setattr(proof, "wikijs_headers", lambda env: {})

    def fake_post_and_verify_note(note, **kwargs):
        events.append(("post", note["path"]))
        return {"id": note["id"], "note_path": note["path"], "qdrant_points_for_note": 1}

    def fake_request_json(url, payload=None, headers=None, timeout=None, method=None):
        if url.endswith("/webhook/synapse/ask"):
            events.append(("ask", payload["source_path"]))
            if not any(event[0] == "post" for event in events):
                return {
                    "answer": "I do not have enough indexed note context to answer that reliably.",
                    "insufficient_context": True,
                    "sources": [],
                }
            return {
                "answer": "OSPF uses Dijkstra's Shortest Path First (SPF) algorithm [1].",
                "insufficient_context": False,
                "sources": [{"source_path": payload["source_path"]}],
            }
        return {}

    def fake_write_evidence(raw, env):
        raw_evidence.update(raw)

    monkeypatch.setattr(proof, "post_and_verify_note", fake_post_and_verify_note)
    monkeypatch.setattr(proof, "request_json", fake_request_json)
    monkeypatch.setattr(proof, "write_evidence", fake_write_evidence)

    assert proof.run_ospf_proof({"QDRANT_COLLECTION": "synapse_notes"}) == 0
    assert [event[0] for event in events] == ["ask", "post", "ask"]
    assert raw_evidence["summary"]["checks_passed"] == 2
    assert raw_evidence["summary"]["checks_total"] == 2


def test_local_e2e_wrapper_forwards_suite_arguments():
    script = (ROOT / "scripts" / "e2e" / "local-e2e-proof.sh").read_text(encoding="utf-8")
    assert '"$@"' in script


def test_complex_live_suite_spec_is_sanitized_and_adversarial():
    proof = load_local_e2e_proof_module()

    suite = proof.build_complex_suite("e2e-complex-20260101T000000Z", "abc123")
    checks = {check["id"]: check for check in suite["checks"]}
    notes = {note["id"]: note for note in suite["notes"]}

    assert suite["suite_id"] == "synapse-live-complex-v1"
    assert len(suite["notes"]) == 3
    assert len({note["path"] for note in suite["notes"]}) == 3
    assert all(note.get("format") is False for note in suite["notes"])
    assert {check["id"] for check in suite["checks"]} == {
        "current_codename_live",
        "newer_beats_stale_live",
        "exact_command_live",
        "multi_source_boundary_live",
        "unsupported_public_url_live",
        "unsupported_secret_live",
    }
    combined = json.dumps(suite, sort_keys=True)
    assert "stale" in combined.casefold()
    assert "[REDACTED]" in combined
    assert "unsupported" in combined.casefold()
    assert not re.search(r"192\.168\.\d+\.\d+", combined)
    assert not re.search(r"sk-[A-Za-z0-9_-]{8,}", combined)
    assert checks["newer_beats_stale_live"]["source_path"] == notes["current_evidence"]["path"]
    assert "complex-queue-abc123" not in notes["public_claim_boundary"]["content"]


def test_workflow_runner_can_select_complex_proof_suite(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env_text = "OLLAMA_INTERNAL_BASE_URL=http://remote-ollama:11434\nOLLAMA_FORMAT_MODEL=tinyllama:latest\nOLLAMA_ANSWER_MODEL=tinyllama:latest\n"
    env_file.write_text(original_env_text, encoding="utf-8")
    proof_commands = []

    def fake_compose(command, *, timeout):
        return {"ok": True, "stdout": "", "stderr": "", "duration_s": 0.01}

    def fake_run_shell(command, *, timeout):
        proof_commands.append(command)
        return {"ok": True, "stdout": "proof ok", "stderr": "", "duration_s": 0.01}

    monkeypatch.setattr(workflow_top_models, "ENV_FILE", env_file)
    monkeypatch.setattr(workflow_top_models, "EVIDENCE_DIR", tmp_path / "evidence")
    monkeypatch.setattr(workflow_top_models, "compose", fake_compose)
    monkeypatch.setattr(workflow_top_models, "run_shell", fake_run_shell)
    monkeypatch.setattr(
        workflow_top_models,
        "parse_evidence",
        lambda model, env, duration_s, ok, output, error: {"model": model, "workflow": {"passed": ok, "score": 100 if ok else 0}},
    )
    args = argparse.Namespace(skip_pull=True, delete_after=False, pull_timeout=1, workflow_timeout=1, proof_suite="complex")

    workflow_top_models.run_workflow_for_model("gemma3:27b", args, original_env_text, set())

    assert any("local_e2e_proof.py" in command and "--suite complex" in command for command in proof_commands)


def test_complex_parse_evidence_records_subchecks(monkeypatch, tmp_path):
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "local-e2e-latest.json").write_text(
        json.dumps(
            {
                "verdict": "FAIL",
                "suite_id": "synapse-live-complex-v1",
                "run_id": "e2e-complex-test",
                "summary": {"score": 83.33, "passed": False, "checks_passed": 5, "checks_total": 6, "notes_posted": 3, "indexed_chunks": 4},
                "notes": [{"note_path": "Synapse-Demo/e2e-complex-test-current.md", "qdrant_points_for_note": 1}],
                "checks": [{"id": "unsupported_secret_live", "passed": False, "rag": {"answer": "[REDACTED]"}}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(workflow_top_models, "EVIDENCE_DIR", evidence_dir)

    item = workflow_top_models.parse_evidence("gemma3:27b", {}, 12.345, False, "", "workflow failed")

    assert item["suite_id"] == "synapse-live-complex-v1"
    assert item["workflow"] == {"passed": False, "score": 83.33}
    assert item["checks_passed"] == 5
    assert item["checks_total"] == 6
    assert item["failed_check_ids"] == ["unsupported_secret_live"]
    assert item["notes_posted"] == 3
    assert item["indexed_chunks"] == 4
    assert item["checks"][0]["id"] == "unsupported_secret_live"


def test_complex_rag_scoring_text_excludes_internal_source_urls():
    proof = load_local_e2e_proof_module()

    text = proof.rag_scoring_text(
        {
            "answer": "There is no public URL [1].",
            "insufficient_context": False,
            "sources": [
                {
                    "title": "Boundary",
                    "source_path": "Synapse-Demo/boundary.md",
                    "source_url": "http://wikijs:3000/synapse-demo/boundary",
                }
            ],
        }
    )

    assert "There is no public URL" in text
    assert "Synapse-Demo/boundary.md" in text
    assert "http://wikijs" not in text


def test_local_e2e_redaction_removes_generic_secret_like_values():
    proof = load_local_e2e_proof_module()
    bearer = "Bearer " + "sk-" + "live-" + "hardcoded-" + "secret"
    password = "password is " + "hunter2"
    api_key = "api_key=" + "abc123456789"
    text = f"{bearer} and {password} and {api_key}"

    redacted = proof.redact(text, {})

    assert bearer not in redacted
    assert "hunter2" not in redacted
    assert "abc123456789" not in redacted
    assert "[REDACTED]" in redacted


def test_local_e2e_redaction_removes_local_urls():
    proof = load_local_e2e_proof_module()
    lan_ip = ".".join(["192", "168", "1", "20"])
    qdrant_ip = ".".join(["10", "0", "0", "5"])
    text = f"Wiki source http://{lan_ip}:3000/synapse-demo/page and Qdrant http://{qdrant_ip}:6333/collections; public https://example.com/docs stays."

    redacted = proof.redact(text, {})

    assert "https://example.com/docs" in redacted
    assert "<LOCAL_URL>" in redacted
    assert lan_ip not in redacted
    assert qdrant_ip not in redacted
    assert "3000/synapse-demo" not in redacted
    assert "6333/collections" not in redacted


def test_scroll_note_points_follows_qdrant_pagination(monkeypatch):
    proof = load_local_e2e_proof_module()
    payloads = []

    def fake_request_json(url, payload=None, headers=None, timeout=None, method=None):
        payloads.append(dict(payload or {}))
        if "offset" not in payloads[-1]:
            return {"result": {"points": [{"id": "first", "payload": {"text": "first page"}}], "next_page_offset": "cursor-2"}}
        return {"result": {"points": [{"id": "second", "payload": {"text": "second page"}}]}}

    monkeypatch.setattr(proof, "request_json", fake_request_json)

    points = proof.scroll_note_points("http://qdrant:6333", "synapse_notes", "note-1")

    assert [point["id"] for point in points] == ["first", "second"]
    assert payloads[1]["offset"] == "cursor-2"


def test_live_unsupported_score_honors_insufficient_context_boolean():
    proof = load_local_e2e_proof_module()
    answer_text = proof.rag_scoring_text({"answer": "", "insufficient_context": True, "sources": []})

    score = proof.score_live_answer(answer_text, {"type": "unsupported", "forbidden_facts": ["Dijkstra"]}, require_sources=False)

    assert score["passed"] is True
    assert score["score"] == 100.0


def test_simple_proof_ensures_qdrant_collection_before_count(monkeypatch, tmp_path):
    proof = load_local_e2e_proof_module()
    calls = []

    posted = {}
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    monkeypatch.setattr(proof, "ROOT", tmp_path)
    monkeypatch.setattr(proof, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(proof, "service_urls", lambda env: {"synapse": "http://synapse", "wikijs": "http://wiki", "qdrant": "http://qdrant", "ollama": "http://ollama"})
    monkeypatch.setattr(proof, "health_snapshot", lambda *args, **kwargs: {"synapse": {"ready": True}, "wikijs": {"ready": True}, "qdrant": {"ready": True}, "ollama": {"ready": True}})
    monkeypatch.setattr(proof, "require_health", lambda health: None)
    monkeypatch.setattr(proof, "auth_headers", lambda env: {})
    monkeypatch.setattr(proof, "wikijs_headers", lambda env: {})
    monkeypatch.setattr(proof, "verify_wikijs_page", lambda *args, **kwargs: None)
    monkeypatch.setattr(proof, "verify_wiki_index_match", lambda *args, **kwargs: {"content_hash": "test", "qdrant_hashes": ["test"]})
    monkeypatch.setattr(proof, "scroll_note_points", lambda *args, **kwargs: [{"payload": {"text": posted.get("content", ""), "current_content_hash": "test"}}])
    monkeypatch.setattr(proof, "write_evidence", lambda *args, **kwargs: None)

    def fake_ensure(url, env, collection):
        calls.append(("ensure", collection))

    count_seen = False

    def fake_request_json(url, payload=None, headers=None, timeout=None, method=None):
        nonlocal count_seen
        if url.endswith("/points/count"):
            if not count_seen:
                assert calls and calls[-1][0] == "ensure"
            count_seen = True
            calls.append(("count", url))
            return {"result": {"count": len(calls)}}
        if url.endswith("/webhook/synapse/note"):
            assert payload is not None
            posted["content"] = payload["content"]
            return {"status": "ok", "publisher": "wikijs", "wiki_path": "/synapse", "note_id": "note-1", "indexed_chunks": 1}
        if url.endswith("/webhook/synapse/ask"):
            assert payload is not None
            return {"answer": posted.get("content", ""), "sources": [{"source_path": payload["source_path"]}], "insufficient_context": False}
        return {}

    monkeypatch.setattr(proof, "ensure_qdrant_collection", fake_ensure)
    monkeypatch.setattr(proof, "request_json", fake_request_json)

    assert proof.run_simple_proof({"QDRANT_COLLECTION": "synapse_notes"}) == 0
    assert calls[0] == ("ensure", "synapse_notes")


def test_workflow_runner_deletes_only_configured_evidence_dir(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env_text = "OLLAMA_INTERNAL_BASE_URL=http://remote-ollama:11434\nOLLAMA_FORMAT_MODEL=tinyllama:latest\nOLLAMA_ANSWER_MODEL=tinyllama:latest\n"
    env_file.write_text(original_env_text, encoding="utf-8")
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    stale_evidence = evidence_dir / "local-e2e-latest.json"
    stale_evidence.write_text('{"verdict":"STALE"}', encoding="utf-8")

    monkeypatch.setattr(workflow_top_models, "ENV_FILE", env_file)
    monkeypatch.setattr(workflow_top_models, "EVIDENCE_DIR", evidence_dir)
    monkeypatch.setattr(workflow_top_models, "compose", lambda command, *, timeout: {"ok": True, "stdout": "", "stderr": "", "duration_s": 0.01})
    monkeypatch.setattr(workflow_top_models, "run_shell", lambda command, *, timeout: {"ok": True, "stdout": "proof ok", "stderr": "", "duration_s": 0.01})
    args = argparse.Namespace(skip_pull=True, delete_after=False, pull_timeout=1, workflow_timeout=1, proof_suite="complex")

    workflow_top_models.run_workflow_for_model("gemma3:27b", args, original_env_text, set())

    assert not stale_evidence.exists()


def test_complex_collection_names_are_model_safe():
    assert workflow_top_models.complex_collection_name("qwen2.5-coder:14b", run_id="20260101T000000Z") == "synapse_e2e_complex_20260101T000000Z_qwen2_5_coder_14b"


def test_workflow_runner_isolates_complex_proof_collection(monkeypatch, tmp_path):
    env_file = tmp_path / ".env"
    original_env_text = "OLLAMA_INTERNAL_BASE_URL=http://remote-ollama:11434\nOLLAMA_FORMAT_MODEL=tinyllama:latest\nOLLAMA_ANSWER_MODEL=tinyllama:latest\nQDRANT_COLLECTION=synapse_notes\n"
    env_file.write_text(original_env_text, encoding="utf-8")
    proof_env_texts = []
    compose_commands = []

    monkeypatch.setattr(workflow_top_models, "ENV_FILE", env_file)
    monkeypatch.setattr(workflow_top_models, "EVIDENCE_DIR", tmp_path / "evidence")

    def fake_compose(command, *, timeout):
        compose_commands.append(command)
        return {"ok": True, "stdout": "", "stderr": "", "duration_s": 0.01}

    monkeypatch.setattr(workflow_top_models, "compose", fake_compose)

    def fake_run_shell(command, *, timeout):
        proof_env_texts.append(env_file.read_text(encoding="utf-8"))
        return {"ok": True, "stdout": "proof ok", "stderr": "", "duration_s": 0.01}

    monkeypatch.setattr(workflow_top_models, "run_shell", fake_run_shell)
    monkeypatch.setattr(
        workflow_top_models,
        "parse_evidence",
        lambda model, env, duration_s, ok, output, error: {"model": model, "workflow": {"passed": ok, "score": 100 if ok else 0}},
    )
    args = argparse.Namespace(skip_pull=True, delete_after=False, pull_timeout=1, workflow_timeout=1, proof_suite="complex")

    workflow_top_models.run_workflow_for_model("qwen2.5-coder:14b", args, original_env_text, set())

    assert any(
        "QDRANT_COLLECTION=synapse_e2e_complex_" in text
        and "qwen2_5_coder_14b" in text
        and "SYNAPSE_ANSWER_MODE=extractive" in text
        for text in proof_env_texts
    )
    assert "up -d --force-recreate synapse-service" in compose_commands
    assert compose_commands[-1] == "up -d --force-recreate synapse-service"
    assert env_file.read_text(encoding="utf-8") == original_env_text


def test_complex_proof_creates_isolated_qdrant_collection(monkeypatch):
    proof = load_local_e2e_proof_module()
    calls = []

    def fake_request_json(url, payload=None, headers=None, timeout=None, method=None):
        calls.append((url, payload, method))
        if url == "http://ollama:11434/api/embed":
            return {"embeddings": [[0.1, 0.2, 0.3, 0.4]]}
        if url.endswith("/collections/synapse_e2e_complex_test") and payload is None:
            raise RuntimeError("HTTP 404 from qdrant")
        return {}

    monkeypatch.setattr(proof, "request_json", fake_request_json)

    proof.ensure_qdrant_collection(
        "http://qdrant:6333",
        {"OLLAMA_HOST_BASE_URL": "http://ollama:11434", "OLLAMA_EMBED_MODEL": "custom/embed:model"},
        "synapse_e2e_complex_test",
    )

    assert calls[-2] == (
        "http://qdrant:6333/collections/synapse_e2e_complex_test",
        {
            "vectors": {"size": 4, "distance": "Cosine"},
            "metadata": {"embedding_model": "custom/embed:model", "embedding_dimension": 4},
        },
        "PUT",
    )
    assert calls[-1] == (
        "http://qdrant:6333/collections/synapse_e2e_complex_test",
        {"metadata": {"embedding_model": "custom/embed:model", "embedding_dimension": 4}},
        "PATCH",
    )


def test_qdrant_setup_derives_collection_name_from_embedding_model_and_dimension():
    setup = load_qdrant_setup_module()

    assert setup.model_slug("nomic-embed-text") == "nomic_embed_text"
    assert setup.model_slug("hf.co/acme/embed:latest") == "hf_co_acme_embed_latest"
    assert setup.derived_collection_name("synapse_notes", "nomic-embed-text", 768) == "synapse_notes__nomic_embed_text__768"


def test_qdrant_setup_probes_ollama_embedding_dimension_and_creates_metadata_collection(tmp_path):
    setup = load_qdrant_setup_module()
    calls = []

    def fake_request_json(url, payload=None, method=None):
        calls.append((url, payload, method))
        if url == "http://ollama:11434/api/embed":
            assert payload == {"model": "nomic-embed-text", "input": "synapse vector dimension probe"}
            return {"embeddings": [[0.0, 1.0, 2.0]]}
        if url == "http://qdrant:6333/collections/synapse_notes__nomic_embed_text__3" and payload is None:
            raise RuntimeError("HTTP 404 from qdrant")
        return {}

    env_file = tmp_path / ".env"
    env_file.write_text(
        "OLLAMA_HOST_BASE_URL=http://ollama:11434\n"
        "QDRANT_HOST_BASE_URL=http://qdrant:6333\n"
        "OLLAMA_EMBED_MODEL=nomic-embed-text\n"
        "QDRANT_COLLECTION_BASE=synapse_notes\n"
        "QDRANT_COLLECTION=synapse_notes__nomic_embed_text__768\n",
        encoding="utf-8",
    )
    env = setup.load_dotenv(env_file)

    result = setup.ensure_collection(env, env_file=env_file, request_json=fake_request_json)

    assert result == {"collection": "synapse_notes__nomic_embed_text__3", "embedding_model": "nomic-embed-text", "embedding_dimension": 3}
    assert calls[-2] == (
        "http://qdrant:6333/collections/synapse_notes__nomic_embed_text__3",
        {
            "vectors": {"size": 3, "distance": "Cosine"},
            "metadata": {"embedding_model": "nomic-embed-text", "embedding_dimension": 3},
        },
        "PUT",
    )
    assert calls[-1] == (
        "http://qdrant:6333/collections/synapse_notes__nomic_embed_text__3",
        {"metadata": {"embedding_model": "nomic-embed-text", "embedding_dimension": 3}},
        "PATCH",
    )
    assert "QDRANT_COLLECTION=synapse_notes__nomic_embed_text__3" in env_file.read_text(encoding="utf-8")


def test_qdrant_setup_retries_until_qdrant_is_ready(monkeypatch, tmp_path):
    setup = load_qdrant_setup_module()
    monkeypatch.setattr(setup.time, "sleep", lambda _seconds: None)
    attempts = {"collection_get": 0}

    def fake_request_json(url, payload=None, method=None):
        if url == "http://ollama:11434/api/embed":
            return {"embeddings": [[0.0, 1.0, 2.0]]}
        if url == "http://qdrant:6333/collections/synapse_notes__nomic_embed_text__3" and payload is None:
            attempts["collection_get"] += 1
            if attempts["collection_get"] == 1:
                raise setup.urllib.error.URLError("connection refused")
            raise RuntimeError("HTTP 404 from qdrant")
        return {}

    env_file = tmp_path / ".env"
    env_file.write_text(
        "OLLAMA_HOST_BASE_URL=http://ollama:11434\n"
        "QDRANT_HOST_BASE_URL=http://qdrant:6333\n"
        "OLLAMA_EMBED_MODEL=nomic-embed-text\n"
        "QDRANT_COLLECTION_BASE=synapse_notes\n",
        encoding="utf-8",
    )

    result = setup.ensure_collection(setup.load_dotenv(env_file), env_file=env_file, request_json=fake_request_json)

    assert attempts["collection_get"] == 2
    assert result["collection"] == "synapse_notes__nomic_embed_text__3"


def test_qdrant_setup_validates_existing_collection_metadata(monkeypatch):
    setup = load_qdrant_setup_module()

    def fake_request_json(url, payload=None, method=None):
        if url == "http://ollama:11434/api/embed":
            return {"embedding": [0.0, 1.0, 2.0]}
        return {
            "result": {
                "config": {"params": {"vectors": {"size": 3, "distance": "Cosine"}}},
                "metadata": {"embedding_model": "other-model", "embedding_dimension": 3},
            }
        }

    try:
        setup.ensure_collection(
            {"OLLAMA_HOST_BASE_URL": "http://ollama:11434", "OLLAMA_EMBED_MODEL": "nomic-embed-text", "QDRANT_COLLECTION_BASE": "synapse_notes"},
            request_json=fake_request_json,
        )
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("expected collection metadata mismatch to fail")

    assert "Qdrant collection schema mismatch" in message
    assert "embedding_model=nomic-embed-text" in message
    assert "actual embedding_model=other-model" in message


def test_existing_qdrant_collection_validates_vector_config(monkeypatch):
    proof = load_local_e2e_proof_module()
    calls = []

    def fake_request_json(url, payload=None, headers=None, timeout=None, method=None):
        calls.append((url, payload, method))
        return {
            "result": {
                "config": {"params": {"vectors": {"size": 768, "distance": "Cosine"}}},
                "metadata": {"embedding_model": "nomic-embed-text", "embedding_dimension": 768},
            }
        }

    monkeypatch.setattr(proof, "request_json", fake_request_json)

    proof.ensure_qdrant_collection("http://qdrant:6333", {"QDRANT_VECTOR_SIZE": "768"}, "synapse_notes")

    assert calls == [("http://qdrant:6333/collections/synapse_notes", None, None)]


def test_existing_qdrant_collection_fails_on_schema_mismatch(monkeypatch):
    proof = load_local_e2e_proof_module()

    def fake_request_json(url, payload=None, headers=None, timeout=None, method=None):
        return {"result": {"config": {"params": {"vectors": {"size": 384, "distance": "Dot"}}}}}

    monkeypatch.setattr(proof, "request_json", fake_request_json)

    try:
        proof.ensure_qdrant_collection("http://qdrant:6333", {"QDRANT_VECTOR_SIZE": "768"}, "synapse_notes")
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("expected mismatched Qdrant collection schema to fail")

    assert "Qdrant collection schema mismatch" in message
    assert "expected size=768 distance=Cosine embedding_model=nomic-embed-text" in message
    assert "actual size=384 distance=Dot" in message


def test_qdrant_collection_shell_script_uses_embedding_probe_helper():
    script = (ROOT / "scripts" / "e2e" / "create-qdrant-collection.sh").read_text(encoding="utf-8")

    assert "create_qdrant_collection.py" in script
    # The verification curl uses the Qdrant REST API to confirm the collection
    # after the Python script creates it; this is not a redundant probe.
    assert "QDRANT_VECTOR_SIZE:-768" not in script
    assert "existing_size" not in script


def test_lab_up_starts_services_then_pulls_models_then_creates_collection():
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    lab_up = makefile.split("lab-up:", 1)[1].split("\n\n", 1)[0]

    assert "scripts/e2e/start.sh" in lab_up
    assert "scripts/e2e/create-qdrant-collection.sh" in lab_up
    assert "scripts/e2e/pull-models.sh" in lab_up
    assert "import-n8n-workflows.sh" not in lab_up
