import threading

from synapse.ingest import ingest, index_qdrant, note_from_payload, prepare_publish_payload, rollback_new_qdrant_chunks


def test_ingest_rejects_note_above_local_lab_content_limit_before_model_calls():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        return {"result": {"status": "ok"}}

    try:
        ingest(
            {"path": "Synapse-Demo/huge.md", "content": "abcdef"},
            env={"SYNAPSE_MAX_CONTENT_BYTES": "5"},
            request_json=request_json,
        )
    except ValueError as error:
        assert "content too large" in str(error)
        assert "max_content_bytes=5" in str(error)
    else:
        raise AssertionError("expected oversized content rejection")

    assert calls == []



def test_ingest_rejects_index_only_formatted_markdown_above_content_limit():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        return {"result": {"status": "ok"}}

    try:
        ingest(
            {
                "path": "Synapse-Demo/bypass.md",
                "content": "ok",
                "formatted_markdown": "x" * 20,
                "publish": False,
                "format": False,
            },
            env={"SYNAPSE_MAX_CONTENT_BYTES": "5"},
            request_json=request_json,
        )
    except ValueError as error:
        assert "content too large" in str(error)
        assert "formatted_markdown" in str(error)
    else:
        raise AssertionError("expected formatted_markdown size rejection")

    assert calls == []


def sample_note():
    return {
        "schema_version": "synapse-note-v1",
        "source": "obsidian",
        "vault_relative_path": "Synapse-Demo/stable-note.md",
        "title": "Stable Note",
        "slug": "stable-note",
        "note_id": "stable-note-id",
        "content_hash": "new-content-hash",
        "wiki_path": "/synapse-demo/stable-note",
        "path_parts": ["Synapse-Demo", "stable-note.md"],
        "content": "# Stable Note\n\nFresh replacement content.\n",
        "formatted_markdown": "# Stable Note\n\nFresh replacement content.\n",
    }


def test_note_from_payload_builds_metadata_and_path_parts():
    note = note_from_payload({"path": "Synapse-Demo\\ospf.md", "content": "# OSPF\nBody", "title": "OSPF Override"})

    assert note["vault_relative_path"] == "Synapse-Demo/ospf.md"
    assert note["title"] == "OSPF Override"
    assert note["slug"] == "ospf-override"
    assert note["wiki_path"] == "/synapse-demo/ospf"
    assert note["path_parts"] == ["Synapse-Demo", "ospf.md"]
    assert note["content"].endswith("\n")


def test_title_override_keeps_slug_and_wiki_path_consistent():
    note = note_from_payload({"path": "Lab/ospf-notes.md", "content": "# Content\nBody", "title": "OSPF Deep Dive"})

    assert note["title"] == "OSPF Deep Dive"
    assert note["slug"] == "ospf-deep-dive"
    assert note["wiki_path"] == "/lab/ospf-notes"


def test_title_override_in_root_path_keeps_wiki_path_stable():
    note = note_from_payload({"path": "simple.md", "content": "# Content\nBody", "title": "Renamed Note"})

    assert note["title"] == "Renamed Note"
    assert note["slug"] == "renamed-note"
    assert note["wiki_path"] == "/simple"


def test_no_title_override_uses_path_derived_wiki_path():
    note = note_from_payload({"path": "Lab/ospf-notes.md", "content": "# OSPF Notes\nBody"})

    assert note["title"] == "OSPF Notes"
    assert note["slug"] == "ospf-notes"
    assert note["wiki_path"] == "/lab/ospf-notes"


def test_title_override_in_nested_dir_keeps_path_segments_stable():
    note = note_from_payload({"path": "Infra/Networking/ospf.md", "content": "# Content", "title": "New Title"})

    assert note["slug"] == "new-title"
    assert note["wiki_path"] == "/infra/networking/ospf"


