import argparse
import json
from pathlib import Path

import yaml

from scripts.benchmark import ollama_models
from scripts.benchmark.constants import (
    MATRIX_PATH,
    NOTES_DIR,
    QUESTIONS_PATH,
    STANDARD_EXTRACT_QUESTION_IDS,
    STANDARD_FORMAT_NOTE_PATHS,
    STANDARD_SUITE_ID,
)
from scripts.benchmark.ollama_models import standard_suite_spec
from scripts.benchmark.report import comparable_standard_records, display_size, redact, render_markdown, summarize_model_records
from scripts.proof.scoring import (
    detect_forbidden,
    detect_redaction_expansion,
    detect_required,
    detect_secret_invention,
    is_insufficient_answer,
    score_answer,
)

STANDARD_NOTE_PATHS = list(STANDARD_FORMAT_NOTE_PATHS)
STANDARD_QUESTION_IDS = list(STANDARD_EXTRACT_QUESTION_IDS)


def _question_runs(count: int, ids: list[str] | None = None) -> list[dict[str, object]]:
    chosen_ids = ids or STANDARD_QUESTION_IDS[:count]
    return [{"id": qid, "ok": True, "answer": "grounded answer"} for qid in chosen_ids]


def _note_runs(count: int, paths: list[str] | None = None) -> list[dict[str, object]]:
    chosen_paths = paths or STANDARD_NOTE_PATHS[:count]
    return [{"source_path": path, "score": {"passed": True}} for path in chosen_paths]


def _standard_runs(model: str) -> list[dict[str, object]]:
    return [
        {
            "kind": "smoke",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "results": {"models": [{"model": model, "passed": True}]},
        },
        {
            "kind": "format",
            "timestamp_utc": "2026-01-01T00:01:00Z",
            "results": {"models": [{"model": model, "format": {"score": 80, "passed": True}, "notes": _note_runs(2)}]},
        },
        {
            "kind": "extract",
            "timestamp_utc": "2026-01-01T00:02:00Z",
            "results": {"models": [{"model": model, "extract": {"score": 90, "passed": True}, "questions": _question_runs(13)}]},
        },
    ]


def test_comparable_standard_records_require_same_smoke_format_extract_suite():
    runs = [
        {
            "kind": "smoke",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "results": {"models": [{"model": "complete-model", "passed": True}, {"model": "missing-format", "passed": True}]},
        },
        {
            "kind": "format",
            "timestamp_utc": "2026-01-01T00:01:00Z",
            "results": {
                "models": [
                    {"model": "complete-model", "format": {"score": 80, "passed": True}, "notes": _note_runs(2)},
                    {"model": "partial-format", "format": {"score": 100, "passed": True}, "notes": _note_runs(1)},
                ]
            },
        },
        {
            "kind": "extract",
            "timestamp_utc": "2026-01-01T00:02:00Z",
            "results": {
                "models": [
                    {"model": "complete-model", "extract": {"score": 90, "passed": True}, "questions": _question_runs(13)},
                    {"model": "extract-only", "extract": {"score": 99, "passed": True}, "questions": _question_runs(13)},
                    {"model": "partial-format", "extract": {"score": 98, "passed": True}, "questions": _question_runs(13)},
                ]
            },
        },
    ]

    records = comparable_standard_records(runs)

    assert [record["model"] for record in records] == ["complete-model"]
    assert records[0]["format_notes"] == 2
    assert records[0]["extract_questions"] == 13
    assert records[0]["scores"] == {"smoke": 100, "format": 80, "extract": 90}
    assert records[0]["workflow_score"] == 87.0


def test_comparable_standard_records_exclude_public_doc_filtered_models():
    runs = []
    for model in ["gemma3:27b", "qwen3-vl:235b-instruct", "llama3.2-vision:11b", "gemma2:2b", "tinyllama:latest"]:
        runs.extend(_standard_runs(model))

    records = comparable_standard_records(runs)

    assert [record["model"] for record in records] == ["gemma3:27b"]


