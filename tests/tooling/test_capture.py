import json
import urllib.request

from scripts.capture import capture_ask_gif


def test_capture_harness_preserves_full_rag_answer_contract(monkeypatch):
    monkeypatch.setattr(capture_ask_gif, "BACKEND_DELAY_SECONDS", 0)
    server, _thread = capture_ask_gif.start_harness(0)
    port = server.server_address[1]
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/webhook/synapse/ask",
        data=json.dumps({"question": capture_ask_gif.QUESTION, "source_path": capture_ask_gif.SOURCE_PATH}).encode(),
        headers={"Content-Type": "application/json", "X-Synapse-Token": capture_ask_gif.WEBHOOK_TOKEN},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=2) as response:
            payload = json.loads(response.read())
    finally:
        server.shutdown()
        server.server_close()
    assert capture_ask_gif.FINAL_HOLD_SECONDS == 6.0
    assert "Shortest Path First" in payload["answer"]
    assert payload["sources"][0]["source_path"] == capture_ask_gif.SOURCE_PATH