def test_title_changes_keep_note_and_publication_identity_stable():
    original = note_from_payload({"path": "Lab/ospf.md", "content": "# Old Title\nBody"})
    renamed = note_from_payload({"path": "Lab/ospf.md", "content": "# New Title\nBody"})

    assert original["note_id"] == renamed["note_id"]
    assert original["wiki_path"] == renamed["wiki_path"] == "/lab/ospf"
    assert original["title"] != renamed["title"]


def test_note_from_payload_rejects_missing_path():
    try:
        note_from_payload({"content": "# No Path\nBody"})
    except ValueError as error:
        assert "path or vault_relative_path" in str(error)
    else:
        raise AssertionError("expected missing path rejection")


def test_note_from_payload_rejects_empty_path():
    try:
        note_from_payload({"path": "", "content": "# Empty Path\nBody"})
    except ValueError as error:
        assert "path or vault_relative_path" in str(error)
    else:
        raise AssertionError("expected empty path rejection")


def test_note_from_payload_rejects_whitespace_only_path():
    try:
        note_from_payload({"path": "   ", "content": "# Whitespace Path\nBody"})
    except ValueError as error:
        assert "path or vault_relative_path" in str(error)
    else:
        raise AssertionError("expected whitespace-only path rejection")


def test_note_from_payload_accepts_vault_relative_path_as_alternative():
    note = note_from_payload({"vault_relative_path": "Notes/alt.md", "content": "# Alt\nBody"})

    assert note["vault_relative_path"] == "Notes/alt.md"
    assert note["wiki_path"] == "/notes/alt"


def test_note_from_payload_prefers_path_over_vault_relative_path():
    note = note_from_payload({"path": "Notes/path.md", "vault_relative_path": "Notes/alt.md", "content": "# Both\nBody"})

    assert note["vault_relative_path"] == "Notes/path.md"


def test_index_qdrant_does_not_delete_existing_chunks_when_embedding_fails():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        if url.endswith("/api/embed"):
            raise RuntimeError("embedding failed")
        return {"result": {"status": "ok"}}

    try:
        index_qdrant(
            sample_note(),
            {"QDRANT_BASE_URL": "http://qdrant:6333", "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434"},
            request_json,
        )
    except RuntimeError as error:
        assert str(error) == "embedding failed"
    else:
        raise AssertionError("expected embedding failure")

    assert not any("/points/delete" in call["url"] for call in calls)


def test_index_qdrant_rejects_notes_that_create_too_many_chunks_before_embedding():
    long_text = "\n\n".join(f"section {index} " + "x" * 900 for index in range(4))
    item = {**sample_note(), "formatted_markdown": long_text}
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        return {"result": {"status": "ok"}}

    try:
        index_qdrant(item, {"SYNAPSE_MAX_CHUNKS_PER_NOTE": "2"}, request_json)
    except ValueError as error:
        assert "too many chunks" in str(error)
        assert "max_chunks_per_note=2" in str(error)
    else:
        raise AssertionError("expected chunk limit rejection")

    assert calls == []


def test_index_qdrant_batches_embeddings_instead_of_calling_once_per_chunk():
    long_text = "\n\n".join(f"section {index} " + "x" * 900 for index in range(3))
    item = {**sample_note(), "formatted_markdown": long_text}
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        if url.endswith("/api/embed"):
            assert isinstance(body["input"], list)
            return {"embeddings": [[0.1, 0.2, 0.3] for _ in body["input"]]}
        if url.endswith("/points/count"):
            return {"result": {"count": 3}}
        return {"result": {"status": "ok"}}

    count = index_qdrant(
        item,
        {"SYNAPSE_MAX_CHUNKS_PER_NOTE": "5", "SYNAPSE_EMBED_BATCH_SIZE": "10"},
        request_json,
    )

    embed_calls = [call for call in calls if call["url"].endswith("/api/embed")]
    assert count == 3
    assert len(embed_calls) == 1
    assert len(embed_calls[0]["body"]["input"]) == 3


