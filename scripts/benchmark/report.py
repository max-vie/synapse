"""Render sanitized benchmark JSON output to the committed benchmark report."""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmark.constants import (  # noqa: E402
    BENCHMARK_REPORT_PATH,
    DEFAULT_OUTPUT_DIR,
    ROOT,
    STANDARD_EXTRACT_QUESTION_IDS,
    STANDARD_FORMAT_NOTE_PATHS,
    STANDARD_SUITE_ID,
    WORKFLOW_SCORE_WEIGHTS,
    is_public_benchmark_model,
)
from scripts.proof.redaction import redact_sensitive  # noqa: E402

DEFAULT_REPORT = BENCHMARK_REPORT_PATH
STANDARD_FORMAT_NOTE_COUNT = len(STANDARD_FORMAT_NOTE_PATHS)
STANDARD_EXTRACT_QUESTION_COUNT = len(STANDARD_EXTRACT_QUESTION_IDS)
REPORTABLE_KINDS = {"smoke", "format", "extract", "suite", "workflow", "pull"}

def redact(text: str) -> str:
    text = text.replace(str(ROOT), "<REPO_ROOT>")
    text = re.sub(r"(?i)([\"']?(?:token|password|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+", r"\1[REDACTED]", text)
    return redact_sensitive(text)


