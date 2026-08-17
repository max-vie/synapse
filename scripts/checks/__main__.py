"""Run Synapse repository checks through one stable interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import docs, images, private, public


def check_repo(root: Path) -> int:
    files = public.candidate_files(root)
    private_findings = private.validate_files(root, files)
    public_findings = public.tracked_env_files(root, files)
    for path in files:
        if public.is_text_candidate(root, path):
            public_findings.extend(public.scan_file(root, path))
    for finding in private_findings:
        print(finding.format(root))
    for finding in public_findings:
        print(finding.format(root))
    if private_findings or public_findings:
        return 1
    print("OK: repository secrets, paths, binds, and public claims are bounded.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    for command in ("repo", "docs", "all"):
        item = subcommands.add_parser(command)
        item.add_argument("root", nargs="?", type=Path, default=Path("."))
    image_parser = subcommands.add_parser("images")
    image_parser.add_argument("--compose-file", type=Path, default=images.ROOT / "docker-compose.e2e.yml")
    image_parser.add_argument("--offline-fixture", action="store_true")
    image_parser.add_argument("--format", choices=("text", "json"), default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "repo":
        return check_repo(args.root.resolve())
    if args.command == "docs":
        return docs.main([str(args.root)])
    if args.command == "images":
        image_args = ["--compose-file", str(args.compose_file), "--format", args.format]
        if args.offline_fixture:
            image_args.append("--offline-fixture")
        return images.main(image_args)
    repo_status = check_repo(args.root.resolve())
    docs_status = docs.main([str(args.root)])
    return 1 if repo_status or docs_status else 0


if __name__ == "__main__":
    raise SystemExit(main())
