#!/usr/bin/env python3
"""Run a localhost Synapse E2E proof and write sanitized evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.benchmark.scoring import score_answer  # noqa: E402
from scripts.benchmark.ollama_models import redact as benchmark_redact  # noqa: E402
from scripts.e2e import create_qdrant_collection as qdrant_setup  # noqa: E402

ENV_FILE = ROOT / ".env"
EVIDENCE_DIR = ROOT / ".local-artifacts" / "evidence"
COMPLEX_SUITE_ID = "synapse-live-complex-v1"
REAL_LOCAL_STACK_SUITE_ID = "synapse-real-local-stack-v1"
OSPF_SUITE_ID = "synapse-live-ospf-v1"
PROOF_NOTE_DIR = "Synapse-Demo/generated-proof-notes"
LOCAL_URL_RE = re.compile(
    r"(?i)\bhttps?://(?:"
    r"localhost|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|"
    r"192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}|\[::1\]"
    r")(?::\d+)?(?:/[^\s\"'<>)]*)?"
)


def proof_note_path(filename: str) -> str:
    return f"{PROOF_NOTE_DIR}/{filename.lstrip('/')}"


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        raise SystemExit(f"missing {path}; run scripts/e2e/setup.sh first")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def request_timeout_seconds() -> int:
    raw = os.environ.get("SYNAPSE_E2E_REQUEST_TIMEOUT", "300")
    try:
        return max(1, int(raw))
    except ValueError:
        return 300


def request_json(url: str, payload: dict | None = None, headers: dict[str, str] | None = None, timeout: int | None = None, method: str | None = None) -> dict:
    timeout = request_timeout_seconds() if timeout is None else timeout
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    req_headers.update(headers or {})
    req_method = method or ("POST" if payload is not None else "GET")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=req_method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {detail}") from exc


def http_probe(
    url: str,
    payload: dict | None = None,
    headers: dict[str, str] | None = None,
    timeout: int | None = None,
    method: str | None = None,
) -> tuple[str, str]:
    timeout = request_timeout_seconds() if timeout is None else timeout
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    req_headers.update(headers or {})
    req_method = method or ("POST" if payload is not None else "GET")
    req = urllib.request.Request(url, data=data, headers=req_headers, method=req_method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return str(response.status), response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return str(exc.code), exc.read().decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - readiness evidence should capture connection failures.
        return "000", str(exc)


def http_status(url: str, timeout: int = 8, attempts: int = 15) -> str:
    last = "000"
    for _ in range(attempts):
        status, _detail = http_probe(url, timeout=timeout)
        if status != "000":
            return status
        last = status
        time.sleep(2)
    return last


def redact(text: str, env: dict[str, str]) -> str:
    out = text
    out = LOCAL_URL_RE.sub("<LOCAL_URL>", out)
    for key, value in env.items():
        if any(word in key for word in ("TOKEN", "SECRET", "PASSWORD", "API_KEY", "APP_KEY")) and value:
            out = out.replace(value, "[REDACTED]")
    return benchmark_redact(out)


def ollama_health_url(env: dict[str, str]) -> str:
    base_url = (env.get("OLLAMA_HOST_BASE_URL") or "").strip().rstrip("/")
    if base_url:
        return base_url
    return f"http://127.0.0.1:{env.get('OLLAMA_PORT', '11434')}"


def service_urls(env: dict[str, str]) -> dict[str, str]:
    return {
        "qdrant": f"http://127.0.0.1:{env.get('QDRANT_PORT', '6333')}",
        "synapse": f"http://127.0.0.1:{env.get('SYNAPSE_SERVICE_PORT', '15515')}",
        "wikijs": f"http://127.0.0.1:{env.get('WIKIJS_PORT', '3000')}",
        "ollama": ollama_health_url(env),
    }


def readiness_result(ready: bool, endpoint: str, status: str, detail: str = "") -> dict[str, Any]:
    return {"ready": ready, "endpoint": endpoint, "status": status, "detail": detail}


def synapse_readiness(synapse_url: str, webhook_headers: dict[str, str] | None = None, attempts: int = 15) -> dict[str, Any]:
    base_url = synapse_url.rstrip("/")
    health_endpoint = base_url + "/healthz"
    webhook_endpoint = base_url + "/webhook/synapse/ask"
    last_status = "000"
    last_detail = ""
    for attempt in range(attempts):
        health_status, health_detail = http_probe(health_endpoint)
        webhook_status, webhook_detail = http_probe(webhook_endpoint, {"question": ""}, webhook_headers or {}, method="POST")
        if health_status.startswith(("2", "3")) and webhook_status not in {"000", "404"}:
            return readiness_result(True, f"{health_endpoint}; {webhook_endpoint}", f"{health_status}/{webhook_status}", "Synapse API health endpoint and webhook route responded")
        last_status = f"{health_status}/{webhook_status}"
        last_detail = f"healthz={health_detail}; webhook={webhook_detail}"
        if attempt + 1 < attempts:
            time.sleep(2)
    return readiness_result(False, f"{health_endpoint}; {webhook_endpoint}", last_status, last_detail or "Synapse API did not become ready")


def qdrant_readiness(qdrant_url: str, attempts: int = 15) -> dict[str, Any]:
    endpoint = qdrant_url.rstrip("/") + "/collections"
    last_detail = ""
    for attempt in range(attempts):
        try:
            data = request_json(endpoint)
            if isinstance(data, dict) and "result" in data:
                return readiness_result(True, endpoint, "200", "collections endpoint returned Qdrant metadata")
            last_detail = f"unexpected response: {data}"
        except Exception as exc:  # noqa: BLE001 - readiness evidence should explain failed service checks.
            last_detail = str(exc)
        if attempt + 1 < attempts:
            time.sleep(2)
    return readiness_result(False, endpoint, "error", last_detail)


def ollama_readiness(ollama_url: str, attempts: int = 15) -> dict[str, Any]:
    endpoint = ollama_url.rstrip("/") + "/api/tags"
    last_detail = ""
    for attempt in range(attempts):
        try:
            data = request_json(endpoint)
            if isinstance(data, dict) and isinstance(data.get("models"), list):
                return readiness_result(True, endpoint, "200", "model tags endpoint returned models list")
            last_detail = f"unexpected response: {data}"
        except Exception as exc:  # noqa: BLE001 - readiness evidence should explain failed service checks.
            last_detail = str(exc)
        if attempt + 1 < attempts:
            time.sleep(2)
    return readiness_result(False, endpoint, "error", last_detail)


def wikijs_readiness(wikijs_url: str, gql_headers: dict[str, str] | None = None, attempts: int = 15) -> dict[str, Any]:
    endpoint = wikijs_url.rstrip("/") + "/graphql"
    payload = {"query": "query { pages { list { id path title } } }"}
    last_detail = ""
    for attempt in range(attempts):
        try:
            data = request_json(endpoint, payload, gql_headers or {})
            if isinstance(data, dict) and not data.get("errors") and "data" in data:
                return readiness_result(True, endpoint, "200", "authenticated GraphQL query succeeded")
            last_detail = f"GraphQL errors or unexpected response: {data}"
        except Exception as exc:  # noqa: BLE001 - readiness evidence should explain failed service checks.
            last_detail = str(exc)
        if attempt + 1 < attempts:
            time.sleep(2)
    return readiness_result(False, endpoint, "error", last_detail)


def health_snapshot(
    urls: dict[str, str],
    webhook_headers: dict[str, str] | None = None,
    gql_headers: dict[str, str] | None = None,
    attempts: int = 15,
) -> dict[str, dict[str, Any]]:
    return {
        "synapse": synapse_readiness(urls["synapse"], webhook_headers, attempts),
        "wikijs": wikijs_readiness(urls["wikijs"], gql_headers, attempts),
        "qdrant": qdrant_readiness(urls["qdrant"], attempts),
        "ollama": ollama_readiness(urls["ollama"], attempts),
    }


def require_health(health: dict[str, Any]) -> None:
    failures = []
    for service, result in health.items():
        if isinstance(result, dict):
            if result.get("ready"):
                continue
            failures.append(
                f"{service} endpoint={result.get('endpoint', 'unknown')} "
                f"status={result.get('status', 'unknown')} detail={result.get('detail', '')}"
            )
        elif result == "200":
            continue
        else:
            failures.append(f"{service} status={result}")
    if failures:
        raise SystemExit("readiness check failed: " + "; ".join(failures))


def auth_headers(env: dict[str, str]) -> dict[str, str]:
    auth_token = env.get("SYNAPSE_WEBHOOK_AUTH_TOKEN", "")
    return {"X-Synapse-Token": auth_token} if auth_token else {}


def wikijs_headers(env: dict[str, str]) -> dict[str, str]:
    wikijs_token = env.get("WIKIJS_API_TOKEN") or env.get("WIKIJS_API") or ""
    if not wikijs_token or wikijs_token.startswith("replace-"):
        raise SystemExit("missing usable WIKIJS_API_TOKEN in .env")
    return {"Authorization": f"Bearer {wikijs_token}"}


def build_complex_suite(run_id: str, nonce: str) -> dict[str, Any]:
    """Return a public-safe adversarial live workflow suite spec."""
    current_codename = f"complex-codename-{nonce}"
    stale_codename = f"stale-codename-{nonce}"
    queue_name = f"complex-queue-{nonce}"
    incident_id = f"CX-{nonce.upper()}-42"
    exact_command = "python3 scripts/benchmark/workflow_top_models.py --proof-suite complex --models gemma3:27b,qwen2.5-coder:14b,qwen2.5-coder:3b,qwen3.6:27b --skip-pull"
    current_path = proof_note_path(f"{run_id}-current.md")
    stale_path = proof_note_path(f"{run_id}-stale.md")
    boundary_path = proof_note_path(f"{run_id}-boundary.md")
    notes = [
        {
            "id": "current_evidence",
            "path": current_path,
            "content": (
                f"# Complex Synapse Current Evidence {run_id}\n\n"
                f"The current verification codename is {current_codename}.\n"
                f"The active incident queue is {queue_name}.\n"
                f"The current incident marker is {incident_id}.\n"
                f"The exact replay command is `{exact_command}`.\n"
                "This current note supersedes any stale complex benchmark notes for the same run.\n"
            ),
            "required_marker": current_codename,
            "format": False,
        },
        {
            "id": "stale_decoy",
            "path": stale_path,
            "content": (
                f"# Complex Synapse Stale Evidence {run_id}\n\n"
                f"This is stale superseded evidence. The old verification codename was {stale_codename}.\n"
                f"Do not use {stale_codename} as the current answer. The newer current evidence note is {current_path}.\n"
            ),
            "required_marker": stale_codename,
            "format": False,
        },
        {
            "id": "public_claim_boundary",
            "path": boundary_path,
            "content": (
                f"# Complex Synapse Public Claim Boundary {run_id}\n\n"
                "Synapse is local lab automation only, not production-ready and not a public SaaS.\n"
                "There is no public URL, no customer deployment, and no enterprise-ready claim.\n"
                "Secrets and API tokens stay [REDACTED]; no real token is present in this note.\n"
                f"Boundary applies to incident marker {incident_id}.\n"
            ),
            "required_marker": "[REDACTED]",
            "format": False,
        },
    ]
    checks = [
        {
            "id": "current_codename_live",
            "question": f"What is the current verification codename for {run_id}?",
            "source_path": current_path,
            "expectation": {"required_facts": [current_codename], "forbidden_facts": [stale_codename], "expected_sources": [current_path]},
        },
        {
            "id": "newer_beats_stale_live",
            "question": f"What current verification codename is written in the current evidence note for {run_id}? Do not answer with any old codename.",
            "source_path": current_path,
            "expectation": {"required_facts": [current_codename], "forbidden_facts": [stale_codename], "expected_sources": [current_path], "required_source_count": 1},
        },
        {
            "id": "exact_command_live",
            "question": f"Return the exact replay command recorded for {run_id}.",
            "source_path": current_path,
            "expectation": {"required_facts": [exact_command], "forbidden_facts": ["workflow_top_models.py --models"], "expected_sources": [current_path]},
        },
        {
            "id": "multi_source_boundary_live",
            "question": f"For {incident_id}, quote the queue and explicitly state both boundary phrases: local lab automation and not production-ready.",
            "expectation": {
                "required_facts": [queue_name, "not production-ready", "local lab automation"],
                "forbidden_facts": ["enterprise-ready", "public SaaS"],
                "expected_sources": [current_path, boundary_path],
                "required_source_count": 2,
            },
        },
        {
            "id": "unsupported_public_url_live",
            "question": f"What is the public ingress URL for {run_id}?",
            "source_path": boundary_path,
            "expectation": {
                "type": "unsupported",
                "accepted_facts": ["no public URL", "not provided", "insufficient context"],
                "forbidden_facts": ["http://", "https://", "public ingress url is"],
                "expected_sources": [boundary_path],
            },
        },
        {
            "id": "unsupported_secret_live",
            "question": f"What API token or credential should be used for {run_id}?",
            "source_path": boundary_path,
            "expectation": {
                "type": "unsupported",
                "accepted_facts": ["[REDACTED]", "insufficient context", "no real token"],
                "forbidden_facts": ["sk-", "Bearer ", "password is", "api key"],
                "expected_sources": [boundary_path],
            },
        },
    ]
    return {"suite_id": COMPLEX_SUITE_ID, "run_id": run_id, "notes": notes, "checks": checks}


def build_real_local_stack_suite(run_id: str, nonce: str) -> dict[str, Any]:
    """Return the manual proof suite for the real local Compose stack."""
    notes = [
        {
            "id": "network_runbook",
            "path": proof_note_path(f"{run_id}-network-runbook.md"),
            "content": (
                f"# Network Operations Runbook {run_id}\n\n"
                f"OSPF uses Dijkstra's Shortest Path First algorithm in this lab. Marker net-{nonce}.\n"
                "Routers should prefer the documented backbone area before advertising new lab links.\n"
            ),
            "required_marker": f"net-{nonce}",
        },
        {
            "id": "backup_runbook",
            "path": proof_note_path(f"{run_id}-backup-runbook.md"),
            "content": (
                f"# Backup Restore Runbook {run_id}\n\n"
                f"The nightly backup verification window is 02:30 UTC. Marker bak-{nonce}.\n"
                "A restore proof must read back the restored checksum before the run is accepted.\n"
            ),
            "required_marker": f"bak-{nonce}",
        },
        {
            "id": "database_notes",
            "path": proof_note_path(f"{run_id}-database-notes.md"),
            "content": (
                f"# PostgreSQL Maintenance Notes {run_id}\n\n"
                f"Autovacuum tuning focuses on dead tuples and table bloat. Marker db-{nonce}.\n"
                "The maintenance owner records slow query evidence before changing indexes.\n"
            ),
            "required_marker": f"db-{nonce}",
        },
        {
            "id": "incident_notes",
            "path": proof_note_path(f"{run_id}-incident-notes.md"),
            "content": (
                f"# Incident Response Notes {run_id}\n\n"
                f"The first escalation channel is the lab-ops bridge. Marker inc-{nonce}.\n"
                "Every incident update must include impact, owner, next action, and timestamp.\n"
            ),
            "required_marker": f"inc-{nonce}",
        },
        {
            "id": "model_eval_notes",
            "path": proof_note_path(f"{run_id}-model-eval-notes.md"),
            "content": (
                f"# Model Evaluation Notes {run_id}\n\n"
                f"Answer quality is checked with grounded citations and refusal behavior. Marker eval-{nonce}.\n"
                "A model fails the proof if it answers without a usable indexed source.\n"
            ),
            "required_marker": f"eval-{nonce}",
        },
    ]
    by_id = {note["id"]: note for note in notes}
    def check(note_id: str, check_id: str, question: str, required_facts: list[str]) -> dict[str, Any]:
        source_path = by_id[note_id]["path"]
        return {
            "id": check_id,
            "question": question,
            "source_path": source_path,
            "expectation": {"required_facts": required_facts, "expected_sources": [source_path]},
        }

    checks = [
        check("network_runbook", "ospf_algorithm", "Which algorithm does OSPF use in the network runbook?", ["Dijkstra", "Shortest Path First"]),
        check("network_runbook", "backbone_area", "What should routers prefer before advertising new lab links?", ["backbone area"]),
        check("backup_runbook", "backup_window", "What is the nightly backup verification window?", ["02:30 UTC"]),
        check("backup_runbook", "restore_acceptance", "What must a restore proof read back before acceptance?", ["restored checksum"]),
        check("database_notes", "autovacuum_focus", "What does autovacuum tuning focus on in the database notes?", ["dead tuples", "table bloat"]),
        check("database_notes", "index_change_evidence", "What evidence is recorded before changing indexes?", ["slow query evidence"]),
        check("incident_notes", "escalation_channel", "What is the first escalation channel for incidents?", ["lab-ops bridge"]),
        check("incident_notes", "incident_update_fields", "Which fields must every incident update include?", ["impact", "owner", "next action", "timestamp"]),
        check("model_eval_notes", "model_quality_checks", "How is answer quality checked in the model evaluation notes?", ["grounded citations", "refusal behavior"]),
        check("model_eval_notes", "model_failure_rule", "When does a model fail the proof?", ["without a usable indexed source"]),
    ]
    return {"suite_id": REAL_LOCAL_STACK_SUITE_ID, "run_id": run_id, "notes": notes, "checks": checks}


def assert_real_stack_config(env: dict[str, str]) -> None:
    model_values = " ".join(
        env.get(name, "")
        for name in ("OLLAMA_EMBED_MODEL", "OLLAMA_ANSWER_MODEL", "OLLAMA_FORMAT_MODEL", "OLLAMA_INTERNAL_BASE_URL", "OLLAMA_CHAT_BASE_URL")
    ).casefold()
    if "mock" in model_values:
        raise SystemExit("real-local-stack-proof requires real Ollama models/URLs, not mock Ollama settings")
    if qdrant_vector_size(env) < 128:
        raise SystemExit("real-local-stack-proof requires a normal Qdrant vector size; mock 8-dimensional collections are not accepted")


def run_real_local_stack_proof(env: dict[str, str]) -> int:
    assert_real_stack_config(env)
    urls = service_urls(env)
    webhook_headers = auth_headers(env)
    gql_headers = wikijs_headers(env)
    qdrant_collection = env.get("QDRANT_COLLECTION", "synapse_notes")
    run_id = "real-local-stack-proof-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    suite = build_real_local_stack_suite(run_id, secrets.token_hex(3))
    health = health_snapshot(urls, webhook_headers=webhook_headers, gql_headers=gql_headers)
    require_health(health)
    ensure_qdrant_collection(urls["qdrant"], env, qdrant_collection)

    note_results = [
        post_and_verify_note(
            note,
            env=env,
            urls=urls,
            qdrant_collection=qdrant_collection,
            webhook_headers=webhook_headers,
            gql_headers=gql_headers,
        )
        for note in suite["notes"]
    ]
    checks = [run_live_rag_check(check, urls=urls, webhook_headers=webhook_headers) for check in suite["checks"]]
    check_scores = [float(check.get("score") or 0) for check in checks]
    checks_passed = sum(1 for check in checks if check.get("passed"))
    summary = {
        "score": round(sum(check_scores) / len(check_scores), 2) if check_scores else 0.0,
        "passed": bool(checks and checks_passed == len(checks)),
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "notes_posted": len(note_results),
        "indexed_chunks": sum(int(note.get("qdrant_points_for_note") or 0) for note in note_results),
    }
    raw = {
        "verdict": "PASS" if summary["passed"] else "FAIL",
        "suite_id": REAL_LOCAL_STACK_SUITE_ID,
        "run_id": run_id,
        "health": health,
        "qdrant_collection": qdrant_collection,
        "notes": note_results,
        "checks": checks,
        "summary": summary,
    }
    write_evidence(raw, env)
    report_text = render_real_local_stack_report(raw)
    (EVIDENCE_DIR / "real-local-stack-proof-report.md").write_text(redact(report_text, env), encoding="utf-8")
    print(redact(report_text, env))
    return 0 if summary["passed"] else 1


def render_real_local_stack_report(raw: dict[str, Any]) -> str:
    summary = raw.get("summary") or {}
    lines = [
        "# Synapse Real Local Stack Proof Evidence",
        "",
        f"Verdict: {raw.get('verdict')}",
        f"Suite: {raw.get('suite_id')}",
        f"Run ID: {raw.get('run_id')}",
        f"Score: {summary.get('score')}",
        f"Checks: {summary.get('checks_passed')}/{summary.get('checks_total')}",
        f"Notes posted: {summary.get('notes_posted')}",
        f"Indexed chunks: {summary.get('indexed_chunks')}",
        "",
        "Scope:",
        "- Real Ollama embedding and answer models.",
        "- Real Wiki.js GraphQL create/update/readback.",
        "- Qdrant with normal vector size.",
        "- At least 5 realistic notes and 10 realistic questions.",
        "",
        "Checks:",
    ]
    for check in raw.get("checks") or []:
        status = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- {status} {check.get('id')}: {check.get('score')}")
    lines.append("")
    return "\n".join(lines)


def build_ospf_suite(run_id: str) -> dict[str, Any]:
    """Return a public-safe live RAG proof focused on the user's OSPF question."""
    note_suffix = run_id.removeprefix("e2e-ospf-")
    note_path = proof_note_path(f"networking-notes-{note_suffix}.md")
    question = "what algorithm is used in ospf?"
    required_terms = ["Dijkstra", "Shortest Path First", "SPF"]
    answer_sentence = "OSPF uses Dijkstra's Shortest Path First (SPF) algorithm."
    note = {
        "id": "ospf_algorithm_evidence",
        "path": note_path,
        "content": (
            "# Networking Notes\n\n"
            f"{answer_sentence}\n"
            "Open Shortest Path First uses this SPF calculation to build a shortest-path tree for each router.\n"
            "This is generated public-safe lab content for a Synapse Ask live RAG TUI proof.\n"
        ),
        "required_marker": answer_sentence,
    }
    absent_check = {
        "id": "ospf_absent_refuses",
        "phase": "before_note",
        "question": question,
        "source_path": note_path,
        "expectation": {
            "type": "unsupported",
            "accepted_facts": ["insufficient context", "not enough indexed note context", "do not have enough indexed note context"],
            "forbidden_facts": required_terms,
        },
    }
    backed_check = {
        "id": "ospf_note_backed_answer",
        "phase": "after_note",
        "question": question,
        "source_path": note_path,
        "expectation": {
            "required_facts": required_terms,
            "expected_sources": [note_path],
            "required_source_count": 1,
        },
    }
    return {"suite_id": OSPF_SUITE_ID, "run_id": run_id, "notes": [note], "checks": [absent_check, backed_check], "required_terms": required_terms}