def test_report_ignores_unranked_probe_shapes_and_tuned_runs():
    runs = [
        {"kind": "gemma4_tuning_probe", "timestamp_utc": "2026-01-01T00:00:00Z", "results": []},
        {
            "kind": "suite_tuned",
            "timestamp_utc": "2026-01-01T00:01:00Z",
            "results": {
                "benchmark_spec": {"suite_id": "synapse-standard-v1-tuned-chat-thinkfalse-v1"},
                "models": [
                    {
                        "model": "tuned-model",
                        "suite": {"score": 100, "passed": True},
                        "smoke": {"passed": True},
                        "format": {"score": 100, "passed": True},
                        "notes": _note_runs(2),
                        "extract": {"score": 100, "passed": True},
                        "questions": _question_runs(13),
                    }
                ],
            },
        },
    ]

    assert comparable_standard_records(runs) == []
    assert summarize_model_records(runs) == {}
    text = render_markdown(runs)
    assert "tuned-model" not in text
    assert "suite_tuned" not in text


def test_report_separates_quality_pick_from_low_resource_generated_default():
    text = render_markdown(_standard_runs("gemma3:27b"))

    assert "## Quality pick" in text
    assert "For higher-quality benchmarked runs" in text
    assert "The generated lab `.env` still defaults to `tinyllama:latest`" in text
    assert "Run `gemma3:27b` by default" not in text


def test_comparable_standard_records_reject_nonstandard_format_extract_suite_ids():
    runs = [
        {
            "kind": "smoke",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "results": {"models": [{"model": "gemma3:27b", "passed": True}]},
        },
        {
            "kind": "format",
            "timestamp_utc": "2026-01-01T00:01:00Z",
            "results": {
                "benchmark_spec": {"suite_id": "synapse-standard-v1-tuned-chat-thinkfalse-v1"},
                "models": [{"model": "gemma3:27b", "format": {"score": 100, "passed": True}, "notes": _note_runs(len(STANDARD_NOTE_PATHS))}],
            },
        },
        {
            "kind": "extract",
            "timestamp_utc": "2026-01-01T00:02:00Z",
            "results": {
                "benchmark_spec": {"suite_id": "synapse-standard-v1-tuned-chat-thinkfalse-v1"},
                "models": [{"model": "gemma3:27b", "extract": {"score": 100, "passed": True}, "questions": _question_runs(len(STANDARD_QUESTION_IDS))}],
            },
        },
    ]

    assert comparable_standard_records(runs) == []


def test_report_does_not_classify_passed_missing_suite_workflow_as_complex():
    runs = [
        *_standard_runs("gemma3:27b"),
        {
            "kind": "workflow",
            "timestamp_utc": "2026-01-01T00:03:00Z",
            "results": {
                "selection": {"proof_suite": "complex"},
                "models": [
                    {
                        "model": "gemma3:27b",
                        "workflow": {"score": 100, "passed": True},
                        "suite_id": "",
                        "run_id": "e2e-old-simple",
                        "fresh_note": "Synapse-Demo/e2e-old-simple.md",
                    }
                ],
            },
        },
    ]

    rec = summarize_model_records(runs)["gemma3:27b"]

    assert rec.get("complex_live_workflow") is None


def test_report_redacts_private_networks_and_secret_values():
    private_ip = "172." + "20.5.9"
    token_key = "to" + "ken"
    password_key = "pass" + "word"
    credential_key = "api" + "_key"
    token_value = "abc" + "123456789"
    password_value = "hunter" + "2"
    api_value = "sk-" + "secret-value"
    bearer_value = "abc" + ".def"
    password_phrase = "password is " + password_value
    text = redact(
        f"http://{private_ip}/hook {token_key}=\"{token_value}\" "
        f"{password_key}: {password_value} {password_phrase} {credential_key}={api_value} Bearer {bearer_value}"
    )

    assert private_ip not in text
    assert token_value not in text
    assert password_value not in text
    assert password_phrase not in text
    assert api_value not in text
    assert bearer_value not in text
    assert "172.16.x.x" in text
    assert "[REDACTED]" in text


def test_display_size_handles_effective_b_and_m_tags():
    assert display_size("gemma4:e4b") == "4B"
    assert display_size("gemma3:270m") == "270M"


