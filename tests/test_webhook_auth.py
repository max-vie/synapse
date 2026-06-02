import json
import os
import sys
from pathlib import Path
from unittest.mock import Mock, patch

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask import client as ask_client  # noqa: E402

from scripts.e2e import obsidian_vault


class FakeResponse:
    def __init__(self, body: str = "{}"):
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.body


def test_ask_client_sends_optional_auth_header():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse('{"ok": true}')

    with patch("urllib.request.urlopen", fake_urlopen):
        assert ask_client.post_json("http://example.test/webhook", {"question": "hi"}, auth_token="secret-token") == {"ok": True}

    assert captured["request"].headers["X-synapse-token"] == "secret-token"


def test_obsidian_post_note_sends_optional_auth_header(tmp_path: Path):
    vault = tmp_path / "vault"
    note = vault / "Demo" / "Note.md"
    note.parent.mkdir(parents=True)
    note.write_text("# Note\n", encoding="utf-8")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse('{"status":"ok"}')

    args = Mock(vault=str(vault), path="Demo/Note.md", webhook="http://example.test/webhook", timeout=5, auth_token="secret-token")
    with patch("urllib.request.urlopen", fake_urlopen):
        assert obsidian_vault.post_note(args) == 0

    assert captured["request"].headers["X-synapse-token"] == "secret-token"


def test_clients_can_read_auth_token_from_environment(monkeypatch):
    monkeypatch.setenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", "env-token")
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        return FakeResponse('{"ok": true}')

    with patch("urllib.request.urlopen", fake_urlopen):
        ask_client.post_json("http://example.test/webhook", {"question": "hi"})

    assert captured["request"].headers["X-synapse-token"] == "env-token"


def test_list_indexed_notes_uses_notes_webhook_and_auth_header():
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse('{"notes":[{"source_path":"Synapse-Demo/ospf.md","title":"OSPF Routing"}],"count":1}')

    with patch("urllib.request.urlopen", fake_urlopen):
        result = ask_client.list_indexed_notes(
            "http://localhost:15515/webhook/synapse/ask",
            query="ospf",
            timeout=7,
            auth_token="secret-token",
        )

    assert result == [{"source_path": "Synapse-Demo/ospf.md", "title": "OSPF Routing"}]
    assert captured["timeout"] == 7
    assert captured["request"].full_url == "http://localhost:15515/webhook/synapse/notes"
    assert captured["request"].headers["X-synapse-token"] == "secret-token"
    assert json.loads(captured["request"].data.decode("utf-8")) == {"query": "ospf"}