def write_evidence(raw: dict[str, Any], env: dict[str, str]) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    (EVIDENCE_DIR / "local-e2e-latest.json").write_text(redact(json.dumps(raw, indent=2, ensure_ascii=False), env) + "\n", encoding="utf-8")


def verify_wikijs_page(wikijs_url: str, gql_headers: dict[str, str], wiki_path: str, required_text: str) -> str:
    page_path = str(wiki_path).lstrip("/")
    pages = request_json(f"{wikijs_url}/graphql", {"query": "query { pages { list { id path title } } }"}, gql_headers)
    match = next((p for p in pages.get("data", {}).get("pages", {}).get("list", []) if p.get("path") == page_path), None)
    if not match:
        raise SystemExit(f"Wiki.js page not found: {page_path}")
    page = request_json(
        f"{wikijs_url}/graphql",
        {"query": "query Page($id:Int!){ pages { single(id:$id) { id path title content } } }", "variables": {"id": int(match["id"])}},
        gql_headers,
    )
    page_content = page.get("data", {}).get("pages", {}).get("single", {}).get("content", "")
    if required_text not in page_content:
        raise SystemExit(f"Wiki.js page does not contain required marker for {page_path}")
    return str(page_content)


def _frontmatter_value(content: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.+?)\s*$", content)
    return match.group(1).strip() if match else ""


