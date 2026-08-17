#!/usr/bin/env python3
"""Safe local Ollama benchmark harness for Synapse."""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML is required: python3 -m pip install pyyaml") from exc

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmark.constants import (  # noqa: E402
    CUSTOM_SUITE_ID,
    DEFAULT_FORMAT_NOTE_COUNT,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_QUESTION_LIMIT,
    MATRIX_PATH,
    NOTES_DIR,
    PROMPTS_PATH,
    QUESTIONS_PATH,
    BENCHMARK_REPORT_PATH,
    ROOT,
    STANDARD_EXTRACT_QUESTION_IDS,
    STANDARD_FORMAT_NOTE_PATHS,
    STANDARD_SUITE_ID,
    WORKFLOW_SCORE_WEIGHTS,
)
from scripts.proof.scoring import aggregate_scores, score_answer  # noqa: E402
from scripts.proof.redaction import redact_sensitive  # noqa: E402

REPORT_PATH = BENCHMARK_REPORT_PATH
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "") or os.environ.get("OLLAMA_CLOUD_API", "")
SAFE_ENV_KEYS = {"SYNAPSE_ASK_WEBHOOK_URL", "SYNAPSE_WEBHOOK_AUTH_TOKEN", "SYNAPSE_BENCH_AUTH_HEADER", "OLLAMA_HOST", "OLLAMA_API_KEY", "OLLAMA_CLOUD_API"}


_LOCAL_HOSTS = {"http://127.0.0.1:11434", "http://localhost:11434", "http://0.0.0.0:11434"}


def is_local_ollama() -> bool:
    return OLLAMA_HOST in _LOCAL_HOSTS or OLLAMA_HOST.startswith("http://127.") or OLLAMA_HOST.startswith("http://192.168.") or OLLAMA_HOST.startswith("http://10.")


def now_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML mapping")
    return data


def load_matrix() -> list[dict[str, Any]]:
    models = load_yaml(MATRIX_PATH).get("models", [])
    if not isinstance(models, list):
        raise ValueError("model_matrix.yml key 'models' must be a list")
    return models


def load_prompts() -> dict[str, Any]:
    return load_yaml(PROMPTS_PATH).get("workloads", {})


def load_questions() -> dict[str, Any]:
    return load_yaml(QUESTIONS_PATH)


def _path_from_root(rel_path: str) -> Path:
    return ROOT / rel_path


def select_format_notes(limit: int = DEFAULT_FORMAT_NOTE_COUNT) -> list[Path]:
    """Pick formatting notes; the default is a pinned standard set."""
    if limit == DEFAULT_FORMAT_NOTE_COUNT:
        return [_path_from_root(path) for path in STANDARD_FORMAT_NOTE_PATHS]
    notes = sorted(NOTES_DIR.glob("*.md"))
    if limit <= 0:
        return notes
    return sorted(notes, key=lambda p: len(p.read_text(encoding="utf-8")), reverse=True)[:limit]


def select_extract_questions(questions: list[dict[str, Any]], limit: int = DEFAULT_QUESTION_LIMIT) -> list[dict[str, Any]]:
    """Pick extraction questions; the default is the pinned standard set."""
    by_id = {str(q.get("id")): q for q in questions}
    if limit == DEFAULT_QUESTION_LIMIT:
        missing = [qid for qid in STANDARD_EXTRACT_QUESTION_IDS if qid not in by_id]
        if missing:
            raise ValueError(f"standard benchmark questions missing from fixtures: {', '.join(missing)}")
        return [by_id[qid] for qid in STANDARD_EXTRACT_QUESTION_IDS]
    if limit > 0:
        return questions[:limit]
    return list(questions)


def _suite_id_for(format_notes: list[Path], questions: list[dict[str, Any]]) -> str:
    note_paths = tuple(str(path.relative_to(ROOT)) for path in format_notes)
    question_ids = tuple(str(q.get("id")) for q in questions)
    if note_paths == STANDARD_FORMAT_NOTE_PATHS and question_ids == STANDARD_EXTRACT_QUESTION_IDS:
        return STANDARD_SUITE_ID
    return CUSTOM_SUITE_ID


