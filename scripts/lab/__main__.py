"""Single command for the Synapse local-lab lifecycle."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .runtime import Lab, LabError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=Path(os.environ.get("SYNAPSE_ENV_FILE", ".env")))
    subcommands = parser.add_subparsers(dest="command", required=True)
    init = subcommands.add_parser("init", help="create the private .env file")
    init.add_argument("--force", action="store_true")
    subcommands.add_parser("up", help="start and prepare the local lab")
    subcommands.add_parser("configure", help="verify Wiki.js API configuration")
    subcommands.add_parser("start-service", help="build and start the Synapse service")
    proof = subcommands.add_parser("proof", help="run a live proof suite")
    proof.add_argument("--suite", choices=("simple", "complex", "ospf"), default="simple")
    subcommands.add_parser("mocked-proof", help="run the isolated mocked proof")
    subcommands.add_parser("real-proof", help="run the stronger configured real-stack proof")
    subcommands.add_parser("status", help="show container and HTTP status")
    logs = subcommands.add_parser("logs", help="show Compose logs")
    logs.add_argument("services", nargs="*")
    subcommands.add_parser("down", help="stop the lab and preserve volumes")
    remove = subcommands.add_parser("remove", help="delete containers, volumes, env, and artifacts")
    remove.add_argument("--yes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    lab = Lab(env_path=args.env_file)
    try:
        if args.command == "init":
            lab.initialize(force=args.force)
        elif args.command == "up":
            lab.up()
        elif args.command == "configure":
            lab.configure()
        elif args.command == "start-service":
            lab.start_service()
        elif args.command == "proof":
            lab.proof(args.suite)
        elif args.command == "mocked-proof":
            lab.mocked_proof()
        elif args.command == "real-proof":
            lab.real_proof()
        elif args.command == "status":
            return lab.status()
        elif args.command == "logs":
            lab.logs(args.services)
        elif args.command == "down":
            lab.down()
        elif args.command == "remove":
            lab.remove(yes=args.yes)
    except LabError as exc:
        print(f"[FAIL] {exc}", file=__import__("sys").stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
