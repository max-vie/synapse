"""Focused tests for HTTP error sanitization in Ask/synapse_ask/client.py.

Proves that:
- Default errors hide raw response bodies, internal URLs, and token-like values.
- Debug mode shows full detail (with tokens still redacted).
- SYNAPSE_ASK_DEBUG env var controls debug mode.
- --debug flag integrates with the CLI.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

ASK_DIR = Path(__file__).resolve().parents[1] / "Ask"
if str(ASK_DIR) not in sys.path:
    sys.path.insert(0, str(ASK_DIR))

from synapse_ask.client import (
    SynapseHTTPError,
    _is_debug,
    _sanitize_message,
    ask_question,
    auth_headers,
    post_json,
)
from synapse_ask.cli import build_parser


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeHTTPError(Exception):
    """Mimics urllib.error.HTTPError for testing."""
    def __init__(self, code: int, body: str):
        self.code = code
        self._body = body.encode("utf-8")

    def read(self):
        return self._body


def _make_urlopen_raising(code: int, body: str):
    """Return a fake urlopen that raises an HTTPError-like exception."""
    def fake_urlopen(request, timeout):
        raise FakeHTTPError(code, body)
    return fake_urlopen


# ---------------------------------------------------------------------------
# SynapseHTTPError
# ---------------------------------------------------------------------------

class TestSynapseHTTPErrorDefault:
    """Default (non-debug) error messages must be concise and safe."""

    def test_concise_message_format(self):
        err = SynapseHTTPError(401, "http://internal:8080/webhook", '{"detail":"bad token"}')
        assert str(err) == "HTTP 401 from Synapse webhook"

    def test_concise_message_no_url(self):
        err = SynapseHTTPError(502, "http://192.168.0.11:15515/webhook/synapse/note", "upstream error")
        assert "192.168" not in str(err)
        assert "internal" not in str(err)

    def test_concise_message_no_response_body(self):
        err = SynapseHTTPError(500, "http://localhost/webhook", '{"message":"Error in workflow"}')
        assert "Error in workflow" not in str(err)
        assert "message" not in str(err)

    def test_concise_message_no_token_in_url(self):
        err = SynapseHTTPError(403, "http://host/webhook?token=sekret123", "no")
        assert "sekret123" not in str(err)

    def test_status_code_accessible(self):
        err = SynapseHTTPError(404, "http://x/", "not found")
        assert err.status_code == 404

    def test_body_accessible_on_error_object(self):
        """Full body is still available on the exception object for logging."""
        err = SynapseHTTPError(500, "http://x/", "internal server error detail")
        assert err.body == "internal server error detail"

    def test_url_accessible_on_error_object(self):
        err = SynapseHTTPError(500, "http://192.168.0.11:15515/webhook", "err")
        assert err.url == "http://192.168.0.11:15515/webhook"


class TestSynapseHTTPErrorDebug:
    """Debug error messages include URL and body (but redact tokens)."""

    def test_debug_includes_url(self):
        err = SynapseHTTPError(502, "http://synapse:15515/webhook", "bad gateway", debug=True)
        assert "http://synapse:15515/webhook" in str(err)

    def test_debug_includes_body(self):
        err = SynapseHTTPError(500, "http://x/", '{"message":"Error in workflow"}', debug=True)
        assert "Error in workflow" in str(err)

    def test_debug_redacts_tokens_in_body(self):
        body = '{"token=abc123"}'
        err = SynapseHTTPError(401, "http://x/", body, debug=True)
        msg = str(err)
        assert "abc123" not in msg
        assert "<redacted>" in msg

    def test_debug_redacts_bearer_in_body(self):
        body = 'Bearer sk-live-token-12345 failed'
        err = SynapseHTTPError(401, "http://x/", body, debug=True)
        msg = str(err)
        assert "sk-live-token-12345" not in msg
        assert "<redacted>" in msg

    def test_debug_redacts_x_synapse_token_header_in_body(self):
        body = 'X-Synapse-Token: my-secret-key'
        err = SynapseHTTPError(401, "http://x/", body, debug=True)
        msg = str(err)
        assert "my-secret-key" not in msg


# ---------------------------------------------------------------------------
# _sanitize_message
# ---------------------------------------------------------------------------

class TestSanitizeMessage:
    def test_redacts_token_equals(self):
        assert "_token=secret" not in _sanitize_message("_token=secret123")
        assert "_token=<redacted>" in _sanitize_message("_token=secret123")

    def test_redacts_bearer(self):
        assert "sk-abc" not in _sanitize_message("Bearer sk-abc")
        assert "Bearer <redacted>" in _sanitize_message("Bearer sk-abc")

    def test_redacts_x_synapse_token(self):
        assert "mykey" not in _sanitize_message("X-Synapse-Token: mykey")
        assert "X-Synapse-Token: <redacted>" in _sanitize_message("X-Synapse-Token: mykey")

    def test_leaves_plain_text(self):
        msg = "HTTP 500 from Synapse webhook"
        assert _sanitize_message(msg) == msg


# ---------------------------------------------------------------------------
# _is_debug
# ---------------------------------------------------------------------------

class TestIsDebug:
    @pytest.mark.parametrize("val", ["true", "1", "yes", "True", "YES"])
    def test_truthy_values(self, val, monkeypatch):
        monkeypatch.setenv("SYNAPSE_ASK_DEBUG", val)
        assert _is_debug() is True

    @pytest.mark.parametrize("val", ["false", "0", "", "no", "random"])
    def test_falsy_values(self, val, monkeypatch):
        monkeypatch.setenv("SYNAPSE_ASK_DEBUG", val)
        assert _is_debug() is False

    def test_unset(self, monkeypatch):
        monkeypatch.delenv("SYNAPSE_ASK_DEBUG", raising=False)
        assert _is_debug() is False


# ---------------------------------------------------------------------------
# post_json integration
# ---------------------------------------------------------------------------

class TestPostJsonErrorSanitization:
    """post_json must raise SynapseHTTPError (not raw RuntimeError) with sanitised messages."""

    def test_default_error_hides_body_and_url(self):
        """When an HTTPError occurs, default error must not leak body or URL."""
        import urllib.error

        class RealishHTTPError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://secret-host:15515/webhook", 401, "Unauthorized", {}, None)

            def read(self):
                return b'{"detail":"invalid token xyz789"}'

        err_instance = RealishHTTPError()

        with patch("synapse_ask.client.urllib.request.urlopen", side_effect=err_instance):
            with pytest.raises(SynapseHTTPError) as exc_info:
                post_json("http://secret-host:15515/webhook", {"q": "test"})

        msg = str(exc_info.value)
        assert "HTTP 401 from Synapse webhook" == msg
        assert "secret-host" not in msg
        assert "invalid token" not in msg
        assert "xyz789" not in msg

    def test_debug_error_shows_url_and_body(self):
        """With debug=True, error must include URL and body, but redact tokens."""
        import urllib.error

        class RealishHTTPError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://synapse:15515/webhook", 502, "Bad Gateway", {}, None)

            def read(self):
                return b'{"error":"upstream down"}'

        err_instance = RealishHTTPError()

        with patch("synapse_ask.client.urllib.request.urlopen", side_effect=err_instance):
            with pytest.raises(SynapseHTTPError) as exc_info:
                post_json("http://synapse:15515/webhook", {"q": "test"}, debug=True)

        msg = str(exc_info.value)
        assert "502" in msg
        assert "http://synapse:15515/webhook" in msg
        assert "upstream down" in msg

    def test_debug_error_redacts_tokens_in_body(self):
        """Tokens in response body must be redacted even in debug mode."""
        import urllib.error

        class RealishHTTPError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://x/", 401, "Unauthorized", {}, None)

            def read(self):
                return b'{"token=sk-live-key-999"}'

        err_instance = RealishHTTPError()

        with patch("synapse_ask.client.urllib.request.urlopen", side_effect=err_instance):
            with pytest.raises(SynapseHTTPError) as exc_info:
                post_json("http://x/", {"q": "test"}, debug=True)

        msg = str(exc_info.value)
        assert "sk-live-key-999" not in msg
        assert "<redacted>" in msg


# ---------------------------------------------------------------------------
# ask_question error propagation
# ---------------------------------------------------------------------------

class TestAskQuestionErrorPropagation:
    """ask_question must propagate SynapseHTTPError without wrapping."""

    def test_raises_synapse_http_error_not_runtime_error(self):
        import urllib.error

        class RealishHTTPError(urllib.error.HTTPError):
            def __init__(self):
                super().__init__("http://x/", 401, "Unauthorized", {}, None)

            def read(self):
                return b'{"detail":"no"}'

        with patch("synapse_ask.client.urllib.request.urlopen", side_effect=RealishHTTPError()):
            with pytest.raises(SynapseHTTPError) as exc_info:
                ask_question("test", "http://x/", None, 5, "tok")

        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# CLI --debug flag
# ---------------------------------------------------------------------------

class TestCLIDebugFlag:
    def test_debug_flag_exists(self):
        parser = build_parser()
        args = parser.parse_args(["--debug", "--text", "hello"])
        assert args.debug is True

    def test_debug_flag_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args(["--text", "hello"])
        assert args.debug is False


# ---------------------------------------------------------------------------
# auth_headers must not leak tokens into error messages
# ---------------------------------------------------------------------------

class TestAuthHeadersSafety:
    def test_auth_headers_contains_token(self):
        headers = auth_headers("my-secret-token")
        assert headers["X-Synapse-Token"] == "my-secret-token"

    def test_auth_headers_empty_without_token(self, monkeypatch):
        monkeypatch.delenv("SYNAPSE_WEBHOOK_AUTH_TOKEN", raising=False)
        headers = auth_headers("")
        assert "X-Synapse-Token" not in headers