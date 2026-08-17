
import pytest
from fastapi.testclient import TestClient

from synapse import service  # noqa: E402
from synapse import Settings
from synapse import http_client, runtime as runtime_module
from synapse.runtime import SynapseRuntime
from synapse.service import create_app
from synapse.upstream import UpstreamError  # noqa: E402


def test_fastapi_app_exposes_healthz():
    client = TestClient(service.app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_returns_503_when_backends_unreachable(monkeypatch):
    monkeypatch.setenv("QDRANT_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("QDRANT_COLLECTION", "test_collection")
    monkeypatch.setenv("OLLAMA_INTERNAL_BASE_URL", "http://127.0.0.1:2")
    monkeypatch.setenv("WIKIJS_BASE_URL", "http://127.0.0.1:3")
    monkeypatch.setenv("WIKIJS_API_TOKEN", "real-token")

    client = TestClient(service.app)
    response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["qdrant"]["ok"] is False
    assert body["checks"]["ollama"]["ok"] is False
    assert body["checks"]["wikijs"]["ok"] is False
    assert body["checks"]["publishing"]["enabled"] is True
    assert body["checks"]["publishing"]["blocking"] is True


def test_readyz_returns_200_when_all_backends_reachable(monkeypatch):
    import http.server
    import socketserver
    import threading

    class OkHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = b'{"result":{}}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *_args):  # noqa: A002
            return

    with socketserver.TCPServer(("127.0.0.1", 0), OkHandler) as server:
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        port = server.server_address[1]
        base = f"http://127.0.0.1:{port}"

        monkeypatch.setenv("QDRANT_BASE_URL", base)
        monkeypatch.setenv("QDRANT_COLLECTION", "test_collection")
        monkeypatch.setenv("OLLAMA_INTERNAL_BASE_URL", base)
        monkeypatch.setenv("WIKIJS_BASE_URL", base)
        monkeypatch.setenv("WIKIJS_API_TOKEN", "real-token")

        client = TestClient(service.app)
        response = client.get("/readyz")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["qdrant"]["ok"] is True
        assert body["checks"]["ollama"]["ok"] is True
        assert body["checks"]["wikijs"]["ok"] is True
        assert body["checks"]["publishing"]["enabled"] is True

        server.shutdown()


def test_readyz_skips_wikijs_blocking_when_publishing_disabled(monkeypatch):
    monkeypatch.setenv("QDRANT_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("QDRANT_COLLECTION", "test_collection")
    monkeypatch.setenv("OLLAMA_INTERNAL_BASE_URL", "http://127.0.0.1:2")
    monkeypatch.setenv("WIKIJS_BASE_URL", "http://127.0.0.1:3")
    # Placeholder token -> publishing disabled -> wikijs failure non-blocking
    monkeypatch.setenv("WIKIJS_API_TOKEN", "replace-after-wikijs-admin-setup")

    # Qdrant and Ollama still unreachable -> 503, but not because of wikijs
    client = TestClient(service.app)
    response = client.get("/readyz")

    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["wikijs"]["ok"] is False
    assert body["checks"]["publishing"]["enabled"] is False
    assert body["checks"]["publishing"]["blocking"] is False
    # When publishing is disabled, wikijs failure is informational only:
    # the not_ready comes from qdrant+ollama, not wikijs being blocked.
    failed_blocking = [
        k for k, v in body["checks"].items()
        if k != "publishing" and isinstance(v, dict) and v.get("ok") is False
    ]
    assert "qdrant" in failed_blocking
    assert "ollama" in failed_blocking


def test_readyz_missing_qdrant_collection_returns_not_ready(monkeypatch):
    monkeypatch.delenv("QDRANT_COLLECTION", raising=False)
    monkeypatch.setenv("QDRANT_BASE_URL", "http://127.0.0.1:1")

    result = service._check_readiness({
        "QDRANT_BASE_URL": "http://127.0.0.1:1",
        "QDRANT_COLLECTION": "",
        "OLLAMA_INTERNAL_BASE_URL": "http://127.0.0.1:2",
        "WIKIJS_BASE_URL": "http://127.0.0.1:3",
    })

    assert result["status"] == "not_ready"
    assert result["checks"]["qdrant"]["detail"] == "QDRANT_COLLECTION not set"


def test_direct_endpoints_fail_closed_when_token_missing(monkeypatch):
    monkeypatch.delenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "false")
    client = TestClient(service.app)

    response = client.post("/ask", json={"question": "What is OSPF?"})

    assert response.status_code == 401
    body = response.json()
    assert body["error_code"] == "unauthorized"
    assert "SYNAPSE_WEBHOOK_AUTH_TOKEN" in body["error"]


def test_direct_ask_endpoint_reuses_ask_module(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")
    captured = {}

    def fake_ask(payload):
        captured["payload"] = payload
        return {"answer": "ok", "sources": []}

    monkeypatch.setattr(service, "ask", fake_ask)
    client = TestClient(service.app)

    response = client.post("/ask", json={"question": "What is OSPF?"})

    assert response.status_code == 200
    assert response.json() == {"answer": "ok", "sources": []}
    assert captured["payload"] == {"question": "What is OSPF?"}


def test_direct_ingest_endpoint_reuses_ingest_module(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")
    captured = {}

    def fake_ingest(payload):
        captured["payload"] = payload
        return {"status": "ok", "note_id": "note-1"}

    monkeypatch.setattr(service, "ingest", fake_ingest)
    client = TestClient(service.app)

    response = client.post("/ingest", json={"path": "Demo/Note.md", "content": "# Note"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "note_id": "note-1"}
    assert captured["payload"] == {"path": "Demo/Note.md", "content": "# Note"}


def test_service_preserves_value_error_json_contract(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")

    def fake_ask(payload):
        raise ValueError("Send JSON with a question field.")

    monkeypatch.setattr(service, "ask", fake_ask)
    client = TestClient(service.app)

    response = client.post("/ask", json={"question": ""})

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "bad_request"
    assert body["error"] == "Send JSON with a question field."


def test_service_upstream_error_returns_generic_code_without_details(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")

    def fake_ask(payload):
        raise UpstreamError(
            "upstream_qdrant_error",
            "POST http://qdrant:6333/collections/synapse_notes/points/query failed with HTTP 500: Internal server error at 10.0.0.5",
        )

    monkeypatch.setattr(service, "ask", fake_ask)
    client = TestClient(service.app, raise_server_exceptions=False)

    response = client.post("/ask", json={"question": "What is OSPF?"})

    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "upstream_qdrant_error"
    assert body["error"] == "upstream service unavailable"
    # Verify no upstream details leak
    assert "qdrant:6333" not in body["error"]
    assert "10.0.0.5" not in body["error"]
    assert "Internal server error" not in body["error"]


def test_service_ollama_upstream_error_returns_generic_code(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")

    def fake_ask(payload):
        raise UpstreamError(
            "upstream_ollama_error",
            "POST http://ollama:11434/api/chat failed with HTTP 404: model 'tinyllama' not found",
        )

    monkeypatch.setattr(service, "ask", fake_ask)
    client = TestClient(service.app, raise_server_exceptions=False)

    response = client.post("/ask", json={"question": "What is OSPF?"})

    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "upstream_ollama_error"
    assert body["error"] == "upstream service unavailable"
    assert "ollama:11434" not in body["error"]
    assert "tinyllama" not in body["error"]


def test_service_wikijs_upstream_error_returns_generic_code(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")

    def fake_ingest(payload):
        raise UpstreamError(
            "upstream_wikijs_error",
            "POST http://wikijs:3000/graphql failed with HTTP 403: Forbidden - API token expired for user admin@wiki.local",
        )

    monkeypatch.setattr(service, "ingest", fake_ingest)
    client = TestClient(service.app, raise_server_exceptions=False)

    response = client.post("/ingest", json={"path": "Demo/Note.md", "content": "# Note"})

    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "upstream_wikijs_error"
    assert body["error"] == "upstream service unavailable"
    assert "wikijs:3000" not in body["error"]
    assert "admin@wiki.local" not in body["error"]


def test_service_generic_runtime_error_returns_internal_error_code(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")

    def fake_ask(payload):
        raise RuntimeError("Unexpected internal state at /opt/synapse/cache/db.sqlite")

    monkeypatch.setattr(service, "ask", fake_ask)
    client = TestClient(service.app, raise_server_exceptions=False)

    response = client.post("/ask", json={"question": "What is OSPF?"})

    assert response.status_code == 502
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert body["error"] == "internal service error"
    # Internal path must not leak
    assert "/opt/synapse" not in body["error"]
    assert "db.sqlite" not in body["error"]




def test_service_rejects_non_object_json_with_400(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")
    client = TestClient(service.app)

    response = client.post("/ask", json=["not", "an", "object"])

    assert response.status_code == 400
    body = response.json()
    assert body["error_code"] == "bad_request"
    assert body["error"] == "request body must be a JSON object"


def test_service_rejects_oversized_request_before_json_parsing(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")
    monkeypatch.setenv("SYNAPSE_MAX_REQUEST_BYTES", "32")
    client = TestClient(service.app)

    response = client.post("/ask", content=b"{" + b"x" * 64 + b"}", headers={"content-type": "application/json"})

    assert response.status_code == 413
    assert response.json()["error_code"] == "payload_too_large"


def test_webhook_auth_fails_closed_when_token_missing(monkeypatch):
    monkeypatch.delenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "false")
    client = TestClient(service.app)

    response = client.post("/webhook/synapse/ask", json={"question": "What is OSPF?"})

    assert response.status_code == 401
    body = response.json()
    assert body["error_code"] == "unauthorized"


@pytest.mark.parametrize(
    ("headers"),
    [
        {"X-Synapse-Token": "secret"},
        {"Authorization": "Bearer secret"},
    ],
)
def test_webhook_ask_accepts_synapse_token(monkeypatch, headers):
    monkeypatch.setenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", "secret")
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "false")
    monkeypatch.setattr(service, "ask", lambda payload: {"answer": "ok", "sources": []})
    client = TestClient(service.app)

    response = client.post("/webhook/synapse/ask", json={"question": "What is OSPF?"}, headers=headers)

    assert response.status_code == 200
    assert response.json() == {"answer": "ok", "sources": []}


def test_webhook_note_delegates_to_ingest(monkeypatch):
    monkeypatch.setenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", "secret")
    captured = {}

    def fake_ingest(payload):
        captured["payload"] = payload
        return {"status": "ok", "publisher": "wikijs"}

    monkeypatch.setattr(service, "ingest", fake_ingest)
    client = TestClient(service.app)

    response = client.post(
        "/webhook/synapse/note",
        json={"path": "Demo/Note.md", "content": "# Note"},
        headers={"X-Synapse-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "publisher": "wikijs"}
    assert captured["payload"] == {"path": "Demo/Note.md", "content": "# Note"}


def test_webhook_index_note_forces_index_only_ingest(monkeypatch):
    monkeypatch.setenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", "secret")
    captured = {}

    def fake_ingest(payload):
        captured["payload"] = payload
        return {"status": "indexed", "publisher_status": "skipped"}

    monkeypatch.setattr(service, "ingest", fake_ingest)
    client = TestClient(service.app)

    response = client.post(
        "/webhook/synapse/index-note",
        json={"path": "Demo/Note.md", "content": "# Note", "publish": True, "format": True},
        headers={"X-Synapse-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "indexed", "publisher_status": "skipped"}
    assert captured["payload"]["publish"] is False
    assert captured["payload"]["format"] is False


def test_direct_notes_endpoint_reuses_indexed_note_lister(monkeypatch):
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")
    captured = {}

    def fake_list_indexed_notes(payload):
        captured["payload"] = payload
        return {"notes": [{"source_path": "Synapse-Demo/ospf.md", "title": "OSPF Routing"}], "count": 1}

    monkeypatch.setattr(service, "list_indexed_notes", fake_list_indexed_notes)
    client = TestClient(service.app)

    response = client.post("/notes", json={"query": "ospf"})

    assert response.status_code == 200
    assert response.json() == {"notes": [{"source_path": "Synapse-Demo/ospf.md", "title": "OSPF Routing"}], "count": 1}
    assert captured["payload"] == {"query": "ospf"}


def test_webhook_notes_accepts_synapse_token(monkeypatch):
    monkeypatch.setenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", "secret")
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "false")
    monkeypatch.setattr(service, "list_indexed_notes", lambda payload: {"notes": [{"source_path": "Synapse-Demo/ospf.md"}], "count": 1})
    client = TestClient(service.app)

    response = client.post(
        "/webhook/synapse/notes",
        json={},
        headers={"X-Synapse-Token": "secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"notes": [{"source_path": "Synapse-Demo/ospf.md"}], "count": 1}


class FakeTransport:
    def request(self, method, url, payload, headers=None):
        raise AssertionError("transport should not be reached in this interface test")


def test_settings_are_validated_and_secret_safe():
    settings = Settings.from_env({"WIKIJS_API_TOKEN": "real-secret", "SYNAPSE_AUTH_DISABLED": "true"})
    settings.validate()
    assert "real-secret" not in repr(settings)
    with pytest.raises(ValueError, match="SYNAPSE_WEBHOOK_AUTH_TOKEN"):
        Settings.from_env({"SYNAPSE_AUTH_DISABLED": "false"}).validate()


def test_settings_resolve_file_backed_secret_and_reject_url_credentials(tmp_path):
    secret_file = tmp_path / "webhook"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    settings = Settings.from_env(
        {
            "SYNAPSE_WEBHOOK_AUTH_TOKEN_FILE": str(secret_file),
            "SYNAPSE_AUTH_DISABLED": "false",
            "QDRANT_BASE_URL": "http://qdrant:6333",
        }
    )
    settings.validate()
    assert settings["SYNAPSE_WEBHOOK_AUTH_TOKEN"] == "file-secret"
    with pytest.raises(ValueError, match="URL credentials"):
        Settings.from_env(
            {
                "SYNAPSE_AUTH_DISABLED": "true",
                "QDRANT_BASE_URL": "http://user:" + "password" + "@qdrant:6333",
            }
        ).validate()


def test_webhook_auth_accepts_file_backed_token(monkeypatch, tmp_path):
    secret_file = tmp_path / "webhook"
    secret_file.write_text("file-secret\n", encoding="utf-8")
    monkeypatch.delenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", raising=False)
    monkeypatch.setenv("SYNAPSE_WEBHOOK_AUTH_TOKEN_FILE", str(secret_file))
    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "false")
    monkeypatch.setattr(service, "ask", lambda payload: {"answer": "ok", "sources": []})

    response = TestClient(service.app).post(
        "/webhook/synapse/ask",
        json={"question": "What is OSPF?"},
        headers={"X-Synapse-Token": "file-secret"},
    )

    assert response.status_code == 200


def test_runtime_exposes_ingest_answer_and_notes(monkeypatch):
    runtime = SynapseRuntime(Settings.from_env({}), FakeTransport())
    monkeypatch.setattr(runtime_module, "ask", lambda payload, **kwargs: {"answer": payload["question"]})
    monkeypatch.setattr(runtime_module, "ingest", lambda payload, **kwargs: {"status": payload["status"]})
    monkeypatch.setattr(runtime_module, "list_indexed_notes", lambda payload, **kwargs: {"notes": [payload["query"]]})
    assert runtime.answer_question({"question": "hello"}) == {"answer": "hello"}
    assert runtime.ingest_note({"status": "ok"}) == {"status": "ok"}
    assert runtime.indexed_notes({"query": "ospf"}) == {"notes": ["ospf"]}


def test_application_factory_routes_through_injected_runtime(monkeypatch):
    class Runtime:
        def answer_question(self, payload):
            return {"answer": payload["question"], "sources": []}

        def indexed_notes(self, payload):
            return {"notes": [], "count": 0}

        def ingest_note(self, payload):
            return {"status": "indexed" if payload.get("publish") is False else "ok"}

    monkeypatch.setenv("SYNAPSE_AUTH_DISABLED", "true")
    client = TestClient(create_app(Runtime()))
    assert client.post("/webhook/synapse/ask", json={"question": "hello"}).json()["answer"] == "hello"
    assert client.post("/webhook/synapse/index-note", json={"content": "note"}).json()["status"] == "indexed"


def test_http_timeout_parsing_is_bounded(monkeypatch):
    for raw, expected in (("5", 5.0), ("invalid", 180.0), ("0.2", 1.0)):
        monkeypatch.setenv("SYNAPSE_HTTP_TIMEOUT_SECONDS", raw)
        assert http_client.default_timeout_seconds() == expected