def standard_suite_spec(
    *,
    questions: list[dict[str, Any]] | None = None,
    format_notes: list[Path] | None = None,
    question_limit: int = DEFAULT_QUESTION_LIMIT,
    format_note_count: int = DEFAULT_FORMAT_NOTE_COUNT,
) -> dict[str, Any]:
    """Describe the comparable benchmark suite for this run."""
    question_items = select_extract_questions(questions or load_questions().get("questions", []), question_limit)
    note_items = format_notes if format_notes is not None else select_format_notes(format_note_count)
    return {
        "suite_id": _suite_id_for(note_items, question_items),
        "workloads": ["smoke", "format", "extract"],
        "same_suite_required": True,
        "format_note_count": len(note_items),
        "format_notes": [str(path.relative_to(ROOT)) for path in note_items],
        "extract_question_count": len(question_items),
        "extract_question_ids": [str(q.get("id")) for q in question_items],
        "workflow_checks": ["availability smoke", "formatting", "grounded extraction", "safety boundaries"],
        "score_weights": WORKFLOW_SCORE_WEIGHTS,
    }


def weighted_workflow_score(scores: dict[str, float]) -> float:
    return round(sum(float(scores.get(name, 0)) * weight for name, weight in WORKFLOW_SCORE_WEIGHTS.items()), 2)


def validate_matrix(models: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    required = {"name", "family", "tier", "roles", "source_url", "timeout_seconds"}
    seen: set[str] = set()
    for idx, model in enumerate(models):
        missing = required - set(model)
        if missing:
            errors.append(f"model[{idx}] missing {sorted(missing)}")
        name = str(model.get("name", ""))
        if name in seen:
            errors.append(f"duplicate model name: {name}")
        seen.add(name)
        source_url = str(model.get("source_url", ""))
        if not model.get("external") and not source_url.startswith("https://ollama.com/library/"):
            errors.append(f"{name}: source_url must point to ollama library")
        params = float(model.get("parameters_b") or 0)
        if params >= 24 and model.get("enabled_by_default"):
            errors.append(f"{name}: 24B+ models must be disabled by default")
        if any(flag in name for flag in ("cloud", "mlx")) and model.get("enabled_by_default"):
            errors.append(f"{name}: cloud/mlx tags must be disabled by default")
        if model.get("track") in {"embedding", "ocr", "vision", "safeguard"} and model.get("enabled_by_default"):
            errors.append(f"{name}: specialized tracks must not be enabled by default")
    return errors


def parse_models_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def max_params_value(value: str | None) -> float | None:
    if not value:
        return None
    cleaned = value.lower().strip().replace("b", "")
    return float(cleaned)


def select_models(args: argparse.Namespace, *, include_disabled: bool = False) -> list[dict[str, Any]]:
    models = load_matrix()
    errors = validate_matrix(models)
    if errors:
        raise SystemExit("Invalid model matrix:\n" + "\n".join(errors))
    names = parse_models_arg(getattr(args, "models", None))
    tier = getattr(args, "tier", None)
    max_params = max_params_value(getattr(args, "max_params", None))
    selected: list[dict[str, Any]] = []
    for model in models:
        if names is None and not include_disabled and not model.get("enabled_by_default", False):
            continue
        if names is not None:
            # Allow matching against canonical alias (strip :latest)
            model_aliases = {model["name"], model["name"].replace(":latest", "")}
            if not any(a in names for a in model_aliases):
                continue
        if tier and model.get("tier") != tier:
            continue
        if max_params is not None and float(model.get("parameters_b") or 0) > max_params:
            continue
        selected.append(model)
    if names:
        found_aliases = set()
        for m in selected:
            found_aliases.add(m["name"])
            found_aliases.add(m["name"].replace(":latest", ""))
        missing = [name for name in names if name not in found_aliases]
        if missing:
            raise SystemExit(f"Requested models are not in selected matrix: {', '.join(missing)}")
    return selected


def run_cmd(cmd: list[str], timeout: int = 120) -> dict[str, Any]:
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True, timeout=timeout, check=False)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": redact(proc.stdout),
            "stderr": redact(proc.stderr),
            "duration_s": round(time.monotonic() - started, 3),
        }
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return {"ok": False, "returncode": None, "stdout": redact(stdout), "stderr": "timeout", "duration_s": round(time.monotonic() - started, 3)}


