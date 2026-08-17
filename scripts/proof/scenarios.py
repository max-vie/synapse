"""Public-safe proof scenario definitions."""

from __future__ import annotations

from typing import Any

COMPLEX_SUITE_ID = "synapse-live-complex-v1"
REAL_LOCAL_STACK_SUITE_ID = "synapse-real-local-stack-v1"
OSPF_SUITE_ID = "synapse-live-ospf-v1"
PROOF_NOTE_DIR = "Synapse-Demo/generated-proof-notes"


def proof_note_path(filename: str) -> str:
    return f"{PROOF_NOTE_DIR}/{filename.lstrip('/')}"


def build_complex_suite(run_id: str, nonce: str) -> dict[str, Any]:
    """Return a public-safe adversarial live workflow suite spec."""
    current_codename = f"complex-codename-{nonce}"
    stale_codename = f"stale-codename-{nonce}"
    queue_name = f"complex-queue-{nonce}"
    incident_id = f"CX-{nonce.upper()}-42"
    exact_command = "python3 -m scripts.benchmark workflow --proof-suite complex --models gemma3:27b,qwen2.5-coder:14b,qwen2.5-coder:3b,qwen3.6:27b --skip-pull"
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
