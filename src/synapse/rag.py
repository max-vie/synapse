"""Typed contracts for source-grounded question answering.

The HTTP and model adapters stay outside these contracts. Callers exchange a
small set of immutable values, which keeps the source-grounded behavior local
to the RAG implementation and its tests.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class Question:
    """A normalized question and its optional retrieval scope."""

    text: str
    filters: Mapping[str, str] = field(default_factory=dict)
    exact_run_id: str = ""

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("question text is required")

    def to_mapping(self) -> dict[str, Any]:
        # The mapping is the compatibility shape consumed by the existing
        # grounding policy. The typed contract stays at the outer seam.
        return {
            "question": self.text,
            "filters": dict(self.filters),
            "exact_run_id": self.exact_run_id,
        }


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieved vector-store result before grounding policy is applied."""

    score: float
    payload: Mapping[str, Any]

    def to_point(self) -> dict[str, Any]:
        return {"score": self.score, "payload": dict(self.payload)}


@dataclass(frozen=True)
class Source:
    """A public-safe source locator and the support quoted from it."""

    title: str = ""
    note_id: str | None = None
    source_path: str | None = None
    wiki_path: str | None = None
    source_url: str | None = None
    score: float | None = None
    chunk_index: int | None = None
    quoted_support: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Source":
        raw_score = value.get("score")
        try:
            score = float(raw_score) if raw_score is not None else None
        except (TypeError, ValueError):
            score = None
        raw_chunk_index = value.get("chunk_index")
        try:
            chunk_index = int(raw_chunk_index) if raw_chunk_index is not None else None
        except (TypeError, ValueError):
            chunk_index = None
        return cls(
            title=str(value.get("title") or ""),
            note_id=str(value["note_id"]) if value.get("note_id") is not None else None,
            source_path=str(value["source_path"])
            if value.get("source_path") is not None
            else None,
            wiki_path=str(value["wiki_path"])
            if value.get("wiki_path") is not None
            else None,
            source_url=str(value["source_url"])
            if value.get("source_url") is not None
            else None,
            score=score,
            chunk_index=chunk_index,
            quoted_support=str(value.get("quoted_support") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "note_id": self.note_id,
            "source_path": self.source_path,
            "wiki_path": self.wiki_path,
            "source_url": self.source_url,
            "score": self.score,
            "chunk_index": self.chunk_index,
            "quoted_support": self.quoted_support,
        }


@dataclass(frozen=True)
class AnswerResult:
    """The stable result shape shared by the HTTP service and Ask client."""

    question: str
    answer: str
    insufficient_context: bool
    sources: tuple[Source, ...] = ()
    retrieval: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "answer": self.answer,
            "insufficient_context": self.insufficient_context,
            "sources": [source.to_dict() for source in self.sources],
            "retrieval": dict(self.retrieval),
        }


class Retriever(Protocol):
    """Port for retrieving candidate chunks for a normalized question.

    Adapters may return broad candidates. Grounding and top-k policy are applied
    after retrieval so callers do not mistake vector similarity for evidence.
    """

    def retrieve(self, question: Question) -> Sequence[RetrievedChunk]: ...


class Generator(Protocol):
    """Port for generating a draft answer from grounded context."""

    def generate(
        self, question: Question, context: str, sources: Sequence[Source]
    ) -> str: ...


class AnswerValidator(Protocol):
    """Port for enforcing citation and source-grounding policy."""

    def validate(
        self,
        question: Question,
        answer: str,
        sources: Sequence[Source],
        retrieval: Mapping[str, Any],
        *,
        insufficient_context: bool = False,
    ) -> AnswerResult: ...


__all__ = [
    "AnswerResult",
    "AnswerValidator",
    "Generator",
    "Question",
    "RetrievedChunk",
    "Retriever",
    "Source",
]
