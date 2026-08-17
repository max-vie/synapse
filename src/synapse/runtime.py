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

    def request(
        self,
        method: str,
        url: str,
        payload: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        return request_json(method, url, payload, headers)


@dataclass(frozen=True)
class SynapseRuntime:
    """Deep module exposing the three operations used by the HTTP layer."""

    settings: Settings
    transport: JsonTransport

    @classmethod
    def from_env(cls, values: Mapping[str, str] | None = None) -> "SynapseRuntime":
        return cls(Settings.from_env(values), StdlibJsonAdapter())

    def ingest_note(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return ingest(payload, env=self.settings, request_json=self.transport.request)

    def answer_question(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return ask(payload, env=self.settings, request_json=self.transport.request)

    def indexed_notes(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return list_indexed_notes(payload, env=self.settings, request_json=self.transport.request)
