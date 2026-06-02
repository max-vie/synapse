from synapse.ask import (
    INSUFFICIENT_ANSWER,
    _contains_term,
    _extractive_answer_valid,
    _ngrams,
    _normalize,
    _quote_overlap,
    _term_groups,
    answer_or_refuse,
    ask,
    build_context,
    build_qdrant_filter,
    extractive_answer,
    list_indexed_notes,
    parse_question,
)


def test_parse_question_normalizes_filters_and_e2e_run_ids():
    result = parse_question(
        {
            "question": "what did run e2e-ospf-20260101T000000Z prove?",
            "source_path": " Synapse-Demo\\ospf.md ",
            "wiki_path": " synapse-demo/ospf ",
            "note_id": " note-123 ",
        }
    )

    assert result["filters"] == {
        "note_id": "note-123",
        "source_path": "Synapse-Demo/ospf.md",
        "wiki_path": "/synapse-demo/ospf",
    }
    assert result["exact_run_id"] == "e2e-ospf-20260101T000000Z"


def test_parse_question_rejects_hostile_source_path_filters():
    try:
        parse_question({"question": "what does the note say?", "source_path": "../secret.md"})
    except ValueError as error:
        assert "note path" in str(error)
    else:
        raise AssertionError("expected hostile source path rejection")


def test_parse_question_rejects_questions_above_local_lab_limit():
    try:
        parse_question({"question": "x" * 11}, env={"SYNAPSE_MAX_QUESTION_LENGTH": "10"})
    except ValueError as error:
        assert "question too long" in str(error)
        assert "max_question_length=10" in str(error)
    else:
        raise AssertionError("expected question length rejection")


def test_list_indexed_notes_reads_searchable_qdrant_payloads_and_dedupes():
    calls = []

    def fake_requester(method, url, body, headers=None):
        calls.append((method, url, body, headers))
        assert method == "POST"
        assert url == "http://qdrant:6333/collections/synapse_notes/points/scroll"
        assert body["with_payload"] is True
        return {
            "result": {
                "points": [
                    {
                        "payload": {
                            "source_path": "Synapse-Demo/ospf.md",
                            "title": "OSPF Routing",
                            "note_id": "note-ospf",
                            "wiki_path": "/synapse-demo/ospf",
                        }
                    },
                    {
                        "payload": {
                            "source_path": "Synapse-Demo/ospf.md",
                            "title": "OSPF Routing",
                            "note_id": "note-ospf",
                            "wiki_path": "/synapse-demo/ospf",
                        }
                    },
                    {
                        "payload": {
                            "source_path": "Synapse-Demo/bgp.md",
                            "title": "BGP Routing",
                            "note_id": "note-bgp",
                        }
                    },
                ]
            }
        }

    result = list_indexed_notes(
        {"query": "ospf"},
        env={"QDRANT_BASE_URL": "http://qdrant:6333", "QDRANT_COLLECTION": "synapse_notes"},
        request_json=fake_requester,
    )

    assert result == {
        "notes": [
            {
                "source_path": "Synapse-Demo/ospf.md",
                "title": "OSPF Routing",
                "note_id": "note-ospf",
                "wiki_path": "/synapse-demo/ospf",
            }
        ],
        "count": 1,
    }
    assert calls[0][2].get("offset") is None


def test_list_indexed_notes_follows_qdrant_scroll_offsets():
    calls = []

    def fake_requester(method, url, body, headers=None):
        calls.append(body)
        if len(calls) == 1:
            return {"result": {"points": [], "next_page_offset": "cursor-2"}}
        return {"result": {"points": [{"payload": {"source_path": "Runbook/ospf.md", "title": "OSPF Runbook"}}], "next_page_offset": None}}

    result = list_indexed_notes(
        {},
        env={"QDRANT_BASE_URL": "http://qdrant:6333", "QDRANT_COLLECTION": "synapse_notes"},
        request_json=fake_requester,
    )

    assert result["notes"] == [{"source_path": "Runbook/ospf.md", "title": "OSPF Runbook"}]
    assert calls[0].get("offset") is None
    assert calls[1]["offset"] == "cursor-2"