def test_index_qdrant_upserts_and_verifies_new_hash_before_deleting_old_hashes():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        if url.endswith("/api/embed"):
            return {"embeddings": [[1, 0, 0, 0, 0, 0, 0, 0]]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        return {"result": {"status": "ok"}}

    count = index_qdrant(
        sample_note(),
        {"QDRANT_BASE_URL": "http://qdrant:6333", "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434"},
        request_json,
    )

    assert count == 1
    urls = [call["url"] for call in calls]
    upsert_index = next(i for i, url in enumerate(urls) if "/points?wait=true" in url)
    verify_index = next(i for i, url in enumerate(urls) if "/points/count" in url)
    delete_index = next(i for i, url in enumerate(urls) if "/points/delete" in url)
    assert upsert_index < verify_index < delete_index
    assert len(calls[upsert_index]["body"]["points"]) == 1
    assert calls[upsert_index]["body"]["points"][0]["payload"]["note_id"] == "stable-note-id"
    payload = calls[upsert_index]["body"]["points"][0]["payload"]
    assert payload["revision"] == "new-content-hash"
    assert payload["current_content_hash"] == "new-content-hash"
    assert payload["ingest_job_id"].startswith("ingest-stable-note-id-")
    assert payload["updated_at"].endswith("Z")

    assert calls[verify_index]["body"]["filter"]["must"] == [
        {"key": "note_id", "match": {"value": "stable-note-id"}},
        {"key": "content_hash", "match": {"value": "new-content-hash"}},
    ]
    assert calls[delete_index]["body"]["filter"]["must_not"] == [
        {"key": "content_hash", "match": {"value": "new-content-hash"}}
    ]


def test_ingest_index_only_skips_wikijs_and_formats_nothing():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        return {"result": {"status": "ok"}}

    result = ingest(
        {"path": "Synapse-Demo/ci.md", "content": "# CI\n\nsynapse-ci-proof", "publish": False, "format": False},
        env={"QDRANT_BASE_URL": "http://qdrant:6333", "QDRANT_COLLECTION": "synapse_ci", "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434"},
        request_json=request_json,
    )

    assert result["status"] == "indexed"
    assert result["publisher_status"] == "skipped"
    assert result["indexed_chunks"] == 1
    assert not any("/graphql" in call["url"] for call in calls)
    assert not any("/api/chat" in call["url"] for call in calls)


def test_ingest_publish_indexes_before_wikijs_to_avoid_visible_page_ahead_of_index():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body, "headers": headers or {}})
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            return {"data": {"pages": {"singleByPath": None}}}
        if url.endswith("/graphql") and "mutation Create" in body["query"]:
            return {"data": {"pages": {"create": {"responseResult": {"succeeded": True}, "page": {"id": 1}}}}}
        return {"result": {"status": "ok"}}

    result = ingest(
        {"path": "Synapse-Demo/published.md", "content": "# Published\n\nBody."},
        env={
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
            "WIKIJS_BASE_URL": "http://wikijs:3000",
            "WIKIJS_API_TOKEN": "token",
        },
        request_json=request_json,
    )

    assert result["status"] == "ok"
    urls = [call["url"] for call in calls]
    first_graphql = next(i for i, url in enumerate(urls) if url == "http://wikijs:3000/graphql")
    upsert_index = next(i for i, url in enumerate(urls) if "/points?wait=true" in url)
    verify_index = next(i for i, url in enumerate(urls) if "/points/count" in url)
    delete_index = next(i for i, url in enumerate(urls) if "/points/delete" in url)
    assert upsert_index < verify_index < first_graphql < delete_index
    assert result["revision"] == result["content_hash"]
    assert result["updated_at"].endswith("Z")
    assert result["publisher"] == "wikijs"
    assert result["publisher_status"] == "ok"
    assert "Original Source Note" in result["formatted_markdown"]