def test_comparable_standard_records_reject_mismatched_suite_signature():
    wrong_notes = [
        "scripts/benchmark/fixtures/notes/incident-timeline.md",
        "scripts/benchmark/fixtures/notes/config-and-commands.md",
    ]
    wrong_questions = [*STANDARD_QUESTION_IDS[:-1], "nonstandard_extra_question"]
    runs = [
        {
            "kind": "smoke",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "results": {"models": [{"model": "standard-model", "passed": True}, {"model": "wrong-suite", "passed": True}]},
        },
        {
            "kind": "format",
            "timestamp_utc": "2026-01-01T00:01:00Z",
            "results": {
                "models": [
                    {"model": "standard-model", "format": {"score": 80, "passed": True}, "notes": _note_runs(2)},
                    {"model": "wrong-suite", "format": {"score": 99, "passed": True}, "notes": _note_runs(2, wrong_notes)},
                ]
            },
        },
        {
            "kind": "extract",
            "timestamp_utc": "2026-01-01T00:02:00Z",
            "results": {
                "models": [
                    {"model": "standard-model", "extract": {"score": 80, "passed": True}, "questions": _question_runs(13)},
                    {"model": "wrong-suite", "extract": {"score": 99, "passed": True}, "questions": _question_runs(13, wrong_questions)},
                ]
            },
        },
    ]

    records = comparable_standard_records(runs)

    assert [record["model"] for record in records] == ["standard-model"]


def test_render_omits_extract_only_results_from_public_docs():
    runs = [
        {
            "kind": "smoke",
            "timestamp_utc": "2026-01-01T00:00:00Z",
            "results": {"models": [{"model": "complete-model", "passed": True}]},
        },
        {
            "kind": "format",
            "timestamp_utc": "2026-01-01T00:01:00Z",
            "results": {"models": [{"model": "complete-model", "format": {"score": 80, "passed": True}, "notes": _note_runs(2)}]},
        },
        {
            "kind": "extract",
            "timestamp_utc": "2026-01-01T00:02:00Z",
            "results": {
                "models": [
                    {"model": "complete-model", "extract": {"score": 90, "passed": True}, "questions": _question_runs(13)},
                    {"model": "extract-only", "extract": {"score": 99, "passed": True}, "questions": _question_runs(13)},
                ]
            },
        },
    ]

    text = render_markdown(runs)

    assert "Standard-suite scoreboard" in text
    assert "`complete-model`" in text
    assert "`extract-only`" not in text
    assert "## Legacy / not comparable" not in text


def test_render_includes_live_workflow_proof_section():
    runs = [
        {
            "kind": "workflow",
            "timestamp_utc": "2026-01-01T00:03:00Z",
            "results": {
                "models": [
                    {
                        "model": "complete-model",
                        "workflow": {"score": 100, "passed": True},
                        "run_id": "e2e-test",
                        "fresh_note": "Synapse-Demo/e2e-test.md",
                        "qdrant_points": 1,
                        "duration_s": 12.5,
                    }
                ]
            },
        }
    ]

    text = render_markdown(runs)

    assert "## Fresh-note live proof" in text
    assert "`complete-model`" in text
    assert "PASS" in text
    assert "Synapse-Demo/e2e-test.md" in text


def test_render_includes_complex_live_workflow_proof_section():
    runs = [
        *_standard_runs("gemma3:27b"),
        {
            "kind": "workflow",
            "timestamp_utc": "2026-01-01T00:03:00Z",
            "results": {
                "models": [
                    {
                        "model": "gemma3:27b",
                        "workflow": {"score": 83.33, "passed": False},
                        "suite_id": "synapse-live-complex-v1",
                        "run_id": "e2e-complex-test",
                        "fresh_note": "Synapse-Demo/e2e-complex-test-current.md",
                        "qdrant_points": 3,
                        "duration_s": 44.2,
                        "checks_passed": 5,
                        "checks_total": 6,
                        "failed_check_ids": ["unsupported_secret_live"],
                        "notes_posted": 3,
                        "indexed_chunks": 4,
                    }
                ]
            },
        }
    ]

    text = render_markdown(runs)

    assert "## Complex live proof" in text
    assert "`gemma3:27b`" in text
    assert "synapse-live-complex-v1" in text
    assert "5/6" in text
    assert "Notes posted" in text
    assert "Indexed chunks" in text
    assert "unsupported_secret_live" in text


def test_render_compacts_live_workflow_errors_for_markdown_table():
    runs = [
        *_standard_runs("bad-model"),
        {
            "kind": "workflow",
            "timestamp_utc": "2026-01-01T00:03:00Z",
            "results": {
                "models": [
                    {
                        "model": "bad-model",
                        "workflow": {"score": 0, "passed": False},
                        "run_id": "",
                        "fresh_note": "",
                        "duration_s": 1.2,
                        "error": "Traceback (most recent call last):\nline 1\nRuntimeError: HTTP 500 from http://192.168.x.x:5678/webhook/synapse/note: {\"message\":\"Error in workflow\"}",
                    }
                ]
            },
        }
    ]

    text = render_markdown(runs)
    live_section = text.split("## Complex live proof", maxsplit=1)[0]

    assert "Traceback" not in live_section
    assert "RuntimeError: HTTP 500" in live_section


