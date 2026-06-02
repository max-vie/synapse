"""Shared paths and suite constants for Synapse benchmark tooling."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = ROOT / "scripts" / "benchmark"
DOCS_DIR = ROOT / "docs"
DEFAULT_OUTPUT_DIR = ROOT / ".local-artifacts" / "benchmarks"

MATRIX_PATH = BENCH_DIR / "model_matrix.yml"
PROMPTS_PATH = BENCH_DIR / "prompts.yml"
QUESTIONS_PATH = BENCH_DIR / "fixtures" / "questions.yml"
NOTES_DIR = BENCH_DIR / "fixtures" / "notes"
REQUESTED_FAMILY_PARAMS_PATH = BENCH_DIR / "requested_family_params.yml"

BENCHMARK_README_PATH = DEFAULT_OUTPUT_DIR / "benchmark-report.md"
BENCHMARK_REPORT_PATH = BENCHMARK_README_PATH
FAMILY_COVERAGE_REPORT_PATH = DEFAULT_OUTPUT_DIR / "benchmark-family-coverage.md"
BENCHMARK_METHODOLOGY_PATH = DEFAULT_OUTPUT_DIR / "benchmark-methodology.md"

STANDARD_SUITE_ID = "synapse-standard-v1"
CUSTOM_SUITE_ID = "synapse-custom-v1"
STANDARD_FORMAT_NOTE_PATHS = (
    "scripts/benchmark/fixtures/notes/complex-lab-operations.md",
    "scripts/benchmark/fixtures/notes/config-and-commands.md",
)
STANDARD_EXTRACT_QUESTION_IDS = (
    "direct_codename",
    "current_collection",
    "newer_beats_stale",
    "exact_command",
    "incident_summary",
    "source_bound_color",
    "public_claim_boundaries",
    "mermaid_label",
    "unsupported_api_token",
    "unsupported_password",
    "unsupported_customers",
    "unsupported_public_url",
    "refuse_enterprise_claim",
)
DEFAULT_FORMAT_NOTE_COUNT = len(STANDARD_FORMAT_NOTE_PATHS)
DEFAULT_QUESTION_LIMIT = 0  # 0 means the pinned standard question set.
WORKFLOW_SCORE_WEIGHTS = {"smoke": 0.10, "format": 0.40, "extract": 0.50}

# Public benchmark docs are text-first and recruiter-facing. Keep raw JSON and
# internal matrices exhaustive, but omit these classes from generated docs:
# unavailable/not-tested rows, vision/OCR tracks, and deprecated local baselines.
PUBLIC_DOC_EXCLUDED_MODEL_PREFIXES = (
    "tinyllama:",
    "gemma2:",
    "medgemma",
    "qwen3-vl:",
    "qwen2.5vl:",
    "llama3.2-vision:",
    "granite3.2-vision:",
    "glm-ocr:",
    "deepseek-ocr:",
    "llava:",
    "bakllava:",
    "moondream:",
)


def is_public_benchmark_model(model: str) -> bool:
    """Return True for models that belong in the public text benchmark docs."""
    name = model.strip().lower()
    return bool(name) and not any(name.startswith(prefix) for prefix in PUBLIC_DOC_EXCLUDED_MODEL_PREFIXES)
