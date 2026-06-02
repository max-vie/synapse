#!/usr/bin/env python3
"""Audit requested Ollama family/parameter coverage against the matrix and raw suite runs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import request

import yaml

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.benchmark.constants import (  # noqa: E402
    DEFAULT_OUTPUT_DIR,
    FAMILY_COVERAGE_REPORT_PATH,
    MATRIX_PATH,
    REQUESTED_FAMILY_PARAMS_PATH,
    ROOT,
    STANDARD_SUITE_ID,
    is_public_benchmark_model,
)

REQUESTED_PATH = REQUESTED_FAMILY_PARAMS_PATH
DEFAULT_REPORT_PATH = FAMILY_COVERAGE_REPORT_PATH


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_env() -> dict[str, str]:
    env_path = ROOT / ".env"
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"\'')
    return env


def requested_aliases(spec: dict[str, Any]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for family in (spec.get("families") or {}).values():
        tags = [str(tag) for tag in family.get("canonical_tags") or []]
        for tag in tags:
            aliases[tag] = tag
            if tag.endswith(":latest"):
                aliases[tag.removesuffix(":latest")] = tag
        for alias in family.get("aliases") or []:
            if tags:
                aliases[str(alias)] = tags[-1]
    return aliases


def normalize(name: str, aliases: dict[str, str]) -> str:
    if name in aliases:
        return aliases[name]
    if ":" not in name and f"{name}:latest" in aliases:
        return f"{name}:latest"
    return name


def load_matrix_names() -> set[str]:
    return {str(model.get("name")) for model in load_yaml(MATRIX_PATH).get("models", []) if model.get("name")}


def suite_result_status(item: dict[str, Any]) -> dict[str, Any]:
    suite = item.get("suite") or {}
    questions = item.get("questions") or []
    ok_count = sum(1 for q in questions if q.get("ok"))
    empty_count = sum(1 for q in questions if not q.get("answer"))
    unavailable = bool(questions and ok_count == 0 and empty_count == len(questions))
    return {
        "suite_id": suite.get("suite_id"),
        "workflow": suite.get("score"),
        "strict_pass": bool(suite.get("passed")),
        "unavailable": unavailable,
        "extract_ok": ok_count,
        "extract_count": len(questions),
    }


def load_suite_results(output_dir: Path, aliases: dict[str, str]) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    if not output_dir.exists():
        return results
    for path in sorted(output_dir.glob("*-suite.json"), key=lambda p: p.stat().st_mtime):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entries = (run.get("results") or {}).get("models") or []
        for item in entries:
            raw_name = item.get("model") or item.get("name")
            if not raw_name:
                continue
            name = normalize(str(raw_name), aliases)
            status = suite_result_status(item)
            status["file"] = str(path.relative_to(ROOT))
            status["timestamp"] = run.get("timestamp_utc")
            results[name] = status
    return results


def query_tags(url: str, *, api_key: str | None = None, timeout: int = 20) -> set[str]:
    headers = {"User-Agent": "Synapse-Benchmark/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url.rstrip("/") + "/api/tags", headers=headers, method="GET")
    with request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return {str(item.get("name")) for item in data.get("models", []) if item.get("name")}


def build_audit(args: argparse.Namespace) -> dict[str, Any]:
    spec = load_yaml(REQUESTED_PATH)
    aliases = requested_aliases(spec)
    matrix_names = load_matrix_names()
    results = load_suite_results(Path(args.output_dir), aliases)
    env = load_env()

    local_tags: set[str] = set()
    cloud_tags: set[str] = set()
    network_errors: dict[str, str] = {}
    if not args.no_network:
        if args.local_host:
            try:
                local_tags = {normalize(name, aliases) for name in query_tags(args.local_host)}
            except Exception as exc:  # noqa: BLE001 - audit must continue
                network_errors["local"] = f"{type(exc).__name__}: {exc}"
        cloud_key = os.environ.get("OLLAMA_API_KEY") or os.environ.get("OLLAMA_CLOUD_API") or env.get("OLLAMA_API_KEY") or env.get("OLLAMA_CLOUD_API")
        if cloud_key:
            try:
                cloud_tags = {normalize(name, aliases) for name in query_tags(args.cloud_host, api_key=cloud_key)}
            except Exception as exc:  # noqa: BLE001 - audit must continue
                network_errors["cloud"] = f"{type(exc).__name__}: {exc}"

    families: dict[str, Any] = {}
    all_tags: list[str] = []
    for family_name, family in (spec.get("families") or {}).items():
        tags = [str(tag) for tag in family.get("canonical_tags") or []]
        all_tags.extend(tags)
        rows = []
        for tag in tags:
            status = results.get(tag)
            rows.append(
                {
                    "tag": tag,
                    "in_matrix": tag in matrix_names,
                    "local_installed": tag in local_tags,
                    "cloud_available": tag in cloud_tags,
                    "suite_attempted": bool(status and status.get("suite_id") == STANDARD_SUITE_ID),
                    "benchmarked": bool(status and status.get("suite_id") == STANDARD_SUITE_ID and not status.get("unavailable")),
                    "unavailable_attempt": bool(status and status.get("unavailable")),
                    "workflow": status.get("workflow") if status else None,
                    "strict_pass": status.get("strict_pass") if status else None,
                    "result_file": status.get("file") if status else None,
                }
            )
        families[family_name] = rows

    flat = [row for rows in families.values() for row in rows]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": spec.get("scope"),
        "notes": spec.get("notes") or [],
        "counts": {
            "families": len(families),
            "requested_tags": len(all_tags),
            "in_matrix": sum(1 for row in flat if row["in_matrix"]),
            "suite_attempted": sum(1 for row in flat if row["suite_attempted"]),
            "benchmarked": sum(1 for row in flat if row["benchmarked"]),
            "unavailable_attempts": sum(1 for row in flat if row["unavailable_attempt"]),
            "local_installed": sum(1 for row in flat if row["local_installed"]),
            "cloud_available": sum(1 for row in flat if row["cloud_available"]),
        },
        "network_errors": network_errors,
        "families": families,
    }


def public_display_families(
    audit: dict[str, Any]
) -> tuple[dict[str, list[dict[str, Any]]], int]:
    display_families: dict[str, list[dict[str, Any]]] = {}
    omitted = 0
    for family, rows in audit["families"].items():
        display_rows = [
            row
            for row in rows
            if row["benchmarked"] and is_public_benchmark_model(str(row["tag"]))
        ]
        omitted += len(rows) - len(display_rows)
        if display_rows:
            display_families[family] = display_rows
    return display_families, omitted


def render_markdown(audit: dict[str, Any]) -> str:
    display_families, omitted = public_display_families(audit)
    published_count = sum(len(rows) for rows in display_families.values())
    lines = [
        "# Text model family coverage",
        "",
        f"Generated: `{audit['generated_at']}`",
        "",
        (
            "Scope: this is only the text-model coverage that has benchmark evidence. "
            "Unavailable pulls, untested tags, vision/OCR tracks, and old baselines stay in raw/internal artifacts."
        ),
        "",
        "## Coverage summary",
        "",
        f"- published_families: `{len(display_families)}`",
        f"- published_benchmarked_tags: `{published_count}`",
        f"- omitted_internal_or_unpublished_tags: `{omitted}`",
    ]
    if audit.get("network_errors"):
        lines.append("- network_errors: present; see raw audit output")
    lines.extend(["", "## Families covered", ""])
    for family, rows in display_families.items():
        lines.append(f"### {family}")
        for row in rows:
            lines.append(
                f"- `{row['tag']}`: benchmarked workflow={row['workflow']}; "
                f"matrix={row['in_matrix']}"
            )
        lines.append("")
    lines.extend(
        [
            "## Coverage notes",
            "",
            "- `benchmarked` means a standard `synapse-standard-v1` suite exists and was not an all-empty unavailable attempt.",
            "- This coverage intentionally omits untested or unavailable tags, vision/OCR tracks, and deprecated local baselines.",
            "- Local/cloud availability is only a point-in-time catalog check. It is not promotion evidence.",
        ]
    )
    return "\n".join(lines) + "\n"


SECTION_START = "<!-- BENCHMARK_FAMILY_COVERAGE_START -->"
SECTION_END = "<!-- BENCHMARK_FAMILY_COVERAGE_END -->"


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


def replace_marked_section(document: str, replacement: str) -> str:
    start = document.find(SECTION_START)
    end = document.find(SECTION_END)
    if start == -1 or end == -1 or end < start:
        return replacement
    end += len(SECTION_END)
    return (
        document[: start + len(SECTION_START)]
        + "\n"
        + replacement.rstrip()
        + "\n"
        + SECTION_END
        + document[end:]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--write-markdown", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-matrix", action="store_true")
    parser.add_argument("--require-benchmarked", action="store_true")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--local-host", default=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"))
    parser.add_argument("--cloud-host", default="https://api.ollama.com")
    args = parser.parse_args()

    audit = build_audit(args)
    display_families, _omitted = public_display_families(audit)
    markdown = render_markdown(audit)
    if args.write_markdown:
        output_path = Path(args.write_markdown)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            existing = output_path.read_text(encoding="utf-8")
            if not display_families and SECTION_START in existing and SECTION_END in existing:
                pass
            elif SECTION_START in existing and SECTION_END in existing:
                output_path.write_text(replace_marked_section(existing, demote_markdown_headings(markdown)), encoding="utf-8")
            else:
                output_path.write_text(markdown, encoding="utf-8")
        else:
            output_path.write_text(markdown, encoding="utf-8")
    if args.json:
        print(json.dumps(audit, indent=2, sort_keys=True))
    else:
        print(markdown)

    rows = [row for family_rows in audit["families"].values() for row in family_rows]
    if args.require_matrix and any(not row["in_matrix"] for row in rows):
        return 1
    if args.require_benchmarked and any(not row["benchmarked"] for row in rows):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