def test_render_uses_workflow_selection_to_classify_failed_complex_runs():
    runs = [
        *_standard_runs("failed-before-evidence"),
        {
            "kind": "workflow",
            "timestamp_utc": "2026-01-01T00:03:00Z",
            "results": {
                "selection": {"proof_suite": "complex"},
                "models": [
                    {
                        "model": "failed-before-evidence",
                        "workflow": {"score": 0, "passed": False},
                        "duration_s": 12.0,
                        "error": "RuntimeError: HTTP 500",
                    }
                ],
            },
        }
    ]

    text = render_markdown(runs)
    fresh_section = text.split("## Fresh-note live proof", maxsplit=1)[1].split(
        "## Complex live proof", maxsplit=1
    )[0]
    complex_section = text.split("## Complex live proof", maxsplit=1)[1]

    assert "`failed-before-evidence`" not in fresh_section
    assert "`failed-before-evidence`" in complex_section
def test_required_and_forbidden_detection():
    text = "Current codename ORCHID-17A uses synapse_benchmark_notes."
    found, missing = detect_required(text, ["ORCHID-17A", "synapse_benchmark_notes", "missing fact"])
    assert found == ["ORCHID-17A", "synapse_benchmark_notes"]
    assert missing == ["missing fact"]
    assert detect_forbidden(text, ["ORCH1D-17A", "synapse_benchmark_notes"]) == ["synapse_benchmark_notes"]


def test_score_answer_passes_expected_facts():
    result = score_answer(
        "The current codename is ORCHID-17A and the collection is synapse_benchmark_notes.",
        {
            "required_facts": ["ORCHID-17A", "synapse_benchmark_notes"],
            "forbidden_facts": ["ORCH1D-17A", "synapse_notes_old"],
        },
    )
    assert result.passed
    assert result.score == 100


def test_score_answer_fails_forbidden_and_missing():
    result = score_answer(
        "The old codename is ORCH1D-17A.",
        {"required_facts": ["ORCHID-17A"], "forbidden_facts": ["ORCH1D-17A"]},
    )
    assert not result.passed
    assert "ORCHID-17A" in result.required_missing
    assert "ORCH1D-17A" in result.forbidden_found