def verify_wiki_index_match(
    wikijs_url: str,
    gql_headers: dict[str, str],
    wiki_path: str,
    note_id: Any,
    points: list[dict[str, Any]],
) -> dict[str, Any]:
    content = verify_wikijs_page(wikijs_url, gql_headers, wiki_path, "synapse_content_hash:")
    wiki_hash = _frontmatter_value(content, "synapse_content_hash")
    qdrant_hashes = {
        str(point.get("payload", {}).get("current_content_hash") or point.get("payload", {}).get("content_hash") or "")
        for point in points
        if isinstance(point.get("payload"), dict)
    }
    qdrant_hashes.discard("")
    if not wiki_hash or qdrant_hashes != {wiki_hash}:
        raise SystemExit(
            f"wiki/index mismatch for note_id={note_id}: "
            f"wiki_content_hash={wiki_hash or '<missing>'} qdrant_hashes={sorted(qdrant_hashes)}"
        )
    return {"content_hash": wiki_hash, "qdrant_hashes": sorted(qdrant_hashes)}


def scroll_note_points(qdrant_url: str, collection: str, note_id: Any) -> list[dict[str, Any]]:
    points: list[dict[str, Any]] = []
    offset: Any = None
    while True:
        payload = {"limit": 20, "with_payload": True, "with_vector": False, "filter": {"must": [{"key": "note_id", "match": {"value": note_id}}]}}
        if offset is not None:
            payload["offset"] = offset
        qdrant_scroll = request_json(f"{qdrant_url}/collections/{collection}/points/scroll", payload)
        result = qdrant_scroll.get("result", {})
        points.extend(result.get("points", []) or [])
        offset = result.get("next_page_offset")
        if offset is None:
            return points


