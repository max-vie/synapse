import os

import pytest

# Prefixes that leak from a sourced .env/shell into tests and break assertions.
_ENV_PREFIXES = ("SYNAPSE_", "OLLAMA_", "WIKIJS_", "QDRANT_", "OBSIDIAN_VAULT") + ("SYNAPSE_ASK_",)


@pytest.fixture(autouse=True)
def _isolate_synapse_env(monkeypatch):
    """Save, clear, and restore environment variables that the Synapse stack reads.

    When ``.env`` has been sourced into the shell (after ``make lab-up``), values
    like ``SYNAPSE_ASK_WEBHOOK_URL`` leak into the test process and break tests
    that assert empty-string defaults.  This fixture removes them at the start of
    every test and reinstates them afterward so the developer's shell is not
    permanently modified."""
    saved: dict[str, str] = {}
    for key in list(os.environ):
        if any(key.startswith(p) for p in _ENV_PREFIXES):
            saved[key] = os.environ.pop(key)
    try:
        yield
    finally:
        for key, value in saved.items():
            os.environ[key] = value
        # Remove any test-polluted keys the test itself may have set.
        for key in list(os.environ):
            if any(key.startswith(p) for p in _ENV_PREFIXES) and key not in saved:
                os.environ.pop(key, None)