def test_wrong_source_path_detected_when_required():
    result = score_answer(
        "Answer cites scripts/benchmark/fixtures/notes/stale-plan-distractor.md",
        {
            "required_facts": ["Answer"],
            "forbidden_facts": [],
            "expected_sources": ["scripts/benchmark/fixtures/notes/newer-evidence-report.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )
    assert not result.passed
    assert result.source_errors


def test_source_scoring_requires_valid_inline_citation_number():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [99]", "sources": [{"source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "invalid source citation(s): 99" in result.source_errors


def test_source_scoring_accepts_expected_source_at_second_returned_index():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [2]", "sources": [{"source_path": "Synapse-Demo/distractor.md"}, {"source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert result.passed


def test_source_scoring_fails_when_no_sources_returned_even_if_answer_mentions_path():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF from Synapse-Demo/ospf.md. [1]", "sources": []}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "invalid source citation(s): 1" in result.source_errors


def test_source_scoring_requires_requested_number_of_cited_sources():
    result = score_answer(
        '{"answer": "OSPF and BGP facts are present. [1]", "sources": [{"source_path": "Synapse-Demo/ospf.md"}, {"source_path": "Synapse-Demo/bgp.md"}]}',
        {
            "required_facts": ["OSPF", "BGP"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md", "Synapse-Demo/bgp.md"],
            "required_source_count": 2,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 2 cited source(s), found 1" in result.source_errors


def test_source_scoring_does_not_count_expected_path_mentioned_in_answer_as_returned_source():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF from Synapse-Demo/ospf.md. [1]", "sources": [{"source_path": "Synapse-Demo/distractor.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 1 source(s), found 0" in result.source_errors


def test_source_scoring_requires_exact_source_path_not_substring():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [1]", "sources": [{"source_path": "Synapse-Demo/ospf.md.bak"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 1 source(s), found 0" in result.source_errors


def test_source_scoring_requires_match_in_source_path_not_title_metadata():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [1]", "sources": [{"title": "mentions Synapse-Demo/ospf.md", "source_path": "Synapse-Demo/stale.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 1 source(s), found 0" in result.source_errors


def test_source_scoring_ignores_numeric_brackets_in_source_metadata():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [1]", "sources": [{"title": "OSPF note [99]", "source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert result.passed


def test_source_scoring_rejects_out_of_range_citation_before_final_citation():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [99]. The valid source is cited later. [1]", "sources": [{"source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "invalid source citation(s): 99" in result.source_errors


def test_unsupported_answer_behavior():
    result = score_answer(
        "Insufficient context. The notes do not provide a private lab password.",
        {"type": "unsupported", "required_facts": ["Insufficient context"], "forbidden_facts": ["hunter2", "password is"]},
    )
    assert result.passed
    assert is_insufficient_answer(result.required_found[0])


def test_secret_and_redaction_detection():
    assert detect_secret_invention("The API key is sk-live-1234567890")
    assert detect_secret_invention("password is hunter2")
    assert detect_redaction_expansion("expanded redaction: abc123")


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


MATRIX = MATRIX_PATH
QUESTIONS = QUESTIONS_PATH


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_model_matrix_schema_and_default_safety():
    data = load_yaml(MATRIX)
    models = data["models"]
    assert len(models) == 7
    names = [m["name"] for m in models]
    assert len(names) == len(set(names))
    enabled = {m["name"] for m in models if m.get("enabled_by_default")}
    assert enabled == {"tinyllama:latest", "gemma2:2b"}
    large = [m for m in models if float(m.get("parameters_b") or 0) >= 24]
    assert len(large) == 2
    assert any(float(m["parameters_b"]) == 27 for m in large)
    for model in models:
        for key in ("name", "family", "tier", "roles", "source_url", "timeout_seconds"):
            assert key in model, f"{model.get('name')} missing {key}"
        assert model["source_url"].startswith("https://ollama.com/library/")
        if float(model.get("parameters_b") or 0) >= 24:
            assert not model.get("enabled_by_default"), model["name"]


def test_fixture_notes_exist_and_are_sanitized():
    notes = sorted(NOTES_DIR.glob("*.md"))
    assert len(notes) >= 8
    combined = "\n".join(path.read_text(encoding="utf-8") for path in notes)
    assert "[REDACTED]" in combined
    assert "[TOKEN]" in combined
    assert "```bash" in combined
    assert "```mermaid" in combined
    assert "---" in combined
    assert "not " + "production-ready" in combined
    assert "do not claim" in combined.lower()
    assert "ORCHID-17A" in combined
    assert "ORCH1D-17A" in combined
    # Fixtures may include fake decoy strings, but must not contain obvious real private material.
    assert "BEGIN PRIVATE KEY" not in combined
    assert "ghp_" not in combined


def test_questions_schema_is_rich_enough():
    data = load_yaml(QUESTIONS)
    questions = data["questions"]
    assert len(questions) >= 10
    required_facts = []
    forbidden_facts = []
    for q in questions:
        for key in ("id", "type", "question", "expected_sources", "required_source_count", "required_facts", "forbidden_facts"):
            assert key in q, f"{q.get('id')} missing {key}"
        required_facts.extend(q["required_facts"])
        forbidden_facts.extend(q["forbidden_facts"])
    required_facts.extend(data["format_expectations"]["required_facts"])
    forbidden_facts.extend(data["format_expectations"]["forbidden_facts"])
    assert len(required_facts) >= 15
    assert len(forbidden_facts) >= 20
    assert any(q["type"] == "unsupported" for q in questions)
    assert any("freshness_precedence" in q for q in questions)
    assert any(q.get("source_path") for q in questions)
    assert len(data["exact_preserve_blocks"]) >= 4


def test_standard_suite_is_fixed_efficient_workflow_benchmark():
    questions = load_yaml(QUESTIONS)["questions"]
    spec = standard_suite_spec(questions=questions)
    assert spec["suite_id"] == STANDARD_SUITE_ID
    assert spec["workloads"] == ["smoke", "format", "extract"]
    assert spec["format_note_count"] == 2
    assert spec["format_notes"] == list(STANDARD_FORMAT_NOTE_PATHS)
    assert spec["extract_question_count"] == len(questions)
    assert spec["extract_question_ids"] == list(STANDARD_EXTRACT_QUESTION_IDS)
    assert spec["extract_question_count"] >= 13
    assert spec["same_suite_required"] is True
    assert "formatting" in spec["workflow_checks"]
    assert "grounded extraction" in spec["workflow_checks"]
    assert "safety boundaries" in spec["workflow_checks"]