def qdrant_vector_size(env: dict[str, str]) -> int:
    return qdrant_setup.embedding_dimension(env, lambda url, payload=None, method=None: request_json(url, payload, method=method))


def qdrant_vector_config(collection_info: dict[str, Any]) -> tuple[Any, Any]:
    return qdrant_setup.vector_config(collection_info)


def qdrant_collection_metadata(collection_info: dict[str, Any]) -> dict[str, Any]:
    return qdrant_setup.collection_metadata(collection_info)


def ensure_qdrant_collection(qdrant_url: str, env: dict[str, str], collection: str) -> None:
    model = env.get("OLLAMA_EMBED_MODEL", qdrant_setup.DEFAULT_EMBED_MODEL)
    vector_size = qdrant_vector_size(env)
    metadata = {"embedding_model": model, "embedding_dimension": vector_size}
    try:
        collection_info = request_json(f"{qdrant_url}/collections/{collection}")
    except RuntimeError as exc:
        if "404" not in str(exc):
            raise
    else:
        actual_size, actual_distance = qdrant_vector_config(collection_info)
        actual_metadata = qdrant_collection_metadata(collection_info)
        if actual_size == vector_size and actual_distance == "Cosine" and actual_metadata.get("embedding_model") == model:
            return
        if actual_size == vector_size and actual_distance == "Cosine" and not actual_metadata.get("embedding_model"):
            qdrant_setup.apply_collection_metadata(lambda url, payload=None, method=None: request_json(url, payload, method=method), qdrant_url, collection, metadata)
            return
        raise SystemExit(
            "Qdrant collection schema mismatch for "
            f"{collection}: expected size={vector_size} distance=Cosine embedding_model={model}; "
            f"actual size={actual_size} distance={actual_distance} "
            f"actual embedding_model={actual_metadata.get('embedding_model', 'unknown')}. "
            "Use a new QDRANT_COLLECTION name or recreate the collection."
        )
    request_json(
        f"{qdrant_url}/collections/{collection}",
        {"vectors": {"size": vector_size, "distance": "Cosine"}, "metadata": metadata},
        method="PUT",
    )
    qdrant_setup.apply_collection_metadata(lambda url, payload=None, method=None: request_json(url, payload, method=method), qdrant_url, collection, metadata)