def test_ingest_publish_indexes_original_source_not_truncated_formatted_markdown():
    embed_inputs = []

    def request_json(method, url, body, headers=None):
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nThe exact replay command is `python3 scripts/benchmark/workflow"}}
        if url.endswith("/api/embed"):
            embed_inputs.extend(body["input"] if isinstance(body["input"], list) else [body["input"]])
            return {"embeddings": [[0.1, 0.2, 0.3] for _ in body["input"]]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            return {"data": {"pages": {"singleByPath": None}}}
        if url.endswith("/graphql") and "mutation Create" in body["query"]:
            return {"data": {"pages": {"create": {"responseResult": {"succeeded": True}, "page": {"id": 1}}}}}
        return {"result": {"status": "ok"}}

    ingest(
        {
            "path": "Synapse-Demo/current.md",
            "content": "# Current\n\nThe exact replay command is `python3 -m scripts.benchmark workflow --proof-suite complex --models qwen2.5-coder:14b --skip-pull`.\n",
        },
        env={
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
            "WIKIJS_BASE_URL": "http://wikijs:3000",
            "WIKIJS_API_TOKEN": "token",
        },
        request_json=request_json,
    )

    indexed_text = "\n".join(embed_inputs)
    assert "scripts.benchmark workflow --proof-suite complex" in indexed_text
    assert "python3 scripts/benchmark/workflow`" not in indexed_text


def test_publish_wikijs_updates_existing_page_via_singleByPath():
    graphql_calls = []

    def request_json(method, url, body, headers=None):
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql"):
            graphql_calls.append({"query": body.get("query", ""), "variables": body.get("variables", {})})
            if "singleByPath" in body.get("query", ""):
                return {"data": {"pages": {"singleByPath": {"id": 42, "path": "synapse-demo/published", "title": "Published"}}}}
            if "mutation Update" in body.get("query", ""):
                return {"data": {"pages": {"update": {"responseResult": {"succeeded": True}, "page": {"id": 42, "path": "synapse-demo/published", "title": "Published"}}}}}
            if "mutation Create" in body.get("query", ""):
                return {"data": {"pages": {"create": {"responseResult": {"succeeded": True}, "page": {"id": 99, "path": "synapse-demo/published"}}}}}
        return {"result": {"status": "ok"}}

    result = ingest(
        {"path": "Synapse-Demo/Published.md", "content": "# Published\n\nBody."},
        env={
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
            "WIKIJS_BASE_URL": "http://wikijs:3000",
            "WIKIJS_API_TOKEN": "token",
        },
        request_json=request_json,
    )

    assert result["status"] == "ok"
    lookup = next((c for c in graphql_calls if "singleByPath" in c["query"]), None)
    assert lookup is not None, "singleByPath lookup must be called"
    assert lookup["variables"]["path"] == "/synapse-demo/published"
    update = next((c for c in graphql_calls if "mutation Update" in c["query"]), None)
    assert update is not None, "must call update mutation for existing page"
    assert update["variables"]["id"] == 42
    create = next((c for c in graphql_calls if "mutation Create" in c["query"]), None)
    assert create is None, "must not call create mutation for existing page"


def test_publish_wikijs_retries_existing_lookup_without_leading_slash():
    graphql_calls = []

    def request_json(method, url, body, headers=None):
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql"):
            graphql_calls.append(body)
            if "singleByPath" in body.get("query", ""):
                if body["variables"]["path"].startswith("/"):
                    return {"data": {"pages": {"singleByPath": None}}}
                return {"data": {"pages": {"singleByPath": {"id": 42, "path": "synapse-demo/existing", "title": "Existing"}}}}
            if "mutation Update" in body.get("query", ""):
                return {"data": {"pages": {"update": {"responseResult": {"succeeded": True}, "page": {"id": 42}}}}}
        return {"result": {"status": "ok"}}

    result = ingest(
        {"path": "Synapse-Demo/Existing.md", "content": "# Existing\n\nBody."},
        env={
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "WIKIJS_BASE_URL": "http://wikijs:3000",
            "WIKIJS_API_TOKEN": "token",
        },
        request_json=request_json,
    )

    lookups = [call for call in graphql_calls if "singleByPath" in call.get("query", "")]
    assert [call["variables"]["path"] for call in lookups] == ["/synapse-demo/existing", "synapse-demo/existing"]
    assert any("mutation Update" in call.get("query", "") for call in graphql_calls)
    assert result["status"] == "ok"


