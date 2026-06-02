"""HTTP client and live/dry-run Ask dispatch."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from .dry_run import dry_run
from .formatting import MISSING_WEBHOOK_MESSAGE


class SynapseHTTPError(RuntimeError):
    """Sanitised HTTP error from the Synapse webhook.

    Default ``str()`` shows a concise message like
    ``"HTTP 401 from Synapse webhook"`` with no upstream body, URL, or
    token-like values.

    When ``debug`` is True, ``str()`` includes the status code, URL, and
    a truncated response body for diagnosis.
    """

    def __init__(
        self,
        status_code: int,
        url: str,
        body: str,
        *,
        debug: bool = False,
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.body = body
        self.debug = debug
        # Store both forms so tests can assert either surface.
        self._concise = f"HTTP {status_code} from Synapse webhook"
        self._verbose = _sanitize_message(f"HTTP {status_code} from {url}: {body[:512]}")
        super().__init__(self._verbose if debug else self._concise)

    def __str__(self) -> str:
        return self._verbose if self.debug else self._concise


# Token-like patterns to strip from non-debug error messages.
_TOKEN_PATTERN = re.compile(
    r"(_token=|token=|X-Synapse-Token[=: ]+|X-synapse-token[=: ]+|Bearer )"
    r"\S+",
    re.IGNORECASE,
)


def _sanitize_message(msg: str) -> str:
    """Redact token-like patterns from *msg* unless it looks intentionally detailed."""
    return _TOKEN_PATTERN.sub(r"\1<redacted>", msg)


def _is_debug() -> bool:
    """Return True when debug mode is enabled via env var."""
    return os.getenv("SYNAPSE_ASK_DEBUG", "").lower() in {"1", "true", "yes"}


def auth_headers(auth_token: str | None = None) -> dict[str, str]:
    # The lab webhook uses one shared header. Build it here so token handling
    # stays boring and, more importantly, never gets printed by mistake.
    token = auth_token if auth_token is not None else os.getenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", "")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Synapse-Token"] = token
    return headers


def post_json(
    url: str,
    payload: dict[str, object],
    timeout: int = 60,
    auth_token: str | None = None,
    *,
    debug: bool | None = None,
) -> dict[str, object]:
    # urllib is clunky, but it keeps Ask dependency-free for fresh clones and
    # the explicit no-network dry-run path.
    if debug is None:
        debug = _is_debug()
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=auth_headers(auth_token),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SynapseHTTPError(exc.code, url, body, debug=debug) from exc


def notes_url_from_ask_webhook(webhook_url: str) -> str:
    """Derive the indexed-notes endpoint from the configured Ask endpoint."""
    cleaned = webhook_url.rstrip("/")
    if cleaned.endswith("/webhook/synapse/ask"):
        return cleaned[: -len("/webhook/synapse/ask")] + "/webhook/synapse/notes"
    if cleaned.endswith("/ask"):
        return cleaned[: -len("/ask")] + "/notes"
    return cleaned + "/notes"


def list_indexed_notes(
    webhook_url: str,
    query: str = "",
    timeout: int = 60,
    auth_token: str | None = None,
    *,
    debug: bool | None = None,
) -> list[dict[str, object]]:
    """Return indexed Markdown note sources from the live Synapse service."""
    if not webhook_url:
        raise RuntimeError(MISSING_WEBHOOK_MESSAGE)
    payload: dict[str, object] = {}
    if query:
        payload["query"] = query
    response = post_json(notes_url_from_ask_webhook(webhook_url), payload, timeout=timeout, auth_token=auth_token, debug=debug)
    notes = response.get("notes")
    return [note for note in notes if isinstance(note, dict)] if isinstance(notes, list) else []


def build_live_payload(
    question: str,
    source_path: str = "",
    note_id: str = "",
    wiki_path: str = "",
    exact_run_id: str = "",
) -> dict[str, object]:
    # Keep the base request tiny, then add optional filters. The proof scripts
    # use these filters to pin a question to a specific canary note/run.
    payload: dict[str, object] = {"question": question}
    if source_path:
        payload["source_path"] = source_path
    if note_id:
        payload["note_id"] = note_id
    if wiki_path:
        payload["wiki_path"] = wiki_path
    if exact_run_id:
        payload["exact_run_id"] = exact_run_id
    return payload


def ask_question(
    question: str,
    webhook_url: str,
    note_path: Path | None,
    timeout: int,
    auth_token: str,
    source_path: str = "",
    note_id: str = "",
    wiki_path: str = "",
    exact_run_id: str = "",
    dry_run_enabled: bool = False,
    *,
    debug: bool | None = None,
) -> dict[str, object]:
    # Ask should fail closed by default. If the app quietly falls back to a dry
    # run, a live demo can look successful while never touching the RAG workflow.
    if dry_run_enabled:
        return dry_run(question, note_path)
    if webhook_url:
        payload = build_live_payload(question, source_path, note_id, wiki_path, exact_run_id)
        return post_json(webhook_url, payload, timeout=timeout, auth_token=auth_token, debug=debug)
    raise RuntimeError(MISSING_WEBHOOK_MESSAGE)