def post_and_verify_note(
    note: dict[str, Any],
    *,
    env: dict[str, str],
    urls: dict[str, str],
    qdrant_collection: str,
    webhook_headers: dict[str, str],
    gql_headers: dict[str, str],
) -> dict[str, Any]:
    vault = ROOT / env.get("OBSIDIAN_VAULT_PATH", "examples/obsidian-vault")
    note_file = vault / note["path"]
    note_file.parent.mkdir(parents=True, exist_ok=True)
    note_file.write_text(note["content"], encoding="utf-8")
    payload = {"path": note["path"], "content": note["content"]}
    for optional_key in ("publish", "format"):
        if optional_key in note:
            payload[optional_key] = note[optional_key]
    post_response = request_json(f"{urls['synapse']}/webhook/synapse/note", payload, webhook_headers)
    if post_response.get("status") != "ok" or post_response.get("publisher") != "wikijs":
        raise SystemExit(f"note post failed: {post_response}")
    verify_wikijs_page(urls["wikijs"], gql_headers, str(post_response["wiki_path"]), str(note["required_marker"]))
    points = scroll_note_points(urls["qdrant"], qdrant_collection, post_response["note_id"])
    consistency = verify_wiki_index_match(urls["wikijs"], gql_headers, str(post_response["wiki_path"]), post_response["note_id"], points)
    payload_text = "\n".join(str(p.get("payload", {}).get("text", "")) for p in points)
    if not points or str(note["required_marker"]) not in payload_text:
        raise SystemExit(f"Qdrant payload does not contain required marker for {note['path']}")
    return {
        "id": note["id"],
        "note_path": note["path"],
        "post_response": post_response,
        "wiki_index_consistency": consistency,
        "qdrant_points_for_note": len(points),
    }


def score_live_answer(answer_text: str, expectation: dict[str, Any], *, require_sources: bool) -> dict[str, Any]:
    result = score_answer(answer_text, expectation, require_sources=require_sources)
    accepted = [str(fact) for fact in expectation.get("accepted_facts") or []]
    accepted_found = [fact for fact in accepted if fact.casefold() in answer_text.casefold()]
    explicit_insufficient = False
    try:
        parsed_answer = json.loads(answer_text)
        explicit_insufficient = isinstance(parsed_answer, dict) and parsed_answer.get("insufficient_context") is True
    except json.JSONDecodeError:
        explicit_insufficient = False
    if expectation.get("type") == "unsupported" and result.required_missing and (accepted_found or explicit_insufficient):
        result.required_found.extend(accepted_found or ["insufficient_context:true"])
        result.required_missing = []
        result.passed = not result.forbidden_found and not result.source_errors and not result.safety_errors
        if result.passed:
            result.score = 100.0
    return result.as_dict()


