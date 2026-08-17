"""Run the curated optional Synapse model benchmark."""

from __future__ import annotations

import argparse

from . import ollama_models, workflow_top_models


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    models = subcommands.add_parser("models", help="list curated model candidates")
    models.add_argument("--models")
    models.add_argument("--max-params")
    run = subcommands.add_parser("run", help="run the standard smoke, format, and extraction suite")
    run.add_argument("--models")
    run.add_argument("--max-params")
    run.add_argument("--skip-pull", action="store_true")
    workflow = subcommands.add_parser("workflow", help="run the live application proof for selected models")
    workflow.add_argument("--models")
    workflow.add_argument("--limit", type=int, default=5)
    workflow.add_argument("--max-params", type=float, default=48.0)
    workflow.add_argument("--proof-suite", choices=("simple", "complex"), default="simple")
    workflow.add_argument("--skip-pull", action="store_true")
    subcommands.add_parser("report", help="render recorded benchmark results")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "models":
        forwarded = ["list"]
        if args.models:
            forwarded.extend(["--models", args.models])
        if args.max_params:
            forwarded.extend(["--max-params", args.max_params])
        return ollama_models.main(forwarded)
    if args.command == "run":
        forwarded = ["suite"]
        if args.models:
            forwarded.extend(["--models", args.models])
        if args.max_params:
            forwarded.extend(["--max-params", args.max_params])
        if args.skip_pull:
            forwarded.append("--skip-pull")
        return ollama_models.main(forwarded)
    if args.command == "workflow":
        forwarded = ["--limit", str(args.limit), "--max-params", str(args.max_params), "--proof-suite", args.proof_suite]
        if args.models:
            forwarded.extend(["--models", args.models])
        if args.skip_pull:
            forwarded.append("--skip-pull")
        return workflow_top_models.main(forwarded)
    return ollama_models.main(["report"])


if __name__ == "__main__":
    raise SystemExit(main())
