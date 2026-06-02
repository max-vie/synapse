import argparse
import json

from scripts.benchmark import ollama_models


class FakeResponse:
    def __init__(self, body: str):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def test_rag_benchmark_uses_synapse_webhook_auth_token(monkeypatch, tmp_path):
    seen_headers = []

    monkeypatch.setattr(
        ollama_models,
        "load_env_safely",
        lambda: {"SYNAPSE_ASK_WEBHOOK_URL": "http://ask", "SYNAPSE_WEBHOOK_AUTH_TOKEN": "tok-secret"},
    )
    monkeypatch.setattr(
        ollama_models,
        "load_questions",
        lambda: {
            "questions": [
                {
                    "id": "q1",
                    "question": "What is proven?",
                    "required_facts": ["answer"],
                    "forbidden_facts": [],
                    "expected_sources": [],
                    "required_source_count": 0,
                }
            ]
        },
    )

    def fake_urlopen(req, timeout):
        seen_headers.append(dict(req.header_items()))
        return FakeResponse(json.dumps({"answer": "answer", "sources": []}))

    monkeypatch.setattr(ollama_models.request, "urlopen", fake_urlopen)

    code = ollama_models.cmd_rag(argparse.Namespace(output_dir=str(tmp_path)))

    assert code == 0
    lowered = {key.lower(): value for key, value in seen_headers[0].items()}
    assert lowered["x-synapse-token"] == "tok-secret"


def test_extract_workload_requires_sources_when_question_requires_sources(monkeypatch):
    monkeypatch.setattr(
        ollama_models,
        "ollama_generate",
        lambda *args, **kwargs: {"ok": True, "response": "The marker is ORCHID-17A.", "latency_s": 0.01},
    )
    question = {
        "id": "source-required",
        "question": "What is the marker?",
        "required_facts": ["ORCHID-17A"],
        "forbidden_facts": [],
        "expected_sources": ["scripts/benchmark/fixtures/notes/newer-evidence-report.md"],
        "required_source_count": 1,
    }

    result = ollama_models.run_extract_workload(
        {"name": "fake", "timeout_seconds": 1},
        {"user_template": "{context}\n{question}", "system": "", "options": {}},
        [question],
        "SOURCE: scripts/benchmark/fixtures/notes/newer-evidence-report.md\nORCHID-17A",
        argparse.Namespace(timeout_scale=1.0),
    )

    assert result["passed"] is False
    assert result["questions"][0]["score"]["source_errors"]


def test_suite_benchmark_run_records_hardware_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(ollama_models, "now_id", lambda: "20260101T000000Z")
    monkeypatch.setattr(ollama_models, "hardware_info", lambda: {"cpu_count": 8, "platform": "test"})

    path = ollama_models.write_run("suite", ["bench", "suite"], {"models": []}, tmp_path)
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["hardware"] == {"cpu_count": 8, "platform": "test"}


def test_ollama_redact_hides_172_private_networks_in_errors():
    private_ip = "172." + "20.5.9"

    text = ollama_models.redact(f"HTTP 500 from http://{private_ip}:11434/api/generate")

    assert private_ip not in text
    assert "172.16.x.x" in text