def test_publish_wikijs_creates_new_page_when_singleByPath_returns_none():
    graphql_calls = []

    def request_json(method, url, body, headers=None):
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql"):
            graphql_calls.append({"query": body.get("query", ""), "variables": body.get("variables", {})})
            if "singleByPath" in body.get("query", ""):
                return {"data": {"pages": {"singleByPath": None}}}
            if "mutation Create" in body.get("query", ""):
                return {"data": {"pages": {"create": {"responseResult": {"succeeded": True}, "page": {"id": 7, "path": "synapse-demo/new-page"}}}}}
        return {"result": {"status": "ok"}}

    result = ingest(
        {"path": "Synapse-Demo/New-Page.md", "content": "# New Page\n\nBody."},
        env={
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
            "WIKIJS_BASE_URL": "http://wikijs:3000",
            "WIKIJS_API_TOKEN": "token",
        },
        request_json=request_json,
    )

    assert result["status"] == "ok"
    lookup = next((c for c in graphql_calls if "singleByPath" in c["query"]), None)
    assert lookup is not None, "singleByPath lookup must be called"
    create = next((c for c in graphql_calls if "mutation Create" in c["query"]), None)
    assert create is not None, "must call create mutation for new page"
    update = next((c for c in graphql_calls if "mutation Update" in c["query"]), None)
    assert update is None, "must not call update mutation for new page"


def test_publish_wikijs_treats_wikijs_page_not_found_as_new_page():
    def request_json(method, url, body, headers=None):
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            return {
                "errors": [{"message": "This page does not exist."}],
                "data": {"pages": {"singleByPath": None}},
            }
        if url.endswith("/graphql") and "mutation Create" in body.get("query", ""):
            return {"data": {"pages": {"create": {"responseResult": {"succeeded": True}, "page": {"id": 7}}}}}
        return {"result": {"status": "ok"}}

    result = ingest(
        {"path": "Synapse-Demo/Missing-Page.md", "content": "# Missing Page\n\nBody."},
        env={
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "QDRANT_COLLECTION": "synapse_notes",
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
            "WIKIJS_BASE_URL": "http://wikijs:3000",
            "WIKIJS_API_TOKEN": "token",
        },
        request_json=request_json,
    )

    assert result["status"] == "ok"



def test_ingest_refuses_concurrent_updates_for_same_note_id():
    first_started = threading.Event()
    release_first = threading.Event()
    first_result = {}

    def request_json(method, url, body, headers=None):
        if url.endswith("/api/embed"):
            first_started.set()
            release_first.wait(timeout=5)
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        return {"result": {"status": "ok"}}

    payload = {"path": "Synapse-Demo/concurrent.md", "content": "# Concurrent\n\nBody.", "publish": False, "format": False}

    def run_first():
        try:
            first_result["value"] = ingest(payload, request_json=request_json)
        except Exception as error:  # noqa: BLE001 - test thread should capture failures.
            first_result["error"] = error

    thread = threading.Thread(target=run_first)
    thread.start()
    assert first_started.wait(timeout=5)

    try:
        ingest(payload, request_json=request_json)
    except ValueError as error:
        assert "concurrent update refused" in str(error)
        assert "note_id" in str(error)
    else:
        raise AssertionError("expected concurrent same-note refusal")
    finally:
        release_first.set()
        thread.join(timeout=5)

    assert "error" not in first_result
    assert first_result["value"]["status"] == "indexed"


