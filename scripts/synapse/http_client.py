"""Small stdlib JSON HTTP helpers for the Synapse service."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .upstream import UpstreamError


def default_timeout_seconds() -> float:
    try:
        return max(1.0, float(os.environ.get("SYNAPSE_HTTP_TIMEOUT_SECONDS", "60")))
    except ValueError:
        return 60.0


def _upstream_code_from_url(url: str) -> str:
    """Derive a stable generic error_code from the upstream URL path."""
    lower = url.lower()
    if "qdrant" in lower:
        return "upstream_qdrant_error"
    if "ollama" in lower:
        return "upstream_ollama_error"
    if "wikijs" in lower or "graphql" in lower:
        return "upstream_wikijs_error"
    return "upstream_service_error"


def request_json(method: str, url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    timeout = default_timeout_seconds() if timeout is None else timeout
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - local lab URLs are configured by the operator.
            raw = response.read().decode("utf-8")
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise UpstreamError(
            _upstream_code_from_url(url),
            f"{method} {url} failed with HTTP {error.code}: {detail}",
        ) from error
    except URLError as error:
        raise UpstreamError(
            _upstream_code_from_url(url),
            f"{method} {url} connection failed: {error.reason}",
        ) from error
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise UpstreamError(
            "upstream_unexpected_response",
            f"{method} {url} returned non-object JSON",
        )
    return parsed


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None, timeout: float | None = None) -> dict[str, Any]:
    return request_json("POST", url, payload, headers, timeout)