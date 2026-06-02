from scripts.synapse import http_client


def test_default_timeout_uses_env(monkeypatch):
    monkeypatch.setenv("SYNAPSE_HTTP_TIMEOUT_SECONDS", "240")

    assert http_client.default_timeout_seconds() == 240.0


def test_default_timeout_falls_back_for_invalid_env(monkeypatch):
    monkeypatch.setenv("SYNAPSE_HTTP_TIMEOUT_SECONDS", "not-a-number")

    assert http_client.default_timeout_seconds() == 60.0


def test_default_timeout_has_one_second_floor(monkeypatch):
    monkeypatch.setenv("SYNAPSE_HTTP_TIMEOUT_SECONDS", "0")

    assert http_client.default_timeout_seconds() == 1.0
