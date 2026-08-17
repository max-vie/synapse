"""Tiny deterministic Ollama-compatible mock for CI service proof."""
from __future__ import annotations

import argparse
import json
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

VECTOR_SIZE = 8
CODENAME_RE = re.compile(r"\bsynapse-ci-proof-[a-z0-9-]+\b", re.IGNORECASE)


def deterministic_vector(text: str, size: int = VECTOR_SIZE) -> list[float]:
    """Return a stable non-zero vector without external model downloads."""
    _ = text
    return [1.0] + [0.0] * (size - 1)


def read_message_text(payload: dict[str, Any]) -> str:
    messages = payload.get("messages") or []
    return "\n".join(str(message.get("content", "")) for message in messages if isinstance(message, dict))


def chat_response(payload: dict[str, Any]) -> str:
    prompt = read_message_text(payload)
    match = CODENAME_RE.search(prompt)
    if match:
        codename = match.group(0)
        return f"The Synapse CI e2e verification codename is {codename} [1]."
    return "I do not have enough indexed note context to answer that reliably."


class MockOllamaHandler(BaseHTTPRequestHandler):
    server_version = "synapse-mock-ollama/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, body: dict[str, Any], status: int = 200) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        if self.path == "/api/tags":
            self.send_json({"models": [{"name": "mock-embed"}, {"name": "mock-answer"}]})
            return
        self.send_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP handler API
        payload = self.read_json()
        if self.path == "/api/embed":
            text = payload.get("input", "")
            if isinstance(text, list):
                embeddings = [deterministic_vector(str(item)) for item in text]
            else:
                embeddings = [deterministic_vector(str(text))]
            self.send_json({"embeddings": embeddings, "embedding": embeddings[0]})
            return
        if self.path == "/api/chat":
            content = chat_response(payload)
            self.send_json({"message": {"role": "assistant", "content": content}, "response": content})
            return
        self.send_json({"error": "not found"}, status=404)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11435)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), MockOllamaHandler)
    print(f"mock Ollama listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