def test_list_indexed_notes_ignores_payloads_without_markdown_source_path():
    def fake_requester(method, url, body, headers=None):
        return {
            "result": {
                "points": [
                    {"payload": {"source_path": "not-markdown.txt", "title": "Nope"}},
                    {"payload": {"title": "Missing path"}},
                ]
            }
        }

    result = list_indexed_notes(
        {},
        env={"QDRANT_BASE_URL": "http://qdrant:6333", "QDRANT_COLLECTION": "synapse_notes"},
        request_json=fake_requester,
    )

    assert result == {"notes": [], "count": 0}


def test_build_context_returns_exact_quoted_support_for_sources():
    result = build_context(
        {"question": "What algorithm is used in OSPF?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.92,
                "payload": {
                    "title": "OSPF note",
                    "source_path": "Synapse-Demo/ospf.md",
                    "text": "Intro sentence. OSPF uses Dijkstra's Shortest Path First algorithm. Extra trailing detail.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )

    assert result["insufficient_context"] is False
    assert result["sources"][0]["quoted_support"] == "OSPF uses Dijkstra's Shortest Path First algorithm."
    assert "OSPF uses Dijkstra's Shortest Path First algorithm." in result["context"]


def test_answer_gate_returns_quoted_support_but_marks_validation_as_structural():
    ctx = {
        "question": "what algorithm is used in ospf?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md", "quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}],
        "retrieval": {"accepted": 1},
    }

    result = answer_or_refuse(ctx, {"response": "OSPF uses Dijkstra's Shortest Path First algorithm. [1]"})

    assert result["insufficient_context"] is False
    assert result["sources"][0]["quoted_support"] == "OSPF uses Dijkstra's Shortest Path First algorithm."
    assert result["retrieval"]["answer_validation"] == "structural_citations_only"


def test_build_context_refuses_when_vector_hit_lacks_query_anchor_terms():
    result = build_context(
        {"question": "What algorithm is used in BGP?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.92,
                "payload": {
                    "title": "Generic graph algorithms",
                    "source_path": "Synapse-Demo/algorithms.md",
                    "text": "Dijkstra is a shortest path algorithm used in graph routing examples.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )

    assert result["insufficient_context"] is True
    assert result["sources"] == []
    assert result["retrieval"]["reason"] == "no_query_term_coverage"


def test_build_context_accepts_chunk_with_enough_query_term_coverage():
    result = build_context(
        {"question": "What algorithm is used in BGP?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.92,
                "payload": {
                    "title": "BGP notes",
                    "source_path": "Synapse-Demo/bgp.md",
                    "text": "BGP uses a path-vector routing algorithm to choose routes.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )

    assert result["insufficient_context"] is False
    assert result["sources"][0]["source_path"] == "Synapse-Demo/bgp.md"
    assert result["retrieval"]["query_terms"] == ["algorithm", "bgp"]
    assert set(result["retrieval"]["matched_terms"]) == {"algorithm", "bgp"}
    assert result["retrieval"]["term_coverage"] == 1


def test_build_context_can_expand_terms_with_domain_glossary_without_demo_hardcoding():
    without_glossary = build_context(
        {"question": "Which routing style does border gateway protocol use?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.9,
                "payload": {
                    "title": "BGP notes",
                    "source_path": "Synapse-Demo/bgp.md",
                    "text": "BGP uses a path-vector routing style.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )
    with_glossary = build_context(
        {"question": "Which routing style does border gateway protocol use?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.9,
                "payload": {
                    "title": "BGP notes",
                    "source_path": "Synapse-Demo/bgp.md",
                    "text": "BGP uses a path-vector routing style.",
                    "chunk_index": 0,
                },
            }
        ],
        env={"RAG_DOMAIN_GLOSSARY_JSON": '{"bgp": ["border gateway protocol"]}'},
    )

    assert without_glossary["insufficient_context"] is True
    assert without_glossary["retrieval"]["reason"] == "no_query_term_coverage"
    assert with_glossary["insufficient_context"] is False
    assert "border gateway protocol" in with_glossary["retrieval"]["matched_terms"]


def test_build_context_treats_structural_question_words_and_simple_inflections_as_grounding_safe():
    fields_result = build_context(
        {"question": "Which fields must every incident update include?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.9,
                "payload": {
                    "title": "Incident notes",
                    "source_path": "Synapse-Demo/incident.md",
                    "text": "Every incident update must include impact, owner, next action, and timestamp.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )
    fail_result = build_context(
        {"question": "When does a model fail the proof?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.9,
                "payload": {
                    "title": "Model notes",
                    "source_path": "Synapse-Demo/model.md",
                    "text": "A model fails the proof if it answers without a usable indexed source.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )
    focus_result = build_context(
        {"question": "What does autovacuum tuning focus on in the database notes?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.9,
                "payload": {
                    "title": "Database notes",
                    "source_path": "Synapse-Demo/db.md",
                    "text": "Autovacuum tuning focuses on dead tuples and table bloat.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )

    assert fields_result["insufficient_context"] is False
    assert fail_result["insufficient_context"] is False
    assert focus_result["insufficient_context"] is False


def test_build_context_can_ground_answer_across_multiple_sources():
    result = build_context(
        {"question": "For CX-ABC123-42, quote the queue and explicitly state both boundary phrases: local lab automation and not production-ready.", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.9,
                "payload": {
                    "title": "Current evidence",
                    "source_path": "Synapse-Demo/current.md",
                    "text": "The active incident queue is complex-queue-abc123. The current incident marker is CX-ABC123-42.",
                    "chunk_index": 0,
                },
            },
            {
                "score": 0.88,
                "payload": {
                    "title": "Boundary evidence",
                    "source_path": "Synapse-Demo/boundary.md",
                    "text": "Synapse is local lab automation only, not production-ready and not a public SaaS. Boundary applies to incident marker CX-ABC123-42.",
                    "chunk_index": 0,
                },
            },
        ],
        env={},
    )

    assert result["insufficient_context"] is False
    assert result["retrieval"]["combined_source_grounding"] is True
    assert {source["source_path"] for source in result["sources"]} == {"Synapse-Demo/current.md", "Synapse-Demo/boundary.md"}



def test_answer_gate_rejects_uncited_and_invalid_answers():
    ctx = {
        "question": "what algorithm is used in ospf?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md"}],
        "retrieval": {"accepted": 1},
    }

    uncited = answer_or_refuse(ctx, {"response": "OSPF uses Dijkstra's Shortest Path First algorithm."})
    invalid = answer_or_refuse(ctx, {"response": "OSPF uses Dijkstra's Shortest Path First algorithm. [99]"})
    valid = answer_or_refuse(ctx, {"response": "OSPF uses Dijkstra's Shortest Path First algorithm. [1]"})

    assert uncited["insufficient_context"] is True
    assert uncited["retrieval"]["refusal_reason"] == "missing_valid_citation"
    assert invalid["insufficient_context"] is True
    assert invalid["retrieval"]["refusal_reason"] == "invalid_citation"
    assert valid["insufficient_context"] is False
    assert valid["answer"].endswith("[1]")


def test_ask_calls_embed_qdrant_and_chat_then_returns_grounded_answer():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append((method, url, body))
        if url.endswith("/api/embed"):
            return {"embeddings": [[0.1, 0.2, 0.3]]}
        if url.endswith("/points/query"):
            return {
                "result": {
                    "points": [
                        {
                            "score": 0.91,
                            "payload": {
                                "title": "OSPF note",
                                "source_path": "Synapse-Demo/ospf.md",
                                "text": "OSPF uses Dijkstra's Shortest Path First algorithm.",
                                "chunk_index": 0,
                            },
                        }
                    ]
                }
            }
        if url.endswith("/api/chat"):
            return {"message": {"content": "OSPF uses Dijkstra's Shortest Path First algorithm. [1]"}}
        raise AssertionError(f"unexpected request: {method} {url}")

    result = ask(
        {"question": "What algorithm is used in OSPF?", "source_path": "Synapse-Demo/ospf.md"},
        env={
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_CHAT_BASE_URL": "http://chat-ollama:11434",
            "OLLAMA_EMBED_MODEL": "mock-embed",
            "OLLAMA_ANSWER_MODEL": "mock-answer",
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "RAG_SCORE_THRESHOLD": "0",
        },
        request_json=request_json,
    )

    assert result["insufficient_context"] is False
    assert result["answer"].endswith("[1]")
    assert calls[0][1] == "http://ollama:11434/api/embed"
    assert calls[1][1] == "http://qdrant:6333/collections/synapse_notes/points/query"
    assert calls[1][2]["filter"] == build_qdrant_filter({"source_path": "Synapse-Demo/ospf.md"})
    assert calls[2][1] == "http://chat-ollama:11434/api/chat"


def test_ask_retrieves_marker_scoped_multi_source_context_beyond_default_top_k():
    calls = []
    points = [
        {
            "score": 0.98,
            "payload": {
                "title": "Old boundary one",
                "source_path": "Synapse-Demo/old-boundary-1.md",
                "text": "Synapse is local lab automation only, not production-ready. Boundary applies to incident marker CX-OLD111-42.",
                "chunk_index": 0,
            },
        },
        {
            "score": 0.97,
            "payload": {
                "title": "Old boundary two",
                "source_path": "Synapse-Demo/old-boundary-2.md",
                "text": "Synapse is local lab automation only, not production-ready. Boundary applies to incident marker CX-OLD222-42.",
                "chunk_index": 0,
            },
        },
        {
            "score": 0.96,
            "payload": {
                "title": "Current boundary",
                "source_path": "Synapse-Demo/current-boundary.md",
                "text": "Synapse is local lab automation only, not production-ready and not a public SaaS. Boundary applies to incident marker CX-ABC123-42.",
                "chunk_index": 0,
            },
        },
        {
            "score": 0.95,
            "payload": {
                "title": "Old boundary three",
                "source_path": "Synapse-Demo/old-boundary-3.md",
                "text": "Synapse is local lab automation only, not production-ready. Boundary applies to incident marker CX-OLD333-42.",
                "chunk_index": 0,
            },
        },
        {
            "score": 0.94,
            "payload": {
                "title": "Old boundary four",
                "source_path": "Synapse-Demo/old-boundary-4.md",
                "text": "Synapse is local lab automation only, not production-ready. Boundary applies to incident marker CX-OLD444-42.",
                "chunk_index": 0,
            },
        },
        {
            "score": 0.93,
            "payload": {
                "title": "Old current one",
                "source_path": "Synapse-Demo/old-current-1.md",
                "text": "The active incident queue is stale-queue-one. The current incident marker is CX-OLD111-42.",
                "chunk_index": 0,
            },
        },
        {
            "score": 0.92,
            "payload": {
                "title": "Old current two",
                "source_path": "Synapse-Demo/old-current-2.md",
                "text": "The active incident queue is stale-queue-two. The current incident marker is CX-OLD222-42.",
                "chunk_index": 0,
            },
        },
        {
            "score": 0.91,
            "payload": {
                "title": "Current queue",
                "source_path": "Synapse-Demo/current-queue.md",
                "text": "The active incident queue is complex-queue-abc123. The current incident marker is CX-ABC123-42.",
                "chunk_index": 0,
            },
        },
    ]

    def request_json(method, url, body, headers=None):
        calls.append((method, url, body))
        if url.endswith("/api/embed"):
            return {"embeddings": [[0.1, 0.2, 0.3]]}
        if url.endswith("/points/query"):
            return {"result": {"points": points[: body["limit"]]}}
        raise AssertionError(f"chat should not be called in extractive mode: {method} {url}")

    result = ask(
        {"question": "For CX-ABC123-42, quote the queue and explicitly state both boundary phrases: local lab automation and not production-ready."},
        env={
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "RAG_SCORE_THRESHOLD": "0",
            "RAG_TOP_K": "5",
            "RAG_CANDIDATE_K": "10",
            "SYNAPSE_ANSWER_MODE": "extractive",
        },
        request_json=request_json,
    )

    qdrant_call = next(call for call in calls if call[1].endswith("/points/query"))
    assert qdrant_call[2]["limit"] == 10
    assert result["insufficient_context"] is False
    assert {source["source_path"] for source in result["sources"]} == {"Synapse-Demo/current-boundary.md", "Synapse-Demo/current-queue.md"}
    assert "complex-queue-abc123" in result["answer"]
    assert "local lab automation" in result["answer"]
    assert "not production-ready" in result["answer"]


def test_extractive_answer_builds_cited_answer_without_chat_model():
    ctx = {
        "sources": [
            {"source_path": "Synapse-Demo/current.md", "quoted_support": "The active incident queue is complex-queue-abc123."},
            {"source_path": "Synapse-Demo/boundary.md", "quoted_support": "Synapse is local lab automation only, not production-ready and not a public SaaS."},
        ]
    }

    assert extractive_answer(ctx) == "The active incident queue is complex-queue-abc123. [1]. Synapse is local lab automation only, not production-ready and not a public SaaS. [2]."


def test_ask_can_use_extractive_answer_mode_to_avoid_slow_chat_model():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append((method, url, body))
        if url.endswith("/api/embed"):
            return {"embeddings": [[0.1, 0.2, 0.3]]}
        if url.endswith("/points/query"):
            return {
                "result": {
                    "points": [
                        {
                            "score": 0.91,
                            "payload": {
                                "title": "Complex note",
                                "source_path": "Synapse-Demo/current.md",
                                "text": "Intro. The exact replay command is `python3 scripts/benchmark/workflow_top_models.py --proof-suite complex --models qwen2.5-coder:14b --skip-pull`.",
                                "chunk_index": 0,
                            },
                        }
                    ]
                }
            }
        raise AssertionError(f"chat should not be called in extractive mode: {method} {url}")

    result = ask(
        {"question": "Return the exact replay command recorded for current.", "source_path": "Synapse-Demo/current.md"},
        env={
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "RAG_SCORE_THRESHOLD": "0",
            "SYNAPSE_ANSWER_MODE": "extractive",
        },
        request_json=request_json,
    )

    assert result["insufficient_context"] is False
    assert "workflow_top_models.py" in result["answer"]
    assert result["answer"].endswith("[1].")
    assert not any(url.endswith("/api/chat") for _method, url, _body in calls)


def test_ask_short_circuits_chat_when_context_is_insufficient():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append(url)
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/query"):
            return {"result": {"points": []}}
        raise AssertionError(f"chat should not be called for insufficient context: {url}")

    result = ask(
        {"question": "What algorithm is used in OSPF?"},
        env={"QDRANT_BASE_URL": "http://qdrant:6333", "RAG_SCORE_THRESHOLD": "0"},
        request_json=request_json,
    )

    assert result["insufficient_context"] is True
    assert result["answer"] == INSUFFICIENT_ANSWER
    assert not any(url.endswith("/api/chat") for url in calls)


# ── quote-overlap and extractive validation tests ─────────────────────────


def test_ngrams_extracts_trigrams():
    assert _ngrams("OSPF uses Dijkstra") == {"ospf uses dijkstra"}
    assert _ngrams("a b c d") == {"a b c", "b c d"}
    assert _ngrams("short") == {"short"}


def test_quote_overlap_returns_high_when_answer_trigrams_match_sources():
    sources = [{"quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}]
    overlap = _quote_overlap("OSPF uses Dijkstra's Shortest Path First algorithm. [1]", sources)
    assert overlap > 0.5


def test_quote_overlap_returns_low_when_answer_invents_details():
    sources = [{"quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}]
    overlap = _quote_overlap("OSPF converges in under 50 milliseconds using Bellman-Ford. [1]", sources)
    assert overlap < 0.3


def test_quote_overlap_zero_when_empty_quoted_support():
    sources = [{"quoted_support": ""}]
    assert _quote_overlap("Any answer here. [1]", sources) == 0.0


def test_extractive_answer_valid_true_when_answer_content_in_quote():
    sources = [{"quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}]
    assert _extractive_answer_valid("OSPF uses Dijkstra's Shortest Path First algorithm. [1].", sources) is True


def test_extractive_answer_valid_false_when_answer_adds_unsupported_detail():
    sources = [{"quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}]
    assert _extractive_answer_valid("OSPF uses Dijkstra and converges in under 50ms. [1].", sources) is False


def test_extractive_answer_valid_false_when_empty_answer():
    sources = [{"quoted_support": "Some text."}]
    assert _extractive_answer_valid("[1].", sources) is False


def test_answer_or_refuse_default_structural_allows_halucinated_cited_answer():
    ctx = {
        "question": "what ospf convergence time?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md", "quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}],
        "retrieval": {"accepted": 1},
    }
    result = answer_or_refuse(
        ctx,
        {"response": "OSPF converges in under 50 milliseconds using Bellman-Ford. [1]"},
    )
    assert result["insufficient_context"] is False
    assert result["retrieval"]["answer_validation"] == "structural_citations_only"


def test_answer_or_refuse_quote_overlap_refuses_halucinated_cited_answer():
    ctx = {
        "question": "what ospf convergence time?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md", "quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}],
        "retrieval": {"accepted": 1},
    }
    result = answer_or_refuse(
        ctx,
        {"response": "OSPF converges in under 50 milliseconds using Bellman-Ford. [1]"},
        env={"SYNAPSE_ANSWER_VALIDATION": "quote_overlap"},
    )
    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "answer_grounding_failed"
    assert result["retrieval"]["quote_overlap"] < result["retrieval"]["quote_overlap_threshold"]


def test_answer_or_refuse_quote_overlap_passes_well_grounded_answer():
    ctx = {
        "question": "what algorithm does ospf use?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md", "quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}],
        "retrieval": {"accepted": 1},
    }
    result = answer_or_refuse(
        ctx,
        {"response": "OSPF uses Dijkstra's Shortest Path First algorithm. [1]"},
        env={"SYNAPSE_ANSWER_VALIDATION": "quote_overlap"},
    )
    assert result["insufficient_context"] is False
    assert result["retrieval"]["answer_validation"] == "quote_overlap"


def test_answer_or_refuse_extractive_validation_refuses_added_detail():
    ctx = {
        "question": "what algorithm does ospf use?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md", "quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}],
        "retrieval": {"accepted": 1},
    }
    result = answer_or_refuse(
        ctx,
        {"response": "OSPF uses Dijkstra's Shortest Path First algorithm and converges fast. [1]"},
        env={"SYNAPSE_ANSWER_VALIDATION": "extractive"},
    )
    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "answer_grounding_failed"
    assert result["retrieval"]["validation"] == "extractive_content_mismatch"


def test_answer_or_refuse_extractive_validation_passes_verbatim_answer():
    ctx = {
        "question": "what algorithm does ospf use?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md", "quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}],
        "retrieval": {"accepted": 1},
    }
    result = answer_or_refuse(
        ctx,
        {"response": "OSPF uses Dijkstra's Shortest Path First algorithm. [1]"},
        env={"SYNAPSE_ANSWER_VALIDATION": "extractive"},
    )
    assert result["insufficient_context"] is False
    assert result["retrieval"]["answer_validation"] == "extractive_content"


def test_answer_or_refuse_quote_overlap_custom_threshold():
    ctx = {
        "question": "what about ospf?",
        "insufficient_context": False,
        "sources": [{"source_path": "Synapse-Demo/ospf.md", "quoted_support": "OSPF uses Dijkstra's Shortest Path First algorithm."}],
        "retrieval": {"accepted": 1},
    }
    partial_answer = "OSPF uses Dijkstra's algorithm for fast convergence. [1]"
    low_threshold = answer_or_refuse(
        ctx,
        {"response": partial_answer},
        env={"SYNAPSE_ANSWER_VALIDATION": "quote_overlap", "RAG_QUOTE_OVERLAP_THRESHOLD": "0.05"},
    )
    assert low_threshold["insufficient_context"] is False

    high_threshold = answer_or_refuse(
        ctx,
        {"response": partial_answer},
        env={"SYNAPSE_ANSWER_VALIDATION": "quote_overlap", "RAG_QUOTE_OVERLAP_THRESHOLD": "0.9"},
    )
    assert high_threshold["insufficient_context"] is True


def test_ask_with_quote_overlap_refuses_halucinated_full_flow():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append((method, url, body))
        if url.endswith("/api/embed"):
            return {"embeddings": [[0.1, 0.2, 0.3]]}
        if url.endswith("/points/query"):
            return {
                "result": {
                    "points": [
                        {
                            "score": 0.91,
                            "payload": {
                                "title": "OSPF note",
                                "source_path": "Synapse-Demo/ospf.md",
                                "text": "OSPF uses Dijkstra's Shortest Path First algorithm.",
                                "chunk_index": 0,
                            },
                        }
                    ]
                }
            }
        if url.endswith("/api/chat"):
            return {"message": {"content": "OSPF converges in under 50 milliseconds using Bellman-Ford. [1]"}}
        raise AssertionError(f"unexpected request: {method} {url}")

    result = ask(
        {"question": "What algorithm is used in OSPF?"},
        env={
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_EMBED_MODEL": "mock-embed",
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "RAG_SCORE_THRESHOLD": "0",
            "SYNAPSE_ANSWER_VALIDATION": "quote_overlap",
        },
        request_json=request_json,
    )
    assert result["insufficient_context"] is True
    assert result["retrieval"]["refusal_reason"] == "answer_grounding_failed"


# ── multilingual and technical grounding tests ─────────────────────────────


def test_normalize_transliterates_german_umlauts():
    assert _normalize("Größe") == "grosse"
    assert _normalize("Käse") == "kase"
    assert _normalize("über") == "uber"
    assert _normalize("Nordrhein-Westfalen") == "nordrhein-westfalen"


def test_normalize_preserves_path_separators():
    assert _normalize("/etc/nginx/nginx.conf") == "/etc/nginx/nginx.conf"
    assert _normalize("scripts/e2e/start.sh") == "scripts/e2e/start.sh"


def test_normalize_preserves_dotted_versions():
    assert _normalize("v1.18.1") == "v1.18.1"
    assert _normalize("qdrant/qdrant:v1.18.1") == "qdrant/qdrant:v1.18.1"


def test_normalize_preserves_cli_flags():
    assert _normalize("--verbose") == "--verbose"
    assert _normalize("--skip-pull") == "--skip-pull"


def test_normalize_preserves_at_sign_and_hash():
    assert _normalize("user@host") == "user@host"
    assert _normalize("#ref") == "#ref"


def test_normalize_strips_non_preserved_symbols():
    assert _normalize("hello (world)") == "hello world"
    assert _normalize("foo=bar") == "foo bar"
    assert _normalize("a & b") == "a b"


def test_contains_term_matches_german_umlaut_text():
    text = "Die Größe der Datenbank beeinflusst die Latenz."
    assert _contains_term(text, "Größe") is True
    assert _contains_term(text, "grosse") is True


def test_contains_term_matches_file_path_in_text():
    text = "Edit /etc/nginx/nginx.conf to configure the reverse proxy."
    assert _contains_term(text, "/etc/nginx/nginx.conf") is True
    assert _contains_term(text, "nginx.conf") is True


def test_contains_term_matches_cli_flag():
    text = "Run with --skip-pull to avoid downloading model layers."
    assert _contains_term(text, "--skip-pull") is True


def test_contains_term_matches_vendor_names():
    text = "Juniper SRX firewalls use zone-based policies."
    assert _contains_term(text, "juniper") is True
    assert _contains_term(text, "srx") is True


def test_contains_term_matches_dotted_version():
    text = "Upgrade Qdrant to v1.18.1 for the fix."
    assert _contains_term(text, "v1.18.1") is True


def test_term_groups_extracts_german_terms():
    groups = _term_groups("Was ist die Größe der Datenbank?", env={})
    labels = [g["label"] for g in groups]
    assert "grosse" in labels
    assert "datenbank" in labels


def test_term_groups_extracts_paths_and_flags():
    groups = _term_groups("How to edit /etc/nginx/nginx.conf with --skip-pull?", env={})
    labels = [g["label"] for g in groups]
    assert "/etc/nginx/nginx.conf" in labels
    assert "--skip-pull" in labels


def test_term_groups_extracts_vendor_and_product_names():
    groups = _term_groups("Which Juniper SRX firewall supports BGP?", env={})
    labels = [g["label"] for g in groups]
    assert "juniper" in labels
    assert "srx" in labels
    assert "bgp" in labels


def test_build_context_grounds_german_note():
    result = build_context(
        {"question": "Was ist die Größe der Datenbank?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.92,
                "payload": {
                    "title": "Datenbank-Notizen",
                    "source_path": "Notes/Datenbank.md",
                    "text": "Die Größe der Datenbank beeinflusst die Abfragelatenz.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )
    assert result["insufficient_context"] is False
    assert "grosse" in result["retrieval"]["matched_terms"]
    assert "datenbank" in result["retrieval"]["matched_terms"]


def test_build_context_grounds_cli_command_note():
    result = build_context(
        {"question": "How to run --skip-pull in start.sh?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.92,
                "payload": {
                    "title": "Start script",
                    "source_path": "scripts/e2e/start.sh",
                    "text": "Run start.sh with --skip-pull to skip model downloads.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )
    assert result["insufficient_context"] is False
    assert "--skip-pull" in result["retrieval"]["matched_terms"]


def test_build_context_grounds_vendor_name_not_stopword():
    result = build_context(
        {"question": "Which Juniper firewall supports BGP?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.92,
                "payload": {
                    "title": "Firewall vendors",
                    "source_path": "Notes/firewall.md",
                    "text": "Juniper SRX firewalls support BGP and OSPF routing.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )
    assert result["insufficient_context"] is False
    assert "juniper" in result["retrieval"]["matched_terms"]


def test_build_context_grounds_file_path_in_note():
    result = build_context(
        {"question": "How to configure /etc/nginx/nginx.conf?", "filters": {}, "exact_run_id": ""},
        [
            {
                "score": 0.92,
                "payload": {
                    "title": "Nginx config",
                    "source_path": "Notes/nginx.md",
                    "text": "Edit /etc/nginx/nginx.conf to set the reverse proxy upstream.",
                    "chunk_index": 0,
                },
            }
        ],
        env={},
    )
    assert result["insufficient_context"] is False
    assert "/etc/nginx/nginx.conf" in result["retrieval"]["matched_terms"]


def test_anchor_terms_accepts_long_technical_names():
    groups = _term_groups("Which PostgreSQL extension supports pgvector?", env={})
    labels = [g["label"] for g in groups]
    assert "postgresql" in labels
    assert "pgvector" in labels
