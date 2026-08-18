"""Application interface for ingest, retrieval, and indexed-note listing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .ask import ask, list_indexed_notes
from .http_client import request_json
from .ingest import ingest
from .settings import Settings


class JsonTransport(Protocol):
    """Port for external JSON-over-HTTP dependencies."""

    def request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]: ...


class StdlibJsonAdapter:
    """Production adapter for Ollama, Qdrant, and Wiki.js HTTP calls."""

    def __init__(self, timeout_seconds: float | None = None) -> None:
        self.timeout_seconds = timeout_seconds

    def request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        # Bind the timeout when the runtime is built. Request handling should
        # not silently change because another caller mutates process env.
        return request_json(method, url, payload, headers, timeout=self.timeout_seconds)


@dataclass(frozen=True)
class SynapseRuntime:
    """Deep module exposing the three operations used by the HTTP layer."""

    settings: Settings
    transport: JsonTransport

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> "SynapseRuntime":
        settings = Settings.from_env(values)
        timeout_seconds = float(settings.integer("SYNAPSE_HTTP_TIMEOUT_SECONDS", 180, minimum=1))
        # The runtime owns settings and transport together, so the HTTP seam
        # cannot accidentally use a different timeout source.
        return cls(settings, StdlibJsonAdapter(timeout_seconds))

    def ingest_note(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return ingest(payload, env=self.settings, request_json=self.transport.request)

    def answer_question(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return ask(payload, env=self.settings, request_json=self.transport.request)

    def indexed_notes(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return list_indexed_notes(payload, env=self.settings, request_json=self.transport.request)
