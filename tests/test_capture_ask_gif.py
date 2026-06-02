import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CAPTURE_SCRIPT = ROOT / "scripts" / "capture" / "capture_ask_gif.py"


def load_capture_module():
    spec = importlib.util.spec_from_file_location("capture_ask_gif", CAPTURE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_capture_harness_preserves_full_rag_answer_contract():
    module = load_capture_module()

    assert module.FINAL_HOLD_SECONDS == 6.0
    source = CAPTURE_SCRIPT.read_text(encoding="utf-8")
    assert "OSPF uses Dijkstra's Shortest Path First algorithm. [1]" in source
    assert '"answer": "OSPF uses Dijkstra. [1]"' not in source
