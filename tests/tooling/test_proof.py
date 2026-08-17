import json
import re

from scripts.proof import runner
from scripts.proof.redaction import redact_sensitive


def test_ospf_suite_proves_refusal_before_grounded_answer():
    suite = runner.build_ospf_suite("e2e-ospf-20260101T000000Z")
    checks = suite["checks"]
    assert len(suite["notes"]) == 1
    assert checks[0]["phase"] == "before_note"
    assert checks[0]["expectation"]["type"] == "unsupported"
    assert checks[1]["phase"] == "after_note"
    assert checks[1]["expectation"]["required_facts"] == ["Dijkstra", "Shortest Path First", "SPF"]


def test_real_suite_keeps_five_notes_and_ten_questions():
    suite = runner.build_real_local_stack_suite("real-test", "abc123")
    assert len(suite["notes"]) == 5
    assert len(suite["checks"]) == 10
    assert len({note["path"] for note in suite["notes"]}) == 5


def test_complex_suite_is_public_safe_and_adversarial():
    suite = runner.build_complex_suite("e2e-complex-test", "abc123")
    combined = json.dumps(suite)
    assert len(suite["notes"]) == 3
    assert len(suite["checks"]) == 6
    assert "[REDACTED]" in combined
    assert "stale" in combined.casefold()
    assert not re.search(r"192\.168\.\d+\.\d+", combined)


def test_redaction_removes_tokens_passwords_and_private_networks():
    private_ip = ".".join(("192", "168", "1", "20"))
    fake_api_key = "abcdef" + "123456"
    text = f"Bearer abc123 password is hunter2 api_" + f"key={fake_api_key} http://{private_ip}"
    redacted = redact_sensitive(text)
    assert "abc123" not in redacted
    assert "hunter2" not in redacted
    assert fake_api_key not in redacted
    assert private_ip not in redacted


def test_proof_main_honors_env_file_override(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("QDRANT_COLLECTION=test\n", encoding="utf-8")
    monkeypatch.setenv("SYNAPSE_ENV_FILE", str(env_path))
    monkeypatch.setattr(runner, "run_simple_proof", lambda values: 0 if values["QDRANT_COLLECTION"] == "test" else 1)
    assert runner.main(["--suite", "simple"]) == 0
