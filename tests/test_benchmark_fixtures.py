from pathlib import Path

import yaml

from scripts.benchmark.constants import (
    MATRIX_PATH,
    NOTES_DIR,
    QUESTIONS_PATH,
    REQUESTED_FAMILY_PARAMS_PATH,
    STANDARD_EXTRACT_QUESTION_IDS,
    STANDARD_FORMAT_NOTE_PATHS,
    STANDARD_SUITE_ID,
)
from scripts.benchmark.ollama_models import standard_suite_spec

MATRIX = MATRIX_PATH
REQUESTED_FAMILY_PARAMS = REQUESTED_FAMILY_PARAMS_PATH
QUESTIONS = QUESTIONS_PATH


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_model_matrix_schema_and_default_safety():
    data = load_yaml(MATRIX)
    models = data["models"]
    assert len(models) >= 35
    names = [m["name"] for m in models]
    assert len(names) == len(set(names))
    enabled = {m["name"] for m in models if m.get("enabled_by_default")}
    assert enabled == {"tinyllama:latest", "gemma2:2b"}
    large = [m for m in models if float(m.get("parameters_b") or 0) >= 24]
    assert len(large) >= 8
    assert any(m["name"].endswith(":24b") for m in large)
    assert any(float(m["parameters_b"]) == 27 for m in large)
    assert any(float(m["parameters_b"]) == 32 for m in large)
    for model in models:
        for key in ("name", "family", "tier", "roles", "source_url", "timeout_seconds"):
            assert key in model, f"{model.get('name')} missing {key}"
        assert model["source_url"].startswith("https://ollama.com/library/")
        if float(model.get("parameters_b") or 0) >= 24:
            assert not model.get("enabled_by_default"), model["name"]


def test_requested_family_parameter_tags_are_in_matrix():
    matrix_names = {m["name"] for m in load_yaml(MATRIX)["models"]}
    requested = load_yaml(REQUESTED_FAMILY_PARAMS)["families"]
    missing = []
    for family_name, family in requested.items():
        for tag in family["canonical_tags"]:
            if tag not in matrix_names:
                missing.append(f"{family_name}:{tag}")
    assert missing == []


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
