from scripts.benchmark.constants import STANDARD_EXTRACT_QUESTION_IDS, STANDARD_FORMAT_NOTE_PATHS
from scripts.benchmark.report import comparable_standard_records, display_size, redact, render_markdown, summarize_model_records

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
