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

BENCHMARK_README_PATH = DEFAULT_OUTPUT_DIR / "benchmark-report.md"
BENCHMARK_REPORT_PATH = BENCHMARK_README_PATH
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

# Keep low-resource baselines out of recommendation prose while preserving
# their recorded results for comparison.
PUBLIC_DOC_EXCLUDED_MODEL_PREFIXES = (
    "tinyllama:",
    "gemma2:",
    "qwen3-vl:",
    "llama3.2-vision:",
)


def is_public_benchmark_model(model: str) -> bool:
    """Return True for models that belong in the public text benchmark docs."""
    name = model.strip().lower()
    return bool(name) and not any(name.startswith(prefix) for prefix in PUBLIC_DOC_EXCLUDED_MODEL_PREFIXES)