def test_prepare_publish_payload_adds_frontmatter_and_source_block():
    payload = prepare_publish_payload(sample_note(), "# Clean\n\nBody")

    assert payload["formatted_markdown"].startswith("---\nsynapse_note_id: stable-note-id")
    assert "## Original Source Note" in payload["formatted_markdown"]


def test_ingest_publish_rollback_qdrant_on_wikijs_failure():
    """When Wiki.js publish fails, newly inserted Qdrant chunks must be deleted."""
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body, "headers": headers or {}})
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            raise RuntimeError("Wiki.js API is disabled")
        return {"result": {"status": "ok"}}

    try:
        ingest(
            {"path": "Synapse-Demo/rollback.md", "content": "# Rollback\n\nBody."},
            env={
                "QDRANT_BASE_URL": "http://qdrant:6333",
                "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
                "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
                "WIKIJS_BASE_URL": "http://wikijs:3000",
                "WIKIJS_API_TOKEN": "token",
            },
            request_json=request_json,
        )
    except RuntimeError as error:
        assert "Wiki.js API is disabled" in str(error)
    else:
        raise AssertionError("expected Wiki.js publish failure to propagate")

    # Verify rollback: a delete request targeting the new content_hash must exist
    delete_calls = [c for c in calls if "/points/delete" in c["url"]]
    assert len(delete_calls) >= 1, "rollback must issue a Qdrant delete after Wiki.js failure"

    rollback_call = delete_calls[0]
    filter_must = rollback_call["body"]["filter"]["must"]
    # The rollback delete targets note_id AND the new content_hash (not must_not)
    content_hash_key = next((m for m in filter_must if m["key"] == "content_hash"), None)
    assert content_hash_key is not None, "rollback delete must filter on content_hash"
    assert "must_not" not in rollback_call["body"]["filter"], "rollback uses must (not must_not)"


def test_ingest_publish_rollback_targets_only_new_chunks():
    """Rollback delete must match the new content_hash, not the stale one."""
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body, "headers": headers or {}})
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            raise RuntimeError("Wiki.js down")
        return {"result": {"status": "ok"}}

    try:
        ingest(
            {"path": "Synapse-Demo/rollback2.md", "content": "# Rollback2\n\nBody."},
            env={
                "QDRANT_BASE_URL": "http://qdrant:6333",
                "QDRANT_COLLECTION": "synapse_notes",
                "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
                "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
                "WIKIJS_BASE_URL": "http://wikijs:3000",
                "WIKIJS_API_TOKEN": "token",
            },
            request_json=request_json,
        )
    except RuntimeError:
        pass

    delete_calls = [c for c in calls if "/points/delete" in c["url"]]
    assert len(delete_calls) == 1, "exactly one rollback delete call"

    rollback = delete_calls[0]
    must = rollback["body"]["filter"]["must"]
    # Both note_id and content_hash in must — this targets ONLY new chunks
    assert len(must) == 2
    keys = {m["key"] for m in must}
    assert keys == {"note_id", "content_hash"}


def test_rollback_new_qdrant_chunks_deletes_by_note_id_and_content_hash():
    """Unit test: rollback_new_qdrant_chunks issues a must filter with both keys."""
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        return {"result": {"status": "ok"}}

    rollback_new_qdrant_chunks(
        sample_note(),
        {"QDRANT_BASE_URL": "http://qdrant:6333", "QDRANT_COLLECTION": "synapse_notes"},
        request_json,
    )

    assert len(calls) == 1
    call = calls[0]
    assert "/points/delete" in call["url"]
    assert "wait=true" in call["url"]
    must = call["body"]["filter"]["must"]
    assert {"key": "note_id", "match": {"value": "stable-note-id"}} in must
    assert {"key": "content_hash", "match": {"value": "new-content-hash"}} in must
    assert "must_not" not in call["body"]["filter"]