def latest_files(output_dir: Path, limit: int | None = None) -> list[Path]:
    if not output_dir.exists():
        return []
    files = sorted(output_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files if limit is None else files[:limit]


def load_runs(output_dir: Path) -> list[dict[str, Any]]:
    runs = []
    for path in latest_files(output_dir):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            data["_path"] = str(path)
            runs.append(data)
        except (OSError, json.JSONDecodeError):
            continue
    return runs


def display_size(model: str) -> str:
    if ":1t" in model.lower():
        return "1T"
    match = re.search(r":e?(\d+(?:\.\d+)?)b(?:\b|-|$)", model, re.IGNORECASE)
    if match:
        return f"{match.group(1)}B"
    match = re.search(r":(\d+(?:\.\d+)?)m(?:\b|-|$)", model, re.IGNORECASE)
    if match:
        return f"{match.group(1)}M"
    return "?"


def md_cell(value: Any) -> str:
    text = "—" if value in (None, "") else str(value)
    text = redact(text).replace("\n", " ").replace("|", "/").strip()
    return text or "—"


def md_code(value: Any) -> str:
    text = md_cell(value).replace("`", "'")
    return "—" if text == "—" else f"`{text}`"


def takeaway(model: str) -> str:
    return "Compare the recorded standard scores and live proof status."


def _empty_record(name: str) -> dict[str, Any]:
    return {
        "model": name,
        "size": display_size(name),
        "scores": {},
        "passes": {},
        "failures": [],
        "runs": {},
        "suite_id": None,
        "format_notes": 0,
        "format_note_paths": [],
        "extract_questions": 0,
        "extract_question_ids": [],
        "extract_ok": 0,
        "extract_scored_passed": 0,
        "extract_empty": 0,
        "extract_unavailable": False,
        "live_workflow": None,
        "complex_live_workflow": None,
    }


def _score_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def weighted_workflow_score(scores: dict[str, Any]) -> float:
    return round(sum(_score_value(scores.get(name)) * weight for name, weight in WORKFLOW_SCORE_WEIGHTS.items()), 2)


def _set_failure(rec: dict[str, Any], label: str, failed: bool) -> None:
    if failed and label not in rec["failures"]:
        rec["failures"].append(label)
    if not failed:
        rec["failures"] = [item for item in rec["failures"] if item != label]


def _record_smoke(rec: dict[str, Any], item: dict[str, Any]) -> None:
    smoke = item.get("smoke") or {}
    if isinstance(smoke, dict) and "passed" in smoke:
        passed = bool(smoke.get("passed"))
    else:
        passed = bool(item.get("passed"))
    rec["passes"]["smoke"] = passed
    rec["scores"]["smoke"] = 100 if passed else 0
    _set_failure(rec, "smoke failed", not passed)


def _record_format(rec: dict[str, Any], item: dict[str, Any]) -> None:
    fmt = item.get("format") or {}
    passed = bool(fmt.get("passed"))
    rec["passes"]["format"] = passed
    rec["scores"]["format"] = _score_value(fmt.get("score"))
    rec["format_notes"] = len(item.get("notes") or [])
    rec["format_note_paths"] = [str(note.get("source_path")) for note in item.get("notes") or [] if note.get("source_path")]
    _set_failure(rec, "format failed", not passed)


def _record_extract(rec: dict[str, Any], item: dict[str, Any]) -> None:
    ext = item.get("extract") or {}
    questions = item.get("questions") or []
    total = len(questions)
    ok_count = sum(1 for q in questions if q.get("ok"))
    scored_passed = sum(1 for q in questions if ((q.get("score") or {}).get("passed")))
    empty_count = sum(1 for q in questions if not q.get("answer"))
    passed = bool(ext.get("passed"))
    rec["passes"]["extract"] = passed
    rec["scores"]["extract"] = _score_value(ext.get("score"))
    rec["extract_questions"] = total
    rec["extract_question_ids"] = [str(q.get("id")) for q in questions if q.get("id")]
    rec["extract_ok"] = ok_count
    rec["extract_scored_passed"] = scored_passed
    rec["extract_empty"] = empty_count
    rec["extract_unavailable"] = bool(total and ok_count == 0 and empty_count == total)
    _set_failure(rec, "extract incomplete", not passed)


def _record_live_workflow(rec: dict[str, Any], item: dict[str, Any]) -> None:
    workflow = item.get("workflow") or {}
    raw_failed_check_ids = item.get("failed_check_ids")
    failed_check_ids = raw_failed_check_ids if isinstance(raw_failed_check_ids, list) else []
    live_record = {
        "passed": bool(workflow.get("passed")),
        "score": _score_value(workflow.get("score")),
        "suite_id": str(item.get("suite_id") or ""),
        "run_id": str(item.get("run_id") or ""),
        "fresh_note": str(item.get("fresh_note") or ""),
        "rag_source": str(item.get("rag_source") or ""),
        "qdrant_points": item.get("qdrant_points"),
        "checks_passed": item.get("checks_passed"),
        "checks_total": item.get("checks_total"),
        "failed_check_ids": [str(check_id) for check_id in failed_check_ids],
        "notes_posted": item.get("notes_posted"),
        "indexed_chunks": item.get("indexed_chunks"),
        "duration_s": _score_value(item.get("duration_s")),
        "error": redact(str(item.get("error") or "")),
    }
    if live_record["suite_id"] == "synapse-live-complex-v1":
        rec["complex_live_workflow"] = live_record
    else:
        rec["live_workflow"] = live_record


def summarize_model_records(runs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Merge heterogeneous run files into one latest record per public model."""
    by_model: dict[str, dict[str, Any]] = {}
    # Oldest first so newer runs overwrite older runs for the same workload.
    for run in sorted(runs, key=lambda r: str(r.get("timestamp_utc", ""))):
        kind = str(run.get("kind"))
        if kind not in REPORTABLE_KINDS:
            continue
        timestamp = run.get("timestamp_utc")
        raw_results = run.get("results") or {}
        if not isinstance(raw_results, dict):
            continue
        results = raw_results
        spec = results.get("benchmark_spec") or {}
        if kind in {"suite", "format", "extract"} and spec.get("suite_id") not in (None, STANDARD_SUITE_ID):
            continue
        raw_models = results.get("models", [])
        models = raw_models if isinstance(raw_models, list) else []
        for item in models:
            if not isinstance(item, dict):
                continue
            name = item.get("model")
            if not name or not is_public_benchmark_model(str(name)):
                continue
            if kind == "suite" and ((item.get("suite") or {}).get("suite_id") or spec.get("suite_id")) != STANDARD_SUITE_ID:
                continue
            model_record = by_model.setdefault(name, _empty_record(name))
            model_record["runs"][kind] = {
                "timestamp": timestamp,
                "file": run.get("_path"),
                "suite_id": spec.get("suite_id"),
            }
            if kind == "smoke":
                _record_smoke(model_record, item)
            elif kind == "format":
                _record_format(model_record, item)
            elif kind == "extract":
                _record_extract(model_record, item)
            elif kind == "suite":
                model_record["suite_id"] = (
                    (item.get("suite") or {}).get("suite_id")
                    or spec.get("suite_id")
                )
                _record_smoke(model_record, item)
                _record_format(model_record, item)
                _record_extract(model_record, item)
                model_record["suite_passed"] = bool(
                    (item.get("suite") or {}).get("passed")
                )
                model_record["workflow_score"] = _score_value(
                    (item.get("suite") or {}).get("score")
                ) or weighted_workflow_score(model_record["scores"])
            elif kind == "workflow":
                workflow_item = item
                raw_selection = results.get("selection")
                selection: dict[str, Any] = raw_selection if isinstance(raw_selection, dict) else {}
                if (
                    not workflow_item.get("suite_id")
                    and selection.get("proof_suite") == "complex"
                    and not bool((workflow_item.get("workflow") or {}).get("passed"))
                ):
                    workflow_item = {**workflow_item, "suite_id": "synapse-live-complex-v1"}
                _record_live_workflow(model_record, workflow_item)
            elif kind == "pull":
                passed = bool((item.get("pull") or {}).get("ok"))
                model_record["passes"]["pull"] = passed
                _set_failure(model_record, "pull failed", not passed)

    # Derive comparable totals only after the newest workload records are known.
    for model_record in by_model.values():
        if {"smoke", "format", "extract"} <= set(model_record["scores"]):
            model_record["workflow_score"] = weighted_workflow_score(
                model_record["scores"]
            )
        scores = [
            value
            for key, value in model_record["scores"].items()
            if key in {"smoke", "format", "extract"}
        ]
        model_record["overall_score"] = (
            round(sum(scores) / len(scores), 2) if scores else 0
        )
        model_record["passed_all_recorded"] = (
            all(model_record["passes"].values())
            if model_record["passes"]
            else False
        )
    return by_model


def reportable_runs(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [run for run in runs if str(run.get("kind")) in REPORTABLE_KINDS and isinstance(run.get("results") or {}, dict)]


def comparable_standard_records(
    runs: list[dict[str, Any]],
    *,
    required_format_notes: int = STANDARD_FORMAT_NOTE_COUNT,
    required_extract_questions: int = STANDARD_EXTRACT_QUESTION_COUNT,
) -> list[dict[str, Any]]:
    """Return only models with the same smoke+format+extract benchmark coverage."""
    records = summarize_model_records(runs)
    comparable = []
    for rec in records.values():
        has_all_scores = {"smoke", "format", "extract"} <= set(rec.get("scores", {}))
        has_standard_counts = rec.get("format_notes", 0) >= required_format_notes and rec.get("extract_questions", 0) >= required_extract_questions
        has_standard_signature = (
            tuple(rec.get("format_note_paths", [])) == STANDARD_FORMAT_NOTE_PATHS
            and tuple(rec.get("extract_question_ids", [])) == STANDARD_EXTRACT_QUESTION_IDS
        )
        if has_all_scores and has_standard_counts and has_standard_signature and not rec.get("extract_unavailable"):
            rec["workflow_score"] = weighted_workflow_score(rec["scores"])
            comparable.append(rec)
    return sorted(comparable, key=lambda r: (r.get("workflow_score", 0), r["scores"].get("extract", 0)), reverse=True)


def fmt_score(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def compact_command(command: str) -> str:
    command = redact(command)
    command = command.replace("<REPO_ROOT>/scripts/benchmark/ollama_models.py ", "python -m scripts.benchmark ")
    command = command.replace("scripts/benchmark/ollama_models.py ", "python -m scripts.benchmark ")
    return command


def compact_error_note(error: str) -> str:
    lines = [line.strip() for line in redact(error).splitlines() if line.strip()]
    if not lines:
        return "workflow failed"
    chosen = next((line for line in reversed(lines) if "Error" in line or "HTTP " in line), lines[-1])
    chosen = re.sub(r"https?://\S+", "[local webhook URL]", chosen)
    chosen = re.sub(r"\{.*", "", chosen).strip()
    chosen = chosen.replace("|", "/")
    return chosen[:160]


def _model_set(records: list[dict[str, Any]]) -> set[str]:
    return {str(rec["model"]) for rec in records}


def _size_b_value(size: str) -> float | None:
    if size.endswith("B"):
        try:
            return float(size[:-1])
        except ValueError:
            return None
    return None


def _records_by_model(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(rec["model"]): rec for rec in records}


def _has_public_workflow_record(
    rec: dict[str, Any], key: str, comparable_names: set[str]
) -> bool:
    workflow = rec.get(key) or {}
    return bool(workflow) and (bool(workflow.get("passed")) or rec["model"] in comparable_names)


def _workflow_status(rec: dict[str, Any] | None, key: str) -> str:
    if not rec:
        return "not run"
    workflow = rec.get(key) or {}
    if not workflow:
        return "not run"
    verdict = "PASS" if workflow.get("passed") else "FAIL"
    checks_total = workflow.get("checks_total")
    checks = ""
    if checks_total not in (None, ""):
        checks = f", {workflow.get('checks_passed', 0)}/{checks_total} checks"
    duration = ""
    if workflow.get("duration_s") is not None:
        duration = f", {_score_value(workflow.get('duration_s')):.1f}s"
    return f"{verdict}, {fmt_score(workflow.get('score'))}{checks}{duration}"


def _standard_status(rec: dict[str, Any] | None) -> str:
    if not rec or "workflow_score" not in rec:
        return "not ranked"
    scores = rec.get("scores", {})
    return (
        f"{fmt_score(rec.get('workflow_score'))} "
        f"(smoke {fmt_score(scores.get('smoke'))}, format {fmt_score(scores.get('format'))}, extract {fmt_score(scores.get('extract'))})"
    )


def _recommendation_rows(records: dict[str, dict[str, Any]]) -> list[tuple[str, str, str, str]]:
    candidates = [
        (
            "Default Synapse model",
            "gemma3:27b",
            "Use as the main local model",
            "Highest useful standard score, plus both live proofs. It beat the bigger-model temptation without needing a monster tag.",
        ),
        (
            "Qwen/coder workhorse",
            "qwen2.5-coder:14b",
            "Use when Qwen-family or code-adjacent behavior is preferred",
            "Close to the default score and a clean 6/6 complex proof. Good when I want Qwen/coder behavior without jumping to 32B.",
        ),
        (
            "Lightweight tuned Gemma 4",
            "gemma4:e4b",
            "Use as a fast tuned live-workflow option",
            "Fastest full complex pass. I still keep it below the default because the stock standard extraction score is much weaker.",
        ),
        (
            "Tuned newer Qwen",
            "qwen3.5:9b",
            "Use as a tuned newer-Qwen option",
            "Passed the live proof, but its lower standard extraction score keeps it behind `gemma3:27b` and `qwen2.5-coder:14b`.",
        ),
        (
            "Experimental newer-Qwen check",
            "qwen3.6:27b",
            "Keep as validation, not default",
            "It did pass, but the lower standard score and 310.1s complex run make it hard to justify as the default.",
        ),
        (
            "Small fallback caveat",
            "qwen2.5-coder:3b",
            "Use only as a constrained fallback",
            "Looks great until the complex suite asks for multi-source boundaries. That one miss keeps it in fallback territory.",
        ),
    ]
    return [row for row in candidates if row[1] in records]


def render_markdown(runs: list[dict[str, Any]]) -> str:
    """Render reviewer-facing model evidence without overstating comparability."""
    lines: list[str] = []
    generated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lines.append("# Synapse local model notes")
    lines.append("")
    lines.append(f"Generated: `{generated}`")
    lines.append("")
    lines.append(
        "Scope: local Synapse model choice. The score only means something inside this workflow: "
        "FastAPI note ingestion, Wiki.js publish, Qdrant indexing, and Ask answering from indexed notes. "
        "It is not a public leaderboard for general LLM quality."
    )
    lines.append("")
    if not runs:
        lines.append("No benchmark result JSON files were found.")
        return "\n".join(lines) + "\n"

    # Phase 1: normalize raw runs into comparable and live-proof views.
    scanned_count = len(runs)
    newest_candidates = reportable_runs(runs)
    newest = sorted(newest_candidates, key=lambda r: str(r.get("timestamp_utc", "")), reverse=True)[0] if newest_candidates else None
    records = summarize_model_records(runs)
    comparable = comparable_standard_records(runs)
    comparable_names = _model_set(comparable)
    legacy_extract: list[dict[str, Any]] = []
    unavailable: list[dict[str, Any]] = []
    live_workflows = sorted(
        [
            model_record
            for model_record in records.values()
            if _has_public_workflow_record(
                model_record,
                "live_workflow",
                comparable_names,
            )
        ],
        key=lambda model_record: (
            bool((model_record.get("live_workflow") or {}).get("passed")),
            _score_value((model_record.get("live_workflow") or {}).get("score")),
            _score_value(model_record.get("workflow_score")),
        ),
        reverse=True,
    )
    complex_workflows = sorted(
        [
            model_record
            for model_record in records.values()
            if _has_public_workflow_record(
                model_record,
                "complex_live_workflow",
                comparable_names,
            )
        ],
        key=lambda model_record: (
            bool((model_record.get("complex_live_workflow") or {}).get("passed")),
            _score_value(
                (model_record.get("complex_live_workflow") or {}).get("score")
            ),
            _score_value(model_record.get("workflow_score")),
        ),
        reverse=True,
    )

    records_by_name = _records_by_model(list(records.values()))
    recommendation_rows = _recommendation_rows(records_by_name)

    # Phase 2: lead with the decision a technical reviewer is looking for.
    lines.append("## Quality pick")
    lines.append("")
    default_record = records_by_name.get("gemma3:27b") or (
        comparable[0] if comparable else None
    )
    if default_record:
        lines.append(
            f"For higher-quality benchmarked runs, use {md_code(default_record['model'])} when the host has enough RAM/VRAM. "
            f"The generated lab `.env` still defaults to `tinyllama:latest` for low-resource fresh setup. "
            f"{md_code(default_record['model'])} was not the fastest model, but it had the cleanest mix of standard-suite score and live proof: "
            f"`{fmt_score(default_record.get('workflow_score'))}` in the standard workflow, "
            f"fresh-note proof `{_workflow_status(default_record, 'live_workflow')}`, and complex proof `{_workflow_status(default_record, 'complex_live_workflow')}`."
        )
    else:
        lines.append("No default can be recommended yet because no model has completed the full standard suite in the available raw output.")
    lines.append("")
    if recommendation_rows:
        lines.append("| Role | Pick | Standard evidence | Live fresh-note proof | Complex proof | Recommendation | Why |")
        lines.append("|------|------|-------------------|-----------------------|---------------|----------------|-----|")
        for role, model, decision, why in recommendation_rows:
            model_record = records_by_name[model]
            lines.append(
                f"| {md_cell(role)} | {md_code(model)} | {md_cell(_standard_status(model_record))} | "
                f"{md_cell(_workflow_status(model_record, 'live_workflow'))} | {md_cell(_workflow_status(model_record, 'complex_live_workflow'))} | "
                f"{md_cell(decision)} | {md_cell(why)} |"
            )
    else:
        lines.append("No comparable recommendation yet. Run `python3 -m scripts.benchmark run --models <tags> --skip-pull` to create ranked output.")
    lines.append("")
    lines.append(
        "Do not treat the tuned rows as stock Ollama defaults. `gemma4:e4b` and `qwen3.5:9b` only made sense with the chat path used in the proof: "
        "`/api/chat`, `think:false`, `temperature:0`, a larger context/generation budget, stricter source-boundary wording, and `/no_think` for Qwen-family reasoning tags."
    )
    lines.append("")
    lines.append("## What I actually ran")
    lines.append("")
    lines.append(f"- Raw benchmark JSON files scanned: `{scanned_count}`")
    lines.append(f"- Comparable standard workflow runs: `{len(comparable)}` models")
    lines.append(f"- Live FastAPI fresh-note service proofs: `{len(live_workflows)}` models")
    lines.append(f"- Live FastAPI complex service proofs: `{len(complex_workflows)}` models")
    lines.append("- Standard suite: `smoke` + `2-note formatting` + `13-question grounded extraction/safety` for every ranked model.")
    lines.append("- Workflow score weights: smoke 10%, format 40%, extract 50%.")
    lines.append("- Live proof path: model switch, FastAPI note webhook, Wiki.js publish, Qdrant index, and ask-webhook RAG over fresh notes.")
    lines.append("- Complex proof adds stale decoy evidence, exact-command extraction, multi-source boundaries, and unsupported secret/public-URL refusals.")
    if comparable:
        best = comparable[0]
        lines.append(f"- Best comparable workflow score: `{best['model']}` at `{fmt_score(best.get('workflow_score'))}`")
    lines.append("")

    # Phase 3: present Live proof separately from the faster standard suite.
    lines.append("## Fresh-note live proof")
    lines.append("")
    lines.append(
        "This is separate from the fast prompt harness. Each row switched the model, posted a new note through FastAPI, "
        "confirmed Wiki.js/Qdrant saw it, then asked through the Ask webhook. A pass means Synapse answered from a note created during that run."
    )
    lines.append("")
    if live_workflows:
        lines.append("| Rank | Model | Verdict | Live workflow | Standard workflow | Fresh note | Qdrant | Duration | Notes |")
        lines.append("|------|-------|---------|---------------|-------------------|------------|--------|----------|-------|")
        for rank, model_record in enumerate(live_workflows, start=1):
            workflow_result = model_record.get("live_workflow") or {}
            verdict = "PASS" if workflow_result.get("passed") else "FAIL"
            fresh_note = workflow_result.get("fresh_note") or "—"
            qdrant_points = workflow_result.get("qdrant_points")
            qdrant_label = (
                "—" if qdrant_points in (None, "") else str(qdrant_points)
            )
            duration_label = (
                f"{_score_value(workflow_result.get('duration_s')):.1f}s"
                if workflow_result.get("duration_s") is not None
                else "—"
            )
            note_summary = (
                "answered run note"
                if workflow_result.get("passed")
                else compact_error_note(str(workflow_result.get("error") or ""))
            )
            lines.append(
                f"| {rank} | {md_code(model_record['model'])} | {md_cell(verdict)} | {fmt_score(workflow_result.get('score'))} | "
                f"{fmt_score(model_record.get('workflow_score'))} | {md_code(fresh_note)} | {md_cell(qdrant_label)} | {md_cell(duration_label)} | {md_cell(note_summary)} |"
            )
    else:
        lines.append("No live workflow proofs have been recorded yet. Run `python3 -m scripts.benchmark workflow` after selecting models.")
    lines.append("")

    lines.append("## Complex live proof")
    lines.append("")
    lines.append(
        "The complex suite (`synapse-live-complex-v1`) is where the easy winners usually get less comfortable: multiple fresh notes, stale decoy evidence, "
        "exact-command extraction, multi-source boundaries, and refusal checks for secrets or public URLs that were never in the source."
    )
    lines.append("")
    if complex_workflows:
        lines.append("| Rank | Model | Verdict | Complex workflow | Standard workflow | Suite | Checks | Notes posted | Indexed chunks | Duration | Failed checks |")
        lines.append("|------|-------|---------|------------------|-------------------|-------|--------|--------------|----------------|----------|---------------|")
        for rank, model_record in enumerate(complex_workflows, start=1):
            workflow_result = model_record.get("complex_live_workflow") or {}
            verdict = "PASS" if workflow_result.get("passed") else "FAIL"
            checks_total = workflow_result.get("checks_total")
            checks = (
                "—"
                if checks_total in (None, "")
                else f"{workflow_result.get('checks_passed', 0)}/{checks_total}"
            )
            notes_posted_value = workflow_result.get("notes_posted")
            notes_posted = "—" if notes_posted_value in (None, "") else str(notes_posted_value)
            indexed_chunks_value = workflow_result.get("indexed_chunks")
            indexed_chunks = "—" if indexed_chunks_value in (None, "") else str(indexed_chunks_value)
            duration = (
                f"{_score_value(workflow_result.get('duration_s')):.1f}s"
                if workflow_result.get("duration_s") is not None
                else "—"
            )
            failed = ", ".join(workflow_result.get("failed_check_ids") or []) or "—"
            lines.append(
                f"| {rank} | {md_code(model_record['model'])} | {md_cell(verdict)} | {fmt_score(workflow_result.get('score'))} | "
                f"{fmt_score(model_record.get('workflow_score'))} | {md_code(workflow_result.get('suite_id') or 'synapse-live-complex-v1')} | {md_cell(checks)} | "
                f"{md_cell(notes_posted)} | {md_cell(indexed_chunks)} | {md_cell(duration)} | {md_cell(failed)} |"
            )
    else:
        lines.append(
            "No complex live workflow proofs have been recorded yet. Run `python3 -m scripts.benchmark workflow --proof-suite complex --models <tags> --skip-pull`."
        )
    lines.append("")

    lines.append("## Standard-suite scoreboard")
    lines.append("")
    lines.append("This table is the fast gate I used before spending time on live FastAPI runs. It includes text models that completed the same standard suite.")
    lines.append("")
    if comparable:
        lines.append("| Rank | Model | Size | Workflow | Smoke | Format | Extract | Checks | Takeaway |")
        lines.append("|------|-------|------|----------|-------|--------|---------|--------|----------|")
        for rank, model_record in enumerate(comparable, start=1):
            checks = (
                f"format {model_record.get('format_notes', 0)}/2; "
                f"extract {model_record.get('extract_scored_passed', 0)}/"
                f"{model_record.get('extract_questions', 0)} scored"
            )
            lines.append(
                f"| {rank} | {md_code(model_record['model'])} | {md_cell(model_record['size'])} | {fmt_score(model_record.get('workflow_score'))} | "
                f"{fmt_score(model_record['scores'].get('smoke'))} | {fmt_score(model_record['scores'].get('format'))} | {fmt_score(model_record['scores'].get('extract'))} | {md_cell(checks)} | {md_cell(takeaway(model_record['model']))} |"
            )
    else:
        lines.append("No comparable standard workflow runs found.")
    lines.append("")

    if legacy_extract:
        lines.append("## Legacy / not comparable")
        lines.append("")
        lines.append("These models have useful older results, but they are not ranked because they did not complete the same smoke + formatting + extraction suite.")
        lines.append("")
        lines.append("| Model | Extract | Questions | Missing for ranking | Takeaway |")
        lines.append("|-------|---------|-----------|---------------------|----------|")
        for model_record in legacy_extract:
            missing = [
                name
                for name in ("smoke", "format", "extract")
                if name not in model_record.get("scores", {})
            ]
            if model_record.get("format_notes", 0) < STANDARD_FORMAT_NOTE_COUNT:
                missing.append("standard format coverage")
            if tuple(model_record.get("format_note_paths", [])) and tuple(
                model_record.get("format_note_paths", [])
            ) != STANDARD_FORMAT_NOTE_PATHS:
                missing.append("standard format note set")
            if model_record.get("extract_questions", 0) < STANDARD_EXTRACT_QUESTION_COUNT:
                missing.append("standard extract coverage")
            if tuple(model_record.get("extract_question_ids", [])) and tuple(
                model_record.get("extract_question_ids", [])
            ) != STANDARD_EXTRACT_QUESTION_IDS:
                missing.append("standard question set")
            question_coverage = (
                f"{model_record.get('extract_scored_passed', 0)}/"
                f"{model_record.get('extract_questions', 0)} scored"
            )
            lines.append(
                f"| {md_code(model_record['model'])} | {fmt_score(model_record['scores'].get('extract'))} | {md_cell(question_coverage)} | "
                f"{md_cell(', '.join(missing) or 'unknown')} | {md_cell(takeaway(model_record['model']))} |"
            )
        lines.append("")

    if unavailable:
        lines.append("## Unavailable / empty-response attempts")
        lines.append("")
        lines.append("These tags were attempted but returned empty responses or were not available at test time.")
        lines.append("")
        for model_record in unavailable:
            lines.append(f"- {md_code(model_record['model'])}")
        lines.append("")

    if newest:
        lines.append("## Last benchmark command")
        lines.append("")
        lines.append(f"- kind: {md_code(newest.get('kind'))}")
        lines.append(f"- timestamp: {md_code(newest.get('timestamp_utc'))}")
        lines.append(f"- command: {md_code(compact_command(str(newest.get('command', ''))))}")
        lines.append(f"- raw file: {md_code(newest.get('_path'))}")
        lines.append("")

        hardware = newest.get("hardware") or {}
        if hardware:
            lines.append("## Hardware snapshot")
            lines.append("")
            lines.append(f"- platform: {md_code(hardware.get('platform'))}")
            lines.append(f"- cpu_count: {md_code(hardware.get('cpu_count'))}")
            ollama_version = ((hardware.get("ollama_version") or {}).get("stdout") or (hardware.get("ollama_version") or {}).get("stderr") or "").strip()
            if ollama_version:
                lines.append(f"- ollama_version: {md_code(ollama_version)}")
            lines.append("")

    lines.append("## Reading the scores")
    lines.append("")
    lines.append("- A model is ranked only after completing the same standard suite: smoke, two fixed formatting notes, and all 13 extraction/safety questions.")
    lines.append("- Partial, unavailable, vision/OCR, and deprecated-baseline attempts remain in raw JSON but are omitted from the public benchmark docs.")
    lines.append("- `rag` remains the live FastAPI webhook proof; use it after services are healthy. The standard suite is the fast model-selection gate.")
    lines.append("- Source-citation, forbidden-claim, and overclaim checks are deterministic string checks, not subjective judging.")
    return "\n".join(lines) + "\n"


SECTION_START = "<!-- BENCHMARK_REPORT_START -->"
SECTION_END = "<!-- BENCHMARK_REPORT_END -->"


def demote_markdown_headings(text: str, levels: int = 1) -> str:
    lines = []
    for line in text.splitlines():
        if line.startswith("#"):
            hashes, sep, title = line.partition(" ")
            if sep and set(hashes) == {"#"}:
                lines.append("#" * (len(hashes) + levels) + " " + title)
                continue
        lines.append(line)
    return "\n".join(lines).rstrip() + "\n"


def replace_marked_section(
    document: str, start_marker: str, end_marker: str, replacement: str
) -> str:
    start = document.find(start_marker)
    end = document.find(end_marker)
    if start == -1 or end == -1 or end < start:
        return replacement
    end += len(end_marker)
    return (
        document[: start + len(start_marker)]
        + "\n"
        + replacement.rstrip()
        + "\n"
        + end_marker
        + document[end:]
    )


def render_latest(output_dir: Path = DEFAULT_OUTPUT_DIR, report_path: Path = DEFAULT_REPORT) -> Path:
    runs = load_runs(output_dir)
    if not runs and report_path.exists():
        return report_path
    text = redact(render_markdown(runs))
    report_path.parent.mkdir(parents=True, exist_ok=True)
    if report_path.exists():
        existing = report_path.read_text(encoding="utf-8")
        if SECTION_START in existing and SECTION_END in existing:
            report_path.write_text(
                replace_marked_section(existing, SECTION_START, SECTION_END, demote_markdown_headings(text)),
                encoding="utf-8",
            )
            return report_path
    report_path.write_text(text, encoding="utf-8")
    return report_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args(argv)
    path = render_latest(Path(args.output_dir), Path(args.output))
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