def rag_scoring_text(rag: dict[str, Any]) -> str:
    """Return RAG content used for scoring without internal service URLs."""
    sources = []
    for source in rag.get("sources") or []:
        if not isinstance(source, dict):
            continue
        sources.append(
            {
                "title": source.get("title", ""),
                "source_path": source.get("source_path", ""),
                "wiki_path": source.get("wiki_path", ""),
            }
        )
    return json.dumps(
        {
            "answer": rag.get("answer", ""),
            "insufficient_context": rag.get("insufficient_context"),
            "sources": sources,
        },
        ensure_ascii=False,
    )


def run_complex_proof(env: dict[str, str]) -> int:
    urls = service_urls(env)
    webhook_headers = auth_headers(env)
    gql_headers = wikijs_headers(env)
    qdrant_collection = env.get("QDRANT_COLLECTION", "synapse_notes")
    run_id = "e2e-complex-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    suite = build_complex_suite(run_id, secrets.token_hex(3))
    health = health_snapshot(urls, webhook_headers=webhook_headers, gql_headers=gql_headers)
    require_health(health)
    ensure_qdrant_collection(urls["qdrant"], env, qdrant_collection)

    note_results = [
        post_and_verify_note(
            note,
            env=env,
            urls=urls,
            qdrant_collection=qdrant_collection,
            webhook_headers=webhook_headers,
            gql_headers=gql_headers,
        )
        for note in suite["notes"]
    ]

    checks: list[dict[str, Any]] = []
    for check in suite["checks"]:
        payload = {"question": check["question"]}
        if check.get("source_path"):
            payload["source_path"] = check["source_path"]
        try:
            rag = request_json(f"{urls['synapse']}/webhook/synapse/ask", payload, webhook_headers)
            answer_text = rag_scoring_text(rag)
            expectation = check.get("expectation") or {}
            score = score_live_answer(answer_text, expectation, require_sources=bool(expectation.get("expected_sources")))
            checks.append({
                "id": check["id"],
                "question": check["question"],
                "source_path": check.get("source_path", ""),
                "passed": bool(score["passed"]),
                "score": score["score"],
                "rag": rag,
                "score_detail": score,
            })
        except Exception as exc:  # noqa: BLE001 - evidence should capture failed live checks.
            checks.append({"id": check["id"], "question": check["question"], "passed": False, "score": 0.0, "error": str(exc)})

    check_scores = [float(check.get("score") or 0) for check in checks]
    checks_passed = sum(1 for check in checks if check.get("passed"))
    indexed_chunks = sum(int(note.get("qdrant_points_for_note") or 0) for note in note_results)
    summary = {
        "score": round(sum(check_scores) / len(check_scores), 2) if check_scores else 0.0,
        "passed": bool(checks and checks_passed == len(checks)),
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "failed_check_ids": [str(check["id"]) for check in checks if not check.get("passed")],
        "notes_posted": len(note_results),
        "indexed_chunks": indexed_chunks,
    }
    raw = {
        "verdict": "PASS" if summary["passed"] else "FAIL",
        "suite_id": COMPLEX_SUITE_ID,
        "run_id": run_id,
        "health": health,
        "qdrant_collection": qdrant_collection,
        "notes": note_results,
        "checks": checks,
        "summary": summary,
    }
    write_evidence(raw, env)
    report_text = render_complex_report(raw)
    (EVIDENCE_DIR / "local-e2e-report.md").write_text(redact(report_text, env), encoding="utf-8")
    print(redact(report_text, env))
    return 0 if summary["passed"] else 1


def render_complex_report(raw: dict[str, Any]) -> str:
    summary = raw.get("summary") or {}
    lines = [
        "# Synapse Local Complex E2E Evidence",
        "",
        f"Verdict: {raw.get('verdict')}",
        f"Suite: {raw.get('suite_id')}",
        f"Run ID: {raw.get('run_id')}",
        f"Score: {summary.get('score')}",
        f"Checks: {summary.get('checks_passed')}/{summary.get('checks_total')}",
        f"Notes posted: {summary.get('notes_posted')}",
        f"Indexed chunks: {summary.get('indexed_chunks')}",
        "",
        "Checks:",
    ]
    for check in raw.get("checks") or []:
        status = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- {status} {check.get('id')}: {check.get('score')}")
    lines.append("")
    return "\n".join(lines)


def run_live_rag_check(check: dict[str, Any], *, urls: dict[str, str], webhook_headers: dict[str, str]) -> dict[str, Any]:
    payload = {"question": check["question"]}
    if check.get("source_path"):
        payload["source_path"] = check["source_path"]
    try:
        rag = request_json(f"{urls['synapse']}/webhook/synapse/ask", payload, webhook_headers)
        expectation = check.get("expectation") or {}
        score = score_live_answer(rag_scoring_text(rag), expectation, require_sources=bool(expectation.get("expected_sources")))
        return {
            "id": check["id"],
            "phase": check.get("phase", ""),
            "question": check["question"],
            "source_path": check.get("source_path", ""),
            "passed": bool(score["passed"]),
            "score": score["score"],
            "rag": rag,
            "score_detail": score,
        }
    except Exception as exc:  # noqa: BLE001 - evidence should capture failed live checks.
        return {"id": check["id"], "phase": check.get("phase", ""), "question": check["question"], "source_path": check.get("source_path", ""), "passed": False, "score": 0.0, "error": str(exc)}


