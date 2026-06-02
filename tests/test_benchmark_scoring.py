from scripts.benchmark.scoring import (
    detect_forbidden,
    detect_redaction_expansion,
    detect_required,
    detect_secret_invention,
    is_insufficient_answer,
    score_answer,
)


def test_required_and_forbidden_detection():
    text = "Current codename ORCHID-17A uses synapse_benchmark_notes."
    found, missing = detect_required(text, ["ORCHID-17A", "synapse_benchmark_notes", "missing fact"])
    assert found == ["ORCHID-17A", "synapse_benchmark_notes"]
    assert missing == ["missing fact"]
    assert detect_forbidden(text, ["ORCH1D-17A", "synapse_benchmark_notes"]) == ["synapse_benchmark_notes"]


def test_score_answer_passes_expected_facts():
    result = score_answer(
        "The current codename is ORCHID-17A and the collection is synapse_benchmark_notes.",
        {
            "required_facts": ["ORCHID-17A", "synapse_benchmark_notes"],
            "forbidden_facts": ["ORCH1D-17A", "synapse_notes_old"],
        },
    )
    assert result.passed
    assert result.score == 100


def test_score_answer_fails_forbidden_and_missing():
    result = score_answer(
        "The old codename is ORCH1D-17A.",
        {"required_facts": ["ORCHID-17A"], "forbidden_facts": ["ORCH1D-17A"]},
    )
    assert not result.passed
    assert "ORCHID-17A" in result.required_missing
    assert "ORCH1D-17A" in result.forbidden_found


def test_wrong_source_path_detected_when_required():
    result = score_answer(
        "Answer cites scripts/benchmark/fixtures/notes/stale-plan-distractor.md",
        {
            "required_facts": ["Answer"],
            "forbidden_facts": [],
            "expected_sources": ["scripts/benchmark/fixtures/notes/newer-evidence-report.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )
    assert not result.passed
    assert result.source_errors


def test_source_scoring_requires_valid_inline_citation_number():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [99]", "sources": [{"source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "invalid source citation(s): 99" in result.source_errors


def test_source_scoring_accepts_expected_source_at_second_returned_index():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [2]", "sources": [{"source_path": "Synapse-Demo/distractor.md"}, {"source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert result.passed


def test_source_scoring_fails_when_no_sources_returned_even_if_answer_mentions_path():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF from Synapse-Demo/ospf.md. [1]", "sources": []}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "invalid source citation(s): 1" in result.source_errors


def test_source_scoring_requires_requested_number_of_cited_sources():
    result = score_answer(
        '{"answer": "OSPF and BGP facts are present. [1]", "sources": [{"source_path": "Synapse-Demo/ospf.md"}, {"source_path": "Synapse-Demo/bgp.md"}]}',
        {
            "required_facts": ["OSPF", "BGP"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md", "Synapse-Demo/bgp.md"],
            "required_source_count": 2,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 2 cited source(s), found 1" in result.source_errors


def test_source_scoring_does_not_count_expected_path_mentioned_in_answer_as_returned_source():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF from Synapse-Demo/ospf.md. [1]", "sources": [{"source_path": "Synapse-Demo/distractor.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 1 source(s), found 0" in result.source_errors


def test_source_scoring_requires_exact_source_path_not_substring():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [1]", "sources": [{"source_path": "Synapse-Demo/ospf.md.bak"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 1 source(s), found 0" in result.source_errors


def test_source_scoring_requires_match_in_source_path_not_title_metadata():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [1]", "sources": [{"title": "mentions Synapse-Demo/ospf.md", "source_path": "Synapse-Demo/stale.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "expected at least 1 source(s), found 0" in result.source_errors


def test_source_scoring_ignores_numeric_brackets_in_source_metadata():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [1]", "sources": [{"title": "OSPF note [99]", "source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert result.passed


def test_source_scoring_rejects_out_of_range_citation_before_final_citation():
    result = score_answer(
        '{"answer": "OSPF uses Dijkstra SPF. [99]. The valid source is cited later. [1]", "sources": [{"source_path": "Synapse-Demo/ospf.md"}]}',
        {
            "required_facts": ["Dijkstra SPF"],
            "forbidden_facts": [],
            "expected_sources": ["Synapse-Demo/ospf.md"],
            "required_source_count": 1,
        },
        require_sources=True,
    )

    assert not result.passed
    assert "invalid source citation(s): 99" in result.source_errors


def test_unsupported_answer_behavior():
    result = score_answer(
        "Insufficient context. The notes do not provide a private lab password.",
        {"type": "unsupported", "required_facts": ["Insufficient context"], "forbidden_facts": ["hunter2", "password is"]},
    )
    assert result.passed
    assert is_insufficient_answer(result.required_found[0])


def test_secret_and_redaction_detection():
    assert detect_secret_invention("The API key is sk-live-1234567890")
    assert detect_secret_invention("password is hunter2")
    assert detect_redaction_expansion("expanded redaction: abc123")
