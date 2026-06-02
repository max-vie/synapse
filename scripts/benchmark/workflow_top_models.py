#!/usr/bin/env python3
"""Run live Synapse workflow proof for top-ranked Ollama models.

This is intentionally separate from the deterministic smoke+format+extract suite.
It switches the FastAPI Synapse service to each candidate model, runs the Local E2E fresh-note proof, and
writes a sanitized `kind=workflow` benchmark JSON so the committed benchmark
report can render a separate live-workflow section.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmark import report  # noqa: E402
from scripts.benchmark.constants import BENCHMARK_REPORT_PATH, DEFAULT_OUTPUT_DIR, MATRIX_PATH, ROOT  # noqa: E402

OUTPUT_DIR = DEFAULT_OUTPUT_DIR
EVIDENCE_DIR = ROOT / ".local-artifacts" / "evidence"
ENV_FILE = ROOT / ".env"
E2E_PROOF = ROOT / "scripts" / "e2e" / "local_e2e_proof.py"
REPORT_PATH = BENCHMARK_REPORT_PATH
MODEL_MATRIX = MATRIX_PATH
SECRET_KEYS = ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "APP_KEY", "KEY")


def now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def redact(text: str, env: dict[str, str] | None = None) -> str:
    out = report.redact(text)
    env = env or {}
    for key, value in env.items():
        if value and any(marker in key for marker in SECRET_KEYS):
            out = out.replace(value, "[REDACTED]")
    return out


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def set_env_values(path: Path, updates: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = {key: False for key in updates}
    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        replaced = False
        for key, value in updates.items():
            if stripped.startswith(f"{key}="):
                new_lines.append(f"{key}={value}")
                seen[key] = True
                replaced = True
                break
        if not replaced:
            new_lines.append(line)
    for key, was_seen in seen.items():
        if not was_seen:
            new_lines.append(f"{key}={updates[key]}")
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def set_env_models(path: Path, model: str) -> None:
    set_env_values(path, {"OLLAMA_FORMAT_MODEL": model, "OLLAMA_ANSWER_MODEL": model})


def complex_collection_name(model: str, *, run_id: str | None = None) -> str:
    run_part = run_id or now_id()
    safe_model = re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_").lower()
    return f"synapse_e2e_complex_{run_part}_{safe_model}"


def run_shell(command: str, *, timeout: int, env: dict[str, str] | None = None) -> dict[str, Any]:
    started = time.monotonic()
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    try:
        proc = subprocess.run(
            ["bash", "-lc", command],
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=proc_env,
        )
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_s": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return {"ok": False, "returncode": None, "stdout": stdout, "stderr": stderr or "timeout", "duration_s": round(time.monotonic() - started, 3)}


def compose(command: str, *, timeout: int) -> dict[str, Any]:
    return run_shell(f"source scripts/e2e/lib.sh && compose {command}", timeout=timeout)


def compose_model_names() -> set[str]:
    out = compose("exec -T ollama ollama list", timeout=120)
    names = set()
    for line in out.get("stdout", "").splitlines()[1:]:
        parts = line.split()
        if parts:
            names.add(parts[0])
    return names


def load_matrix_params() -> dict[str, float]:
    try:
        import yaml
    except ImportError:
        return {}
    data = yaml.safe_load(MODEL_MATRIX.read_text(encoding="utf-8")) or {}
    return {str(model.get("name")): float(model.get("parameters_b") or 0) for model in data.get("models", [])}


def select_top_models(limit: int, max_params: float, explicit_models: list[str] | None) -> list[str]:
    if explicit_models:
        return explicit_models[:limit]
    runs = report.load_runs(OUTPUT_DIR)
    comparable = report.comparable_standard_records(runs)
    params = load_matrix_params()
    selected: list[str] = []
    for rec in comparable:
        model = str(rec["model"])
        if params.get(model, 0.0) <= max_params:
            selected.append(model)
        if len(selected) >= limit:
            break
    return selected


def parse_evidence(model: str, env: dict[str, str], duration_s: float, ok: bool, output: str, error: str) -> dict[str, Any]:
    evidence_path = EVIDENCE_DIR / "local-e2e-latest.json"
    evidence: dict[str, Any] = {}
    if evidence_path.exists():
        try:
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            evidence = {}
    raw_summary = evidence.get("summary")
    summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
    raw_checks = evidence.get("checks")
    checks: list[Any] = raw_checks if isinstance(raw_checks, list) else []
    raw_notes = evidence.get("notes")
    notes: list[Any] = raw_notes if isinstance(raw_notes, list) else []
    rag = evidence.get("rag") or {}
    sources = rag.get("sources") or []
    first_source = sources[0].get("source_path") if sources and isinstance(sources[0], dict) else ""
    if notes and isinstance(notes[0], dict):
        fresh_note = str(notes[0].get("note_path") or "")
    else:
        fresh_note = str(evidence.get("note_path") or "")
    workflow_score = summary.get("score") if summary else (100 if ok and evidence.get("verdict") == "PASS" else 0)
    workflow_passed = bool(ok and evidence.get("verdict") == "PASS" and (summary.get("passed", True) if summary else True))
    raw_failed_check_ids = summary.get("failed_check_ids")
    failed_check_ids = raw_failed_check_ids if isinstance(raw_failed_check_ids, list) else [str(check.get("id")) for check in checks if isinstance(check, dict) and not check.get("passed")]
    notes_posted = summary.get("notes_posted") if "notes_posted" in summary else (len(notes) if notes else None)
    indexed_chunks = summary.get("indexed_chunks") if "indexed_chunks" in summary else summary.get("notes_indexed")
    return {
        "model": model,
        "workflow": {"passed": workflow_passed, "score": workflow_score},
        "suite_id": evidence.get("suite_id", ""),
        "run_id": evidence.get("run_id", ""),
        "fresh_note": fresh_note,
        "qdrant_collection": evidence.get("qdrant_collection", ""),
        "qdrant_points": evidence.get("qdrant_points_for_note"),
        "checks_passed": summary.get("checks_passed"),
        "checks_total": summary.get("checks_total"),
        "failed_check_ids": failed_check_ids,
        "notes_posted": notes_posted,
        "indexed_chunks": indexed_chunks,
        "checks": checks,
        "rag_source": first_source,
        "duration_s": round(duration_s, 3),
        "stdout_tail": redact("\n".join(output.splitlines()[-40:]), env),
        "error": redact(error, env),
    }


def run_workflow_for_model(model: str, args: argparse.Namespace, original_env_text: str, original_models: set[str]) -> dict[str, Any]:
    env = load_dotenv(ENV_FILE)
    started = time.monotonic()
    pulled_here = (not args.skip_pull) and model not in original_models
    try:
        suite_arg = getattr(args, "proof_suite", "simple")
        env_updates = {"OLLAMA_FORMAT_MODEL": model, "OLLAMA_ANSWER_MODEL": model}
        if suite_arg == "complex":
            env_updates.update(
                {
                    "QDRANT_COLLECTION": complex_collection_name(model),
                    "SYNAPSE_ANSWER_MODE": "extractive",
                    "SYNAPSE_HTTP_TIMEOUT_SECONDS": "300",
                }
            )
        set_env_values(ENV_FILE, env_updates)
        evidence_path = EVIDENCE_DIR / "local-e2e-latest.json"
        if evidence_path.exists():
            evidence_path.unlink()
        if not args.skip_pull:
            pull = compose(f"exec -T ollama ollama pull {sh_quote(model)}", timeout=args.pull_timeout)
            if not pull.get("ok"):
                return parse_evidence(model, env, time.monotonic() - started, False, pull.get("stdout", ""), pull.get("stderr", "pull failed"))
        recreate = compose("up -d --force-recreate synapse-service", timeout=300)
        if not recreate.get("ok"):
            return parse_evidence(model, env, time.monotonic() - started, False, recreate.get("stdout", ""), recreate.get("stderr", "synapse-service recreate failed"))
        proof = run_shell(f"python3 {sh_quote(str(E2E_PROOF))} --suite {suite_arg}", timeout=args.workflow_timeout)
        return parse_evidence(model, env, time.monotonic() - started, bool(proof.get("ok")), proof.get("stdout", ""), proof.get("stderr", ""))
    finally:
        if args.delete_after and pulled_here:
            compose(f"exec -T ollama ollama rm {sh_quote(model)}", timeout=120)
        ENV_FILE.write_text(original_env_text, encoding="utf-8")
        compose("up -d --force-recreate synapse-service", timeout=300)


def sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def write_run(models: list[dict[str, Any]], args: argparse.Namespace) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"{now_id()}-workflow.json"
    payload = {
        "kind": "workflow",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(sys.argv),
        "results": {
            "selection": {
                "source": "top comparable standard-suite models",
                "limit": args.limit,
                "max_params": args.max_params,
                "proof_suite": args.proof_suite,
            },
            "models": models,
        },
    }
    path.write_text(report.redact(json.dumps(payload, indent=2, sort_keys=True)), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5, help="number of top models to live-test")
    parser.add_argument("--max-params", type=float, default=48.0, help="skip models over this parameter count")
    parser.add_argument("--models", help="comma-separated explicit model list instead of auto top-N")
    parser.add_argument("--pull-timeout", type=int, default=7200)
    parser.add_argument("--workflow-timeout", type=int, default=2400)
    parser.add_argument("--proof-suite", choices=("simple", "complex"), default="simple", help="Local E2E proof suite to run")
    parser.add_argument("--skip-pull", action="store_true", help="do not pull into compose Ollama; assume selected models already exist at the configured container-reachable Ollama endpoint")
    parser.add_argument("--delete-after", action="store_true", help="delete models that were not installed before this script")
    args = parser.parse_args()

    if not ENV_FILE.exists():
        raise SystemExit(f"missing {ENV_FILE}")
    explicit = [part.strip() for part in args.models.split(",") if part.strip()] if args.models else None
    selected = select_top_models(args.limit, args.max_params, explicit)
    if not selected:
        raise SystemExit("no top models selected for workflow proof")
    print("workflow proof models=" + ",".join(selected), flush=True)

    original_env_text = ENV_FILE.read_text(encoding="utf-8")
    original_models = compose_model_names()
    results = []
    for model in selected:
        print(f"== workflow {model} ==", flush=True)
        item = run_workflow_for_model(model, args, original_env_text, original_models)
        results.append(item)
        print(f"{model}: live workflow score {item['workflow']['score']} pass={item['workflow']['passed']}", flush=True)

    path = write_run(results, args)
    print(f"Wrote {path}")
    rendered = report.render_latest(OUTPUT_DIR, REPORT_PATH)
    print(f"Wrote {rendered}")
    return 0 if all(item.get("workflow", {}).get("passed") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