def redact(text: str) -> str:
    return redact_sensitive(text)


def ollama_generate(model: dict[str, Any], prompt: str, system: str = "", options: dict[str, Any] | None = None, timeout_scale: float = 1.0) -> dict[str, Any]:
    payload = {
        "model": model["name"],
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {
            "temperature": model.get("temperature", 0),
            "num_ctx": model.get("num_ctx", 4096),
            "num_predict": model.get("num_predict", 256),
        },
    }
    if options:
        payload["options"].update(options)
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "Synapse-Benchmark/1.0"}
    if OLLAMA_API_KEY:
        headers["Authorization"] = f"Bearer {OLLAMA_API_KEY}"
    req = request.Request(f"{OLLAMA_HOST}/api/generate", data=body, headers=headers, method="POST")
    timeout = max(1, int(float(model.get("timeout_seconds", 120)) * timeout_scale))
    started = time.monotonic()
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # Some cloud reasoning models return content in "thinking" instead of "response"
        raw_response = data.get("response", "") or data.get("thinking", "")
        response = redact(str(raw_response))
        return {"ok": True, "response": response, "raw": {k: v for k, v in data.items() if k not in ("response", "thinking")}, "latency_s": round(time.monotonic() - started, 3)}
    except (error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        return {"ok": False, "response": "", "error": redact(str(exc)), "latency_s": round(time.monotonic() - started, 3)}


def ollama_list_metadata() -> dict[str, Any]:
    """Read Ollama model metadata via HTTP, falling back to CLI if available."""
    models: dict[str, dict[str, str]] = {}
    try:
        req = request.Request(f"{OLLAMA_HOST}/api/tags", method="GET", headers={"User-Agent": "Synapse-Benchmark/1.0"})
        if OLLAMA_API_KEY:
            req.add_header("Authorization", f"Bearer {OLLAMA_API_KEY}")
        with request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        for item in data.get("models", []):
            name = item.get("name")
            if name:
                models[name] = {
                    "id": str(item.get("digest", ""))[:12],
                    "size": str(item.get("size", "")),
                    "modified_at": str(item.get("modified_at", "")),
                }
        return {"command": {"ok": True, "stdout": "ollama /api/tags"}, "models": models}
    except Exception as exc:  # noqa: BLE001 - metadata is best effort
        if not shutil.which("ollama"):
            return {"command": {"ok": False, "stderr": redact(str(exc))}, "models": models}
    out = run_cmd(["ollama", "list"], timeout=30)
    for line in out.get("stdout", "").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 3:
            models[parts[0]] = {"id": parts[1], "size": " ".join(parts[2:4]) if len(parts) >= 4 else parts[2]}
    return {"command": out, "models": models}


def hardware_info() -> dict[str, Any]:
    return {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "cpu_count": os.cpu_count(),
        "memory": run_cmd(["free", "-h"], timeout=10),
        "disk": run_cmd(["df", "-h", str(ROOT)], timeout=10),
        "nproc": run_cmd(["nproc"], timeout=10),
        "lscpu": run_cmd(["lscpu"], timeout=10),
        "nvidia_smi": run_cmd(["nvidia-smi"], timeout=15) if shutil.which("nvidia-smi") else {"ok": False, "stderr": "nvidia-smi not found"},
        "ollama_version": run_cmd(["ollama", "--version"], timeout=20) if shutil.which("ollama") else {"ok": False, "stderr": "ollama not found"},
    }


def write_run(kind: str, command: list[str], results: dict[str, Any], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{now_id()}-{kind}.json"
    payload = {
        "kind": kind,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "command": " ".join(command),
        "hardware": hardware_info() if kind in {"smoke", "format", "extract", "suite", "full"} else None,
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def cmd_list(args: argparse.Namespace) -> int:
    models = select_models(args, include_disabled=True)
    print(f"Configured models: {len(models)}")
    for model in models:
        enabled = "enabled" if model.get("enabled_by_default") else "disabled"
        print(f"- {model['name']} | tier={model.get('tier')} | params={model.get('parameters_b')}B | track={model.get('track')} | {enabled} | roles={','.join(model.get('roles', []))}")
    return 0


def cmd_hardware(args: argparse.Namespace) -> int:
    info = hardware_info()
    print(json.dumps(info, indent=2))
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    selected = select_models(args)
    results = {"models": []}
    for model in selected:
        before = run_cmd(["df", "-h", str(ROOT)], timeout=10)
        if is_local_ollama():
            pull = run_cmd(["ollama", "pull", model["name"]], timeout=int(model.get("timeout_seconds", 300)) * 2)
        else:
            # Remote/cloud Ollama: verify model is available via API tags instead of local CLI pull
            meta = ollama_list_metadata()
            if model["name"] in meta.get("models", {}):
                pull = {"ok": True, "skipped": True, "note": "remote model already listed"}
            else:
                # Try a lightweight generate/ping to confirm the model loads remotely
                ping = ollama_generate(model, "say exactly PONG", "", {"num_predict": 3}, timeout_scale=0.5)
                pull = {"ok": ping.get("ok"), "note": "remote ping"}
        after = run_cmd(["df", "-h", str(ROOT)], timeout=10)
        listed = ollama_list_metadata()
        results["models"].append({"model": model["name"], "pull": pull, "disk_before": before, "disk_after": after, "listed": model["name"] in listed["models"], "metadata": listed["models"].get(model["name"])})
        print(f"{model['name']}: {'ok' if pull['ok'] else 'failed'}")
    path = write_run("pull", sys.argv, results, Path(args.output_dir))
    print(f"Wrote {path}")
    return 0 if all(item["pull"]["ok"] for item in results["models"]) else 1


def ensure_model_ready(model: dict[str, Any], list_meta: dict[str, Any], *, skip_pull: bool) -> dict[str, Any]:
    if skip_pull:
        return {"ok": True, "skipped": True}
    if model["name"] in list_meta.get("models", {}):
        return {"ok": True, "skipped": True, "note": "model already listed"}
    if is_local_ollama():
        return run_cmd(["ollama", "pull", model["name"]], timeout=int(model.get("timeout_seconds", 300)) * 2)
    ping = ollama_generate(model, "say exactly PONG", "", {"num_predict": 3}, timeout_scale=0.5)
    return {"ok": bool(ping.get("ok")), "note": "remote ping", "latency_s": ping.get("latency_s"), "error": ping.get("error")}


def run_smoke_workload(model: dict[str, Any], prompts: dict[str, Any], args: argparse.Namespace, list_meta: dict[str, Any]) -> dict[str, Any]:
    pull = ensure_model_ready(model, list_meta, skip_pull=bool(getattr(args, "skip_pull", False)))
    gen = ollama_generate(model, prompts["user"], prompts.get("system", ""), prompts.get("options"), args.timeout_scale) if pull.get("ok") else {"ok": False, "error": "pull failed", "response": ""}
    marker = prompts["marker"]
    passed = bool(gen.get("ok") and marker in gen.get("response", ""))
    return {"pull": pull, "generation": gen, "passed": passed, "metadata": list_meta.get("models", {}).get(model["name"])}


def run_format_workload(
    model: dict[str, Any],
    prompts: dict[str, Any],
    expectations: dict[str, Any],
    test_notes: list[Path],
    args: argparse.Namespace,
) -> dict[str, Any]:
    model_scores = []
    note_runs = []
    for path in test_notes:
        note_text = path.read_text(encoding="utf-8")
        prompt = prompts["user_template"].format(source_path=str(path.relative_to(ROOT)), note=note_text)
        gen = ollama_generate(model, prompt, prompts.get("system", ""), prompts.get("options"), args.timeout_scale)
        local_expectations = dict(expectations)
        local_expectations["required_facts"] = [fact for fact in expectations.get("required_facts", []) if str(fact).casefold() in note_text.casefold()]
        scored = score_answer(gen.get("response", ""), local_expectations)
        model_scores.append(scored)
        note_runs.append({"source_path": str(path.relative_to(ROOT)), "ok": gen.get("ok"), "latency_s": gen.get("latency_s"), "score": scored.as_dict(), "output_chars": len(gen.get("response", ""))})
    agg = aggregate_scores(model_scores)
    return {"format": agg, "notes": note_runs, "passed": bool(agg["passed"])}


def run_extract_workload(
    model: dict[str, Any],
    prompts: dict[str, Any],
    questions: list[dict[str, Any]],
    context: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    q_runs = []
    scores = []
    for q in questions:
        prompt = prompts["user_template"].format(context=context, question=q["question"])
        gen = ollama_generate(model, prompt, prompts.get("system", ""), prompts.get("options"), args.timeout_scale)
        scored = score_answer(gen.get("response", ""), q, require_sources=bool(q.get("expected_sources") or q.get("required_source_count")))
        scores.append(scored)
        q_runs.append({"id": q.get("id"), "ok": gen.get("ok"), "latency_s": gen.get("latency_s"), "score": scored.as_dict(), "answer": gen.get("response", "")[:1000]})
    agg = aggregate_scores(scores)
    return {"extract": agg, "questions": q_runs, "passed": bool(agg["passed"])}


def cmd_smoke(args: argparse.Namespace) -> int:
    selected = select_models(args)
    prompts = load_prompts()["smoke"]
    list_meta = ollama_list_metadata()
    results = {"benchmark_spec": standard_suite_spec(), "models": []}
    for model in selected:
        smoke = run_smoke_workload(model, prompts, args, list_meta)
        gen = smoke["generation"]
        results["models"].append({"model": model["name"], "pull": smoke["pull"], "smoke": gen, "passed": smoke["passed"], "metadata": smoke["metadata"]})
        print(f"{model['name']}: {'pass' if smoke['passed'] else 'fail'} ({gen.get('latency_s', 'n/a')}s)")
    path = write_run("smoke", sys.argv, results, Path(args.output_dir))
    print(f"Wrote {path}")
    return 0 if all(item["passed"] for item in results["models"]) else 1


def fixture_context(max_chars: int = 6000) -> str:
    parts = []
    for path in sorted(NOTES_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        rel = path.relative_to(ROOT)
        parts.append(f"\n--- SOURCE: {rel} ---\n{text}")
    return redact("\n".join(parts))[:max_chars]


def cmd_format(args: argparse.Namespace) -> int:
    selected = select_models(args)
    prompts = load_prompts()["format"]
    question_data = load_questions()
    expectations = question_data.get("format_expectations", {})
    test_notes = select_format_notes(int(getattr(args, "format_note_count", DEFAULT_FORMAT_NOTE_COUNT)))
    results = {"benchmark_spec": standard_suite_spec(questions=question_data.get("questions", []), format_notes=test_notes, question_limit=int(getattr(args, "question_limit", DEFAULT_QUESTION_LIMIT))), "models": []}
    for model in selected:
        formatted = run_format_workload(model, prompts, expectations, test_notes, args)
        results["models"].append({"model": model["name"], **formatted})
        agg = formatted["format"]
        print(f"{model['name']}: format score {agg['score']} pass={agg['passed']}")
    path = write_run("format", sys.argv, results, Path(args.output_dir))
    print(f"Wrote {path}")
    return 0 if all(item["passed"] for item in results["models"]) else 1


def cmd_extract(args: argparse.Namespace) -> int:
    selected = select_models(args)
    prompts = load_prompts()["extract"]
    question_data = load_questions()
    questions = question_data.get("questions", [])
    context = fixture_context()
    test_questions = select_extract_questions(questions, int(getattr(args, "question_limit", DEFAULT_QUESTION_LIMIT)))
    test_notes = select_format_notes(int(getattr(args, "format_note_count", DEFAULT_FORMAT_NOTE_COUNT)))
    results = {"benchmark_spec": standard_suite_spec(questions=questions, format_notes=test_notes, question_limit=int(getattr(args, "question_limit", DEFAULT_QUESTION_LIMIT))), "models": []}
    for model in selected:
        extracted = run_extract_workload(model, prompts, test_questions, context, args)
        results["models"].append({"model": model["name"], **extracted})
        agg = extracted["extract"]
        print(f"{model['name']}: extract score {agg['score']} pass={agg['passed']}")
    path = write_run("extract", sys.argv, results, Path(args.output_dir))
    print(f"Wrote {path}")
    return 0 if all(item["passed"] for item in results["models"]) else 1


def load_env_safely() -> dict[str, str]:
    env_path = ROOT / ".env"
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"\'')
        if key in SAFE_ENV_KEYS:
            env[key] = value
    return env


def cmd_rag(args: argparse.Namespace) -> int:
    env = load_env_safely()
    webhook = os.environ.get("SYNAPSE_ASK_WEBHOOK_URL") or env.get("SYNAPSE_ASK_WEBHOOK_URL")
    if not webhook:
        raise SystemExit("RAG benchmark requires SYNAPSE_ASK_WEBHOOK_URL in env/.env")
    questions = load_questions().get("questions", [])
    results = {"webhook": redact(webhook), "questions": []}
    headers = {"Content-Type": "application/json"}
    synapse_token = os.environ.get("SYNAPSE_WEBHOOK_AUTH_TOKEN") or env.get("SYNAPSE_WEBHOOK_AUTH_TOKEN")
    if synapse_token:
        headers["X-Synapse-Token"] = synapse_token
    for q in questions:
        payload = {"question": q["question"], "source_path": q.get("source_path")}
        req = request.Request(webhook, data=json.dumps(payload).encode(), headers=headers, method="POST")
        started = time.monotonic()
        try:
            with request.urlopen(req, timeout=60) as resp:
                text = redact(resp.read().decode("utf-8"))
            scored = score_answer(text, q, require_sources=True)
            ok = True
            err = None
        except Exception as exc:  # noqa: BLE001 - report per question, do not print secrets
            text = ""
            scored = score_answer(text, q, require_sources=True)
            ok = False
            err = redact(str(exc))
        results["questions"].append({"id": q.get("id"), "ok": ok, "error": err, "latency_s": round(time.monotonic() - started, 3), "score": scored.as_dict(), "answer": text[:1000]})
    path = write_run("rag", sys.argv, results, Path(args.output_dir))
    print(f"Wrote {path}")
    return 0 if all(item["ok"] and item["score"]["passed"] for item in results["questions"]) else 1


def cmd_suite(args: argparse.Namespace) -> int:
    """Run the fixed smoke+format+extract suite for every selected model."""
    selected = select_models(args)
    prompts = load_prompts()
    question_data = load_questions()
    questions = question_data.get("questions", [])
    test_questions = select_extract_questions(questions, int(getattr(args, "question_limit", DEFAULT_QUESTION_LIMIT)))
    test_notes = select_format_notes(int(getattr(args, "format_note_count", DEFAULT_FORMAT_NOTE_COUNT)))
    spec = standard_suite_spec(questions=questions, format_notes=test_notes, question_limit=int(getattr(args, "question_limit", DEFAULT_QUESTION_LIMIT)))
    context = fixture_context()
    list_meta = ollama_list_metadata()
    results = {"benchmark_spec": spec, "models": []}
    for model in selected:
        smoke = run_smoke_workload(model, prompts["smoke"], args, list_meta)
        formatted = run_format_workload(model, prompts["format"], question_data.get("format_expectations", {}), test_notes, args)
        extracted = run_extract_workload(model, prompts["extract"], test_questions, context, args)
        scores = {
            "smoke": 100 if smoke["passed"] else 0,
            "format": float(formatted["format"].get("score", 0)),
            "extract": float(extracted["extract"].get("score", 0)),
        }
        suite = {
            "suite_id": spec["suite_id"],
            "score": weighted_workflow_score(scores),
            "passed": bool(smoke["passed"] and formatted["passed"] and extracted["passed"]),
            "scores": scores,
            "weights": WORKFLOW_SCORE_WEIGHTS,
        }
        results["models"].append(
            {
                "model": model["name"],
                "suite": suite,
                "smoke": smoke,
                "format": formatted["format"],
                "notes": formatted["notes"],
                "extract": extracted["extract"],
                "questions": extracted["questions"],
                "passed": suite["passed"],
            }
        )
        print(f"{model['name']}: workflow score {suite['score']} pass={suite['passed']} (smoke={scores['smoke']}, format={scores['format']}, extract={scores['extract']})")
    path = write_run("suite", sys.argv, results, Path(args.output_dir))
    print(f"Wrote {path}")
    return 0 if all(item["passed"] for item in results["models"]) else 1


def cmd_full(args: argparse.Namespace) -> int:
    if not args.no_live_workflow and not args.full_workflow:
        raise SystemExit("Full benchmark avoids Docker service mutation by default. Re-run with --full-workflow to opt in, or --no-live-workflow for the fixed smoke+format+extract suite.")
    exit_code = cmd_suite(args)
    if args.full_workflow:
        print("Full live workflow proof is not automated safely in this harness yet; use rag after services are healthy.", file=sys.stderr)
        exit_code = 1
    return exit_code


def cmd_report(args: argparse.Namespace) -> int:
    from scripts.benchmark.report import render_latest

    path = render_latest(Path(args.output_dir), REPORT_PATH)
    print(f"Wrote {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    sub = parser.add_subparsers(dest="command", required=True)

    def add_filters(p: argparse.ArgumentParser) -> None:
        p.add_argument("--models", help="comma-separated model tags")
        p.add_argument("--tier", help="tier filter: tiny, small, medium, large, max32")
        p.add_argument("--max-params", help="maximum parameter count, e.g. 32b")
        p.add_argument("--timeout-scale", type=float, default=1.0)
        p.add_argument("--format-note-count", type=int, default=DEFAULT_FORMAT_NOTE_COUNT, help="number of formatting notes; default is the pinned standard note set, other values create a custom unranked suite")
        p.add_argument("--question-limit", type=int, default=DEFAULT_QUESTION_LIMIT, help="number of extraction questions; 0 means the pinned standard question set, other values create a custom unranked suite")
        p.add_argument("--skip-pull", action="store_true")
        p.add_argument("--no-live-workflow", action="store_true")
        p.add_argument("--full-workflow", action="store_true")
        p.add_argument("--redact-private-network", action="store_true", default=True)

    p = sub.add_parser("list", help="print configured model matrix")
    add_filters(p)
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("hardware", help="print local hardware readiness")
    p.set_defaults(func=cmd_hardware)
    p = sub.add_parser("pull", help="pull selected models one at a time")
    add_filters(p)
    p.set_defaults(func=cmd_pull)
    p = sub.add_parser("smoke", help="run direct Ollama smoke benchmark")
    add_filters(p)
    p.set_defaults(func=cmd_smoke)
    p = sub.add_parser("format", help="run Markdown formatting benchmark")
    add_filters(p)
    p.set_defaults(func=cmd_format)
    p = sub.add_parser("extract", help="run direct fact extraction benchmark")
    add_filters(p)
    p.set_defaults(func=cmd_extract)
    p = sub.add_parser("suite", help="run the fixed comparable smoke+format+extract benchmark for every selected model")
    add_filters(p)
    p.set_defaults(func=cmd_suite)
    p = sub.add_parser("rag", help="run Synapse ask-webhook benchmark")
    add_filters(p)
    p.set_defaults(func=cmd_rag)
    p = sub.add_parser("full", help="run local full harness, with live workflow only by explicit opt-in")
    add_filters(p)
    p.set_defaults(func=cmd_full)
    p = sub.add_parser("report", help="render latest results into .local-artifacts/benchmarks/benchmark-report.md")
    p.add_argument("--latest", action="store_true", help="accepted for backward compatibility")
    p.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
