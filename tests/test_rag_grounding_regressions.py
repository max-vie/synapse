"""Regression tests for RAG grounding: answer gate, query-term coverage, and metadata safety."""

import sys
from pathlib import Path

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse.ask import answer_or_refuse, build_context  # noqa: E402
from synapse.metadata import build_metadata  # noqa: E402


def run_answer_or_refuse(response, *, sources=None):
    return answer_or_refuse(
        {
            "question": "what algorithm is used in ospf?",
            "insufficient_context": False,
            "sources": sources or [{"source_path": "Synapse-Demo/ospf.md"}, {"source_path": "Synapse-Demo/spf.md"}],
            "retrieval": {"accepted": 2},
        },
        {"response": response},
    )


def run_build_context(question, points, *, filters=None, exact_run_id="", env=None):
    return build_context(
        {"question": question, "filters": filters or {}, "exact_run_id": exact_run_id},
        points,
        env=env or {},
    )


# ── Metadata safety ───────────────────────────────────────────────────


def test_metadata_no_longer_emits_removed_publisher_slug():
    metadata = build_metadata("Demo/My Note.md", "# My Note\n")
    assert "bookstack_slug" not in metadata.to_dict()


# ── Query-term grounding ──────────────────────────────────────────────


def test_build_context_does_not_count_source_path_as_query_term_grounding():
    result = run_build_context(
        "What algorithm is used in VRRP?",
        [
            {
                "score": 0.93,
                "payload": {
                    "title": "Generic algorithm note",
                    "source_path": "Synapse-Demo/vrrp.md",
                    "text": "This note mentions an election algorithm but omits the requested protocol name.",
                    "chunk_index": 0,
                },
            }
        ],
    )

    assert result["insufficient_context"] is True
    assert result["retrieval"]["reason"] == "no_query_term_coverage"


def test_build_context_applies_query_coverage_even_with_source_path_filter():
    missing_terms = run_build_context(
        "What algorithm is used in VRRP?",
        [
            {
                "score": 0.91,
                "payload": {
                    "title": "Filtered note",
                    "source_path": "Synapse-Demo/networking.md",
                    "text": "A generic algorithm note without the requested protocol anchor.",
                    "chunk_index": 0,
                },
            }
        ],
        filters={"source_path": "Synapse-Demo/networking.md"},
    )
    with_terms = run_build_context(
        "What algorithm is used in VRRP?",
        [
            {
                "score": 0.91,
                "payload": {
                    "title": "Filtered note",
                    "source_path": "Synapse-Demo/networking.md",
                    "text": "VRRP uses a priority-based master election algorithm.",
                    "chunk_index": 0,
                },
            }
        ],
        filters={"source_path": "Synapse-Demo/networking.md"},
    )

    assert missing_terms["insufficient_context"] is True
    assert missing_terms["retrieval"]["reason"] == "no_query_term_coverage"
    assert with_terms["insufficient_context"] is False
    assert with_terms["sources"][0]["source_path"] == "Synapse-Demo/networking.md"


# ── Answer gate ────────────────────────────────────────────────────────


def test_answer_gate_accepts_multi_source_citations_without_repair():
    result = run_answer_or_refuse("OSPF uses Dijkstra's Shortest Path First algorithm. [1, 2]")

    assert result["insufficient_context"] is False
    assert result["answer"].endswith("[1, 2]")


def test_answer_gate_rejects_uncited_answers_even_when_sources_exist():
    result = run_answer_or_refuse("OSPF uses Dijkstra's Shortest Path First algorithm.")

    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "missing_valid_citation"


def test_answer_gate_rejects_invalid_or_mixed_citation_numbers():
    invalid_only = run_answer_or_refuse("OSPF uses Dijkstra's Shortest Path First algorithm. [99]")
    mixed = run_answer_or_refuse("OSPF uses Dijkstra's Shortest Path First algorithm. [1, 99]")

    assert invalid_only["insufficient_context"] is True
    assert invalid_only["retrieval"]["refusal_reason"] == "invalid_citation"
    assert mixed["insufficient_context"] is True
    assert mixed["retrieval"]["refusal_reason"] == "invalid_citation"


def test_answer_gate_rejects_out_of_range_citation_before_final_valid_citation():
    result = run_answer_or_refuse("OSPF uses Dijkstra SPF. [99]. The valid source is cited later. [1]", sources=[{"source_path": "Synapse-Demo/ospf.md"}])

    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "invalid_citation"


def test_answer_gate_rejects_citations_to_sources_without_locator():
    result = run_answer_or_refuse("OSPF uses Dijkstra's Shortest Path First algorithm. [1]", sources=[{"title": "OSPF"}])

    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "invalid_source_locator"


def test_answer_gate_treats_cited_refusal_as_insufficient_context():
    result = run_answer_or_refuse("I do not have enough indexed note context to answer that reliably. [1]")

    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "empty_or_refused_answer"


def test_answer_gate_treats_cited_refusal_without_period_as_insufficient_context():
    result = run_answer_or_refuse("I do not have enough indexed note context to answer that reliably [1]")

    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "empty_or_refused_answer"


def test_answer_gate_treats_refusal_with_citation_then_period_as_insufficient_context():
    result = run_answer_or_refuse("I do not have enough indexed note context to answer that reliably. [1].")

    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "empty_or_refused_answer"


def test_answer_gate_does_not_treat_inline_numeric_brackets_as_citations():
    inline = run_answer_or_refuse("The configured tag is VLAN[1].")
    rfc = run_answer_or_refuse("The note references RFC [2328]. OSPF uses Dijkstra SPF. [1]", sources=[{"source_path": "Synapse-Demo/ospf.md"}])

    assert inline["insufficient_context"] is True
    assert inline["retrieval"]["refusal_reason"] == "missing_valid_citation"
    assert rfc["insufficient_context"] is False
    assert rfc["answer"].endswith("[1]")