def test_ingest_publish_no_rollback_on_success():
    """When Wiki.js publish succeeds, no rollback delete should happen — only stale cleanup."""
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body, "headers": headers or {}})
        if url.endswith("/api/chat"):
            return {"message": {"content": "# Formatted\n\nBody."}}
        if url.endswith("/api/embed"):
            return {"embedding": [0.1, 0.2, 0.3]}
        if url.endswith("/points/count"):
            return {"result": {"count": 1}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            return {"data": {"pages": {"singleByPath": None}}}
        if url.endswith("/graphql") and "mutation Create" in body["query"]:
            return {"data": {"pages": {"create": {"responseResult": {"succeeded": True}, "page": {"id": 1}}}}}
        return {"result": {"status": "ok"}}

    result = ingest(
        {"path": "Synapse-Demo/success.md", "content": "# Success\n\nBody."},
        env={
            "QDRANT_BASE_URL": "http://qdrant:6333",
            "OLLAMA_INTERNAL_BASE_URL": "http://ollama:11434",
            "OLLAMA_CHAT_BASE_URL": "http://ollama:11434",
            "WIKIJS_BASE_URL": "http://wikijs:3000",
            "WIKIJS_API_TOKEN": "token",
        },
        request_json=request_json,
    )

    assert result["status"] == "ok"
    assert result["publisher_status"] == "ok"

    delete_calls = [c for c in calls if "/points/delete" in c["url"]]
    # Only one delete call: the stale-chunk cleanup (must_not on content_hash), not a rollback
    assert len(delete_calls) == 1
    assert "must_not" in delete_calls[0]["body"]["filter"], "success path uses stale cleanup, not rollback"


def test_ingest_delete_removes_qdrant_before_published_page():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body, "headers": headers or {}})
        if url.endswith("/points/delete?wait=true"):
            return {"result": {"status": "ok"}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            return {"data": {"pages": {"singleByPath": {"id": 42, "path": "lab/ospf", "title": "Old Title"}}}}
        if url.endswith("/graphql") and "mutation Delete" in body.get("query", ""):
            return {"data": {"pages": {"remove": {"responseResult": {"succeeded": True, "message": ""}}}}}
        raise AssertionError(f"unexpected request: {method} {url}")

    result = ingest(
        {"path": "Lab/ospf.md", "delete": True},
        env={"QDRANT_BASE_URL": "http://qdrant:6333", "WIKIJS_BASE_URL": "http://wikijs:3000", "WIKIJS_API_TOKEN": "token"},
        request_json=request_json,
    )

    assert result["status"] == "deleted"
    assert result["publisher_status"] == "deleted"
    assert result["wiki_path"] == "/lab/ospf"
    delete_index = next(index for index, call in enumerate(calls) if "/points/delete" in call["url"])
    graphql_index = next(index for index, call in enumerate(calls) if "mutation Delete" in call["body"].get("query", ""))
    assert delete_index < graphql_index
    assert calls[delete_index]["body"]["filter"]["must"] == [{"key": "note_id", "match": {"value": result["note_id"]}}]
    assert calls[graphql_index]["body"]["variables"] == {"id": 42}


def test_ingest_delete_treats_missing_published_page_as_success():
    calls = []

    def request_json(method, url, body, headers=None):
        calls.append({"method": method, "url": url, "body": body})
        if url.endswith("/points/delete?wait=true"):
            return {"result": {"status": "ok"}}
        if url.endswith("/graphql") and "singleByPath" in body.get("query", ""):
            return {"data": {"pages": {"singleByPath": None}}}
        raise AssertionError(f"unexpected request: {method} {url}")

    result = ingest(
        {"path": "Lab/missing.md", "delete": True},
        env={"QDRANT_BASE_URL": "http://qdrant:6333", "WIKIJS_BASE_URL": "http://wikijs:3000", "WIKIJS_API_TOKEN": "token"},
        request_json=request_json,
    )

    assert result["status"] == "deleted"
    assert result["wikijs_result"] == {"status": "not_found"}
    assert not any("mutation Delete" in call["body"].get("query", "") for call in calls)