def render_ospf_report(raw: dict[str, Any]) -> str:
    summary = raw.get("summary") or {}
    checks = raw.get("checks") or []
    positive = next((check for check in checks if check.get("id") == "ospf_note_backed_answer"), checks[-1] if checks else {})
    rag = positive.get("rag") or {}
    first_source = (rag.get("sources") or [{}])[0]
    lines = [
        "# Synapse OSPF RAG TUI Evidence",
        "",
        f"Verdict: {raw.get('verdict')}",
        f"Suite: {raw.get('suite_id')}",
        f"Run ID: {raw.get('run_id')}",
        f"Question: {positive.get('question')}",
        f"Fresh note: {raw.get('note_path')}",
        f"Required terms: {', '.join(raw.get('required_terms') or [])}",
        f"Checks: {summary.get('checks_passed')}/{summary.get('checks_total')}",
        "",
        "Checks:",
    ]
    for check in checks:
        status = "PASS" if check.get("passed") else "FAIL"
        lines.append(f"- {status} {check.get('id')}: {check.get('score')}")
    lines.extend([
        "",
        "RAG:",
        f"- insufficient_context: {rag.get('insufficient_context')}",
        f"- answer: {rag.get('answer')}",
        f"- first source: {first_source.get('source_path')}",
        "",
    ])
    return "\n".join(lines)


def run_ospf_proof(env: dict[str, str]) -> int:
    urls = service_urls(env)
    webhook_headers = auth_headers(env)
    gql_headers = wikijs_headers(env)
    qdrant_collection = env.get("QDRANT_COLLECTION", "synapse_notes")
    run_id = "e2e-ospf-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    suite = build_ospf_suite(run_id)
    health = health_snapshot(urls, webhook_headers=webhook_headers, gql_headers=gql_headers)
    require_health(health)
    ensure_qdrant_collection(urls["qdrant"], env, qdrant_collection)

    checks: list[dict[str, Any]] = []
    before_checks = [check for check in suite["checks"] if check.get("phase") == "before_note"]
    after_checks = [check for check in suite["checks"] if check.get("phase") != "before_note"]
    for check in before_checks:
        checks.append(run_live_rag_check(check, urls=urls, webhook_headers=webhook_headers))

    note_result = post_and_verify_note(
        suite["notes"][0],
        env=env,
        urls=urls,
        qdrant_collection=qdrant_collection,
        webhook_headers=webhook_headers,
        gql_headers=gql_headers,
    )
    for check in after_checks:
        checks.append(run_live_rag_check(check, urls=urls, webhook_headers=webhook_headers))

    check_scores = [float(check.get("score") or 0) for check in checks]
    checks_passed = sum(1 for check in checks if check.get("passed"))
    summary = {
        "score": round(sum(check_scores) / len(check_scores), 2) if check_scores else 0.0,
        "passed": bool(checks and checks_passed == len(checks)),
        "checks_passed": checks_passed,
        "checks_total": len(checks),
        "notes_posted": 1,
        "indexed_chunks": int(note_result.get("qdrant_points_for_note") or 0),
    }
    raw = {
        "verdict": "PASS" if summary["passed"] else "FAIL",
        "suite_id": OSPF_SUITE_ID,
        "run_id": run_id,
        "note_path": suite["notes"][0]["path"],
        "required_terms": suite["required_terms"],
        "health": health,
        "qdrant_collection": qdrant_collection,
        "notes": [note_result],
        "checks": checks,
        "summary": summary,
    }
    write_evidence(raw, env)
    report_text = render_ospf_report(raw)
    (EVIDENCE_DIR / "local-e2e-report.md").write_text(redact(report_text, env), encoding="utf-8")
    print(redact(report_text, env))
    return 0 if summary["passed"] else 1


def run_ci_proof(env: dict[str, str]) -> int:
    urls = service_urls(env)
    webhook_headers = auth_headers(env)
    qdrant_collection = env.get("QDRANT_COLLECTION", "synapse_ci_e2e")
    run_id = "ci-e2e-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    unique_phrase = f"synapse-ci-proof-{secrets.token_hex(4)}"
    note_path = proof_note_path("ci-e2e.md")
    note_content = (
        "# Synapse CI E2E Note\n\n"
        f"The Synapse CI e2e verification codename is {unique_phrase}.\n\n"
        "This mocked test proves workflow import, webhook execution, Qdrant indexing, and source-grounded RAG adapter plumbing with a synthetic Ollama service and without Wiki.js.\n"
    )

    health = {
        "synapse": synapse_readiness(urls["synapse"], webhook_headers=webhook_headers, attempts=30),
        "qdrant": qdrant_readiness(urls["qdrant"], attempts=30),
        "mock_ollama": readiness_result(True, "http://mock-ollama:11435/api/tags", "compose", "mock Ollama is Compose-internal; synapse-service health depends on it"),
    }
    require_health(health)
    ensure_qdrant_collection(urls["qdrant"], env, qdrant_collection)

    post_response = request_json(
        f"{urls['synapse']}/webhook/synapse/index-note",
        {"path": note_path, "content": note_content},
        webhook_headers,
    )
    if post_response.get("status") != "indexed" or int(post_response.get("chunks") or 0) < 1:
        raise SystemExit(f"CI index webhook failed: {post_response}")
    note_id = post_response.get("note_id")
    if not note_id:
        raise SystemExit(f"CI index response did not include note_id: {post_response}")

    points = scroll_note_points(urls["qdrant"], qdrant_collection, note_id)
    payload_text = "\n".join(str(point.get("payload", {}).get("text", "")) for point in points)
    source_paths = {str(point.get("payload", {}).get("source_path", "")) for point in points}
    if not points or unique_phrase not in payload_text or note_path not in source_paths:
        raise SystemExit(f"CI Qdrant grounding payload missing expected source or phrase: paths={sorted(source_paths)}")

    rag = request_json(
        f"{urls['synapse']}/webhook/synapse/ask",
        {"question": "What is the Synapse CI e2e verification codename?", "source_path": note_path},
        webhook_headers,
    )
    first_source = (rag.get("sources") or [{}])[0]
    if rag.get("insufficient_context") is not False:
        raise SystemExit(f"CI RAG query returned insufficient context: {rag}")
    if unique_phrase not in str(rag.get("answer", "")) or "[1]" not in str(rag.get("answer", "")):
        raise SystemExit(f"CI RAG answer lacks codename or citation: {rag}")
    if first_source.get("source_path") != note_path:
        raise SystemExit(f"CI RAG source grounding mismatch: {rag}")

    raw = {
        "verdict": "PASS",
        "suite_id": "synapse-mocked-fastapi-qdrant-e2e-v1",
        "run_id": run_id,
        "note_path": note_path,
        "unique_phrase": unique_phrase,
        "health": health,
        "post_response": post_response,
        "qdrant_collection": qdrant_collection,
        "qdrant_points_for_note": len(points),
        "rag": rag,
    }
    write_evidence(raw, env)
    report = f"""# Synapse Mocked FastAPI/Qdrant E2E Evidence\n\nVerdict: PASS\nSuite: synapse-mocked-fastapi-qdrant-e2e-v1\nRun ID: {run_id}\nFresh note: {note_path}\nIndexed chunks: {post_response.get('chunks')}\nQdrant points: {len(points)}\n\nScope:\n- Uses a Compose-internal mock Ollama service.\n- Does not prove real Ollama model quality, real embedding dimensions, or Wiki.js GraphQL behavior.\n\nRAG:\n- insufficient_context: {rag.get('insufficient_context')}\n- answer: {rag.get('answer')}\n- first source: {first_source.get('source_path')}\n"""
    (EVIDENCE_DIR / "ci-e2e-report.md").write_text(redact(report, env), encoding="utf-8")
    print(redact(report, env))
    return 0


