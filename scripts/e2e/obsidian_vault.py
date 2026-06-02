#!/usr/bin/env python3
"""Small filesystem-first Obsidian helper for Synapse E2E.

This is intentionally not tied to the Obsidian desktop app. It treats a vault as
plain Markdown files, which is exactly how Obsidian stores notes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

DEFAULT_NOTE = "Synapse-Demo/example-study-notes.md"
DEMO_CONTENT = """# Example Study Notes

This single example Obsidian note gives Synapse one realistic study page with mixed networking and project facts. It is intentionally public-safe lab content.

## Networking basics

- OSPF stands for Open Shortest Path First.
- OSPF is a link-state routing protocol that routers use to share network topology and choose routes inside an autonomous system.
- OSPF uses Dijkstra's Shortest Path First (SPF) algorithm.
- Dijkstra's SPF calculation builds a shortest-path tree so each router can choose the best next hop.
- An IP address is a numeric label assigned to a device interface so packets can be routed to and from that device.
- IPv4 addresses look like `192.0.2.10`; IPv6 addresses look like `2001:db8::10`.
- A subnet groups IP addresses into the same network range.
- DNS maps human-readable names to IP addresses.
- A default gateway is the router a host uses to reach networks outside its local subnet.

## Synapse facts

- Project name: Synapse.
- Primary publisher: Wiki.js.
- Vector database: Qdrant.
- Local model runtime: Ollama.
- RAG behavior: answer only from retrieved context and say when context is insufficient.

"""


def vault_path(raw: str | None) -> Path:
    raw = raw or os.getenv("OBSIDIAN_VAULT_PATH") or "examples/obsidian-vault"
    return Path(raw).expanduser().resolve()


def note_path(vault: Path, rel: str) -> Path:
    rel_path = Path(rel)
    if rel_path.is_absolute() or ".." in rel_path.parts:
        raise SystemExit("note path must be vault-relative and must not contain '..'")
    return vault / rel_path


def write_demo(args: argparse.Namespace) -> int:
    vault = vault_path(args.vault)
    path = note_path(vault, args.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not args.force:
        print(path)
        return 0
    path.write_text(DEMO_CONTENT, encoding="utf-8")
    print(path)
    return 0


def append_marker(args: argparse.Namespace) -> int:
    vault = vault_path(args.vault)
    path = note_path(vault, args.path)
    if not path.exists():
        raise SystemExit(f"missing note: {path}")
    marker = args.marker or f"E2E marker: update {int(time.time())}."
    with path.open("a", encoding="utf-8") as f:
        f.write("\n" + marker + "\n")
    print(marker)
    return 0


def read_note(args: argparse.Namespace) -> int:
    vault = vault_path(args.vault)
    path = note_path(vault, args.path)
    if not path.exists():
        raise SystemExit(f"missing note: {path}")
    payload = {"path": args.path, "content": path.read_text(encoding="utf-8")}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(payload["content"])
    return 0


def post_note(args: argparse.Namespace) -> int:
    vault = vault_path(args.vault)
    path = note_path(vault, args.path)
    if not path.exists():
        raise SystemExit(f"missing note: {path}")
    webhook = args.webhook or os.getenv("SYNAPSE_NOTE_WEBHOOK_URL")
    if not webhook:
        raise SystemExit("missing webhook; set SYNAPSE_NOTE_WEBHOOK_URL or pass --webhook")
    payload = {"path": args.path, "content": path.read_text(encoding="utf-8")}
    headers = {"Content-Type": "application/json"}
    token = getattr(args, "auth_token", None) if getattr(args, "auth_token", None) is not None else os.getenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", "")
    if token:
        headers["X-Synapse-Token"] = token
    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=args.timeout) as response:
        print(response.read().decode("utf-8"))
    return 0


def watch(args: argparse.Namespace) -> int:
    vault = vault_path(args.vault)
    path = note_path(vault, args.path)
    if not path.exists():
        raise SystemExit(f"missing note: {path}")
    last = None
    print(f"Watching {path}")
    while True:
        mtime = path.stat().st_mtime
        if last is None:
            last = mtime
        elif mtime != last:
            last = mtime
            post_note(args)
        time.sleep(args.interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", help="Obsidian vault path; defaults to OBSIDIAN_VAULT_PATH or examples/obsidian-vault")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("write-demo")
    p.add_argument("--path", default=DEFAULT_NOTE)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=write_demo)

    p = sub.add_parser("append-marker")
    p.add_argument("--path", default=DEFAULT_NOTE)
    p.add_argument("--marker")
    p.set_defaults(func=append_marker)

    p = sub.add_parser("read-note")
    p.add_argument("--path", default=DEFAULT_NOTE)
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=read_note)

    p = sub.add_parser("post-note")
    p.add_argument("--path", default=DEFAULT_NOTE)
    p.add_argument("--webhook")
    p.add_argument("--auth-token", default=os.getenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", ""))
    p.add_argument("--timeout", type=int, default=180)
    p.set_defaults(func=post_note)

    p = sub.add_parser("watch")
    p.add_argument("--path", default=DEFAULT_NOTE)
    p.add_argument("--webhook")
    p.add_argument("--auth-token", default=os.getenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", ""))
    p.add_argument("--timeout", type=int, default=180)
    p.add_argument("--interval", type=float, default=2.0)
    p.set_defaults(func=watch)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