def run_simple_proof(env: dict[str, str]) -> int:
    urls = service_urls(env)
    webhook_headers = auth_headers(env)
    gql_headers = wikijs_headers(env)
    run_id = "e2e-" + dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    unique_phrase = f"synapse-local-proof-{run_id}-{secrets.token_hex(3)}"
    note_path = proof_note_path(f"{run_id}.md")
    note_content = (
        f"# Synapse Local E2E {run_id}\n\n"
        f"The verification codename is {unique_phrase}. The primary publisher is Wiki.js.\n\n"
        "This note was generated by scripts/e2e/local-e2e-proof.sh for live proof.\n"
    )
    vault = ROOT / env.get("OBSIDIAN_VAULT_PATH", "examples/obsidian-vault")
    note_file = vault / note_path
    note_file.parent.mkdir(parents=True, exist_ok=True)
    note_file.write_text(note_content, encoding="utf-8")

    qdrant_collection = env.get("QDRANT_COLLECTION", "synapse_notes")
    health = health_snapshot(urls, webhook_headers=webhook_headers, gql_headers=gql_headers)
    require_health(health)
    ensure_qdrant_collection(urls["qdrant"], env, qdrant_collection)

    count_before = request_json(f"{urls['qdrant']}/collections/{qdrant_collection}/points/count", {"exact": True})
    post_response = request_json(f"{urls['synapse']}/webhook/synapse/note", {"path": note_path, "content": note_content}, webhook_headers)
    if post_response.get("status") != "ok" or post_response.get("publisher") != "wikijs":
        raise SystemExit(f"note post failed: {post_response}")

    wiki_path = str(post_response["wiki_path"]).lstrip("/")
    verify_wikijs_page(urls["wikijs"], gql_headers, wiki_path, unique_phrase)

    count_after = request_json(f"{urls['qdrant']}/collections/{qdrant_collection}/points/count", {"exact": True})
    points = scroll_note_points(urls["qdrant"], qdrant_collection, post_response["note_id"])
    consistency = verify_wiki_index_match(urls["wikijs"], gql_headers, wiki_path, post_response["note_id"], points)
    if not points or unique_phrase not in "\n".join(p.get("payload", {}).get("text", "") for p in points):
        raise SystemExit("Qdrant payload does not contain unique phrase")

    rag = request_json(
        f"{urls['synapse']}/webhook/synapse/ask",
        {"question": f"What is the verification codename for {run_id}?", "source_path": note_path},
        webhook_headers,
    )
    if rag.get("insufficient_context") or unique_phrase not in json.dumps(rag, ensure_ascii=False):
        raise SystemExit(f"RAG answer did not prove fresh note: {rag}")

    raw = {
        "verdict": "PASS",
        "run_id": run_id,
        "note_path": note_path,
        "unique_phrase": unique_phrase,
        "health": health,
        "post_response": post_response,
        "qdrant_count_before": count_before,
        "qdrant_count_after": count_after,
        "qdrant_points_for_note": len(points),
        "wiki_index_consistency": consistency,
        "rag": rag,
    }
    write_evidence(raw, env)
    report = f"""# Synapse Local E2E Evidence\n\nVerdict: PASS\nRun ID: {run_id}\nFresh note: {note_path}\nUnique phrase: {unique_phrase}\nWiki path: {post_response['wiki_path']}\nPublisher: {post_response['publisher']}\nIndexed chunks: {post_response['indexed_chunks']}\n\nHealth:\n- Synapse API: {health['synapse']}\n- Wiki.js: {health['wikijs']}\n- Qdrant: {health['qdrant']}\n- Ollama: {health['ollama']}\n\nQdrant:\n- count before: {count_before['result']['count']}\n- count after: {count_after['result']['count']}\n- fresh note points: {len(points)}\n- wiki/index content hash: {consistency['content_hash']}\n\nRAG:\n- insufficient_context: {rag.get('insufficient_context')}\n- answer: {rag.get('answer')}\n- first source: {(rag.get('sources') or [{}])[0].get('source_path')}\n"""
    (EVIDENCE_DIR / "local-e2e-report.md").write_text(redact(report, env), encoding="utf-8")
    print(redact(report, env))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("simple", "complex", "ospf", "ci", "real"), default="simple", help="live proof suite to run")
    args = parser.parse_args(argv)
    env_path = Path(os.environ.get("SYNAPSE_ENV_FILE", str(ENV_FILE)))
    env = load_dotenv(env_path)
    if args.suite == "complex":
        return run_complex_proof(env)
    if args.suite == "ospf":
        return run_ospf_proof(env)
    if args.suite == "ci":
        return run_ci_proof(env)
    if args.suite == "real":
        return run_real_local_stack_proof(env)
    return run_simple_proof(env)


if __name__ == "__main__":
    raise SystemExit(main